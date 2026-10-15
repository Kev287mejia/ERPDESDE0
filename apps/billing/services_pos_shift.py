import hashlib
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction, models
from django.utils import timezone

from apps.billing.models import PosRegisterShift, Invoice, PaymentReceipt


def open_pos_shift(organization, cashier, opening_cash_nio, register_name: str = 'CAJA-PRINCIPAL-01') -> PosRegisterShift:
    """
    Abre un nuevo turno de caja POS para el cajero y organización especificados.
    Valida que no exista otro turno con estado OPEN para este cajero en la misma organización.
    """
    already_open = PosRegisterShift.objects.filter(
        organization=organization,
        cashier=cashier,
        status=PosRegisterShift.Status.OPEN,
    ).exists()

    if already_open:
        raise ValidationError("Ya existe un turno de caja abierto para este cajero en la organización.")

    opening_amount = Decimal(str(opening_cash_nio or '0.00')).quantize(Decimal('0.01'))
    if opening_amount < Decimal('0.00'):
        raise ValidationError("El fondo fijo inicial de apertura no puede ser negativo.")

    shift = PosRegisterShift.objects.create(
        organization=organization,
        cashier=cashier,
        register_name=register_name or 'CAJA-PRINCIPAL-01',
        opening_cash_nio=opening_amount,
        expected_cash_in_drawer_nio=opening_amount,
        status=PosRegisterShift.Status.OPEN,
    )
    return shift


def compute_shift_x_cut_metrics(shift: PosRegisterShift) -> dict:
    """
    Calcula en tiempo real las métricas de Corte X Parcial para un turno de caja POS:
    - Cantidad de transacciones/facturas emitidas
    - Total de ventas recaudadas en efectivo
    - Total de ventas en tarjeta / transferencia / crédito
    - Total de ventas globales
    - Efectivo total esperado en gaveta (Fondo Inicial + Ventas Efectivo)
    """
    invoices = list(
        shift.shift_invoices.filter(
            status__in=[Invoice.Status.ISSUED, Invoice.Status.PAID, Invoice.Status.PARTIAL]
        ).select_related('account').prefetch_related('payments').order_by('-issue_date', '-created_at')
    )

    transactions_count = len(invoices)
    cash_sales = Decimal('0.00')
    card_transfer_sales = Decimal('0.00')

    for inv in invoices:
        payments = list(inv.payments.all())
        if payments:
            for p in payments:
                amt = p.amount_applied_to_invoice or p.amount_in_payment_currency
                if p.payment_method == PaymentReceipt.PaymentMethod.CASH:
                    cash_sales += amt
                else:
                    card_transfer_sales += amt
        else:
            if inv.payment_condition == Invoice.PaymentCondition.CASH:
                cash_sales += inv.net_receivable
            else:
                card_transfer_sales += inv.net_receivable

    cash_sales = cash_sales.quantize(Decimal('0.01'))
    card_transfer_sales = card_transfer_sales.quantize(Decimal('0.01'))
    total_sales = (cash_sales + card_transfer_sales).quantize(Decimal('0.01'))
    expected_cash_in_drawer = (shift.opening_cash_nio + cash_sales).quantize(Decimal('0.01'))

    if shift.status == PosRegisterShift.Status.OPEN:
        shift.system_cash_sales_nio = cash_sales
        shift.system_card_transfer_sales_nio = card_transfer_sales
        shift.expected_cash_in_drawer_nio = expected_cash_in_drawer
        shift.transactions_count = transactions_count
        super(PosRegisterShift, shift).save(update_fields=[
            'system_cash_sales_nio',
            'system_card_transfer_sales_nio',
            'expected_cash_in_drawer_nio',
            'transactions_count'
        ])

    return {
        'shift': shift,
        'invoices': invoices,
        'transactions_count': transactions_count,
        'opening_cash_nio': shift.opening_cash_nio,
        'cash_sales_nio': cash_sales,
        'system_cash_sales_nio': cash_sales,
        'card_transfer_sales_nio': card_transfer_sales,
        'system_card_transfer_sales_nio': card_transfer_sales,
        'total_sales_nio': total_sales,
        'expected_cash_in_drawer_nio': expected_cash_in_drawer,
    }


@transaction.atomic
def close_pos_shift_z_cut(shift: PosRegisterShift, declared_cash_nio: Decimal, user, notes: str = '') -> PosRegisterShift:
    """
    Ejecuta el Arqueo Ciego y Cierre de Corte Z Definitivo para el turno de caja POS:
    1. Bloqueo pesimista con select_for_update().
    2. Recalcula las métricas finales de ventas y efectivo esperado.
    3. Registra el efectivo declarado físicamente por el cajero.
    4. Computa la diferencia de caja (declarado - esperado): 0.00 cuadrado, >0 sobrante, <0 faltante.
    5. Genera el sello criptográfico inmutable SHA-256.
    6. Transiciona el turno a CLOSED_Z inmutable.
    """
    shift = PosRegisterShift.objects.select_for_update().get(pk=shift.pk)

    if shift.status == PosRegisterShift.Status.CLOSED_Z:
        raise ValidationError("Un turno con Corte Z sellado es inmutable.")

    compute_shift_x_cut_metrics(shift)
    shift.refresh_from_db()

    declared = Decimal(str(declared_cash_nio or '0.00')).quantize(Decimal('0.01'))
    if declared < Decimal('0.00'):
        raise ValidationError("El monto de efectivo declarado no puede ser negativo.")

    expected = shift.expected_cash_in_drawer_nio
    diff = (declared - expected).quantize(Decimal('0.01'))
    now = timezone.now()

    raw_payload = (
        f"{shift.organization_id}|{shift.shift_number}|{shift.opened_at.isoformat()}|"
        f"{now.isoformat()}|{shift.opening_cash_nio}|{shift.system_cash_sales_nio}|"
        f"{shift.system_card_transfer_sales_nio}|{expected}|{declared}|{diff}|{user.id}"
    )
    audit_hash = hashlib.sha256(raw_payload.encode('utf-8')).hexdigest()

    shift.declared_cash_nio = declared
    shift.cash_difference_nio = diff
    shift.status = PosRegisterShift.Status.CLOSED_Z
    shift.closed_at = now
    shift.closing_notes = (notes or '').strip()
    shift.audit_hash = audit_hash

    super(PosRegisterShift, shift).save()
    return shift
