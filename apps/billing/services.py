from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction, models
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceItem, PaymentReceipt, PosRegisterShift
from apps.crm.models import Account
from apps.inventory.models import InventoryItem, Warehouse, StockBalance, StockMovement, InventoryBatch


@transaction.atomic
def execute_pos_sale(
    organization,
    user,
    warehouse,
    account=None,
    items_data=None,
    cart_items=None,
    payment_method=PaymentReceipt.PaymentMethod.CASH,
    price_tier='RETAIL',
    cash_received=None,
    notes=''
) -> Invoice:
    """
    Motor Transaccional de Venta Rápida en Mostrador (Terminal POS).
    1. Valida cliente (o inicializa Consumidor Final).
    2. Aplica regla de escala de precios (Detalle, Contratista, Mayorista).
    3. Aplica estricta regla sanitaria FEFO:
       - Selecciona el lote más próximo a vencer no caducado.
       - Si el lote está vencido (expiry_status == 'EXPIRED'), rechaza la transacción con ValidationError.
       - Descuenta existencias del lote.
    4. Descuenta existencias de StockBalance y registra movimiento inmutable OUT_SALE_POS en Kardex.
    5. Emite Factura Fiscal DGI (Invoice) y Recibo Oficial de Caja (ROC - PaymentReceipt).
    """
    items_data = items_data or cart_items
    if not items_data:
        raise ValidationError("El carrito de venta POS no contiene productos para facturar.")

    if not warehouse:
        warehouse = Warehouse.objects.filter(organization=organization, is_active=True).first()
        if not warehouse:
            raise ValidationError("No existe ninguna bodega activa configurada para registrar la salida de inventario.")

    # 1. Resolver o inicializar cliente de mostrador
    if not account:
        account = Account.objects.filter(
            organization=organization,
            commercial_name__icontains='Consumidor Final'
        ).first()
        if not account:
            account = Account.objects.create(
                organization=organization,
                commercial_name='Consumidor Final / Mostrador',
                legal_name='Cliente de Mostrador',
                tax_id='',
                account_type=Account.AccountType.INDIVIDUAL,
                lifecycle_stage=Account.LifecycleStage.ACTIVE,
            )

    # 2. Inicializar Factura Fiscal DGI
    invoice = Invoice.objects.create(
        organization=organization,
        account=account,
        payment_condition=Invoice.PaymentCondition.CASH,
        status=Invoice.Status.ISSUED,
        currency_code=organization.currency,
        currency_symbol=organization.currency_symbol,
        apply_tax=True,
        tax_rate=Decimal('15.00'),
        created_by=user,
        notes=notes or "Venta en Mostrador / Terminal POS",
    )

    # 3. Procesar partidas, FEFO y descuentos de inventario
    for entry in items_data:
        raw_item = entry.get('item')
        if isinstance(raw_item, InventoryItem):
            item = raw_item
        else:
            item_id = entry.get('item_id') or raw_item
            item = InventoryItem.objects.select_for_update().get(id=item_id, organization=organization)

        qty = Decimal(str(entry.get('quantity', 1)))
        if qty <= Decimal('0.00'):
            raise ValidationError("La cantidad a facturar debe ser estrictamente mayor a 0.")

        # Resolución de precio unitario según tier o entrada
        explicit_price = entry.get('unit_price')
        if explicit_price is not None and Decimal(str(explicit_price)) > Decimal('0.00'):
            unit_price = Decimal(str(explicit_price))
        else:
            tier = (entry.get('price_tier') or price_tier or 'RETAIL').upper()
            if tier == 'CONTRACTOR':
                unit_price = item.price_contractor if item.price_contractor > Decimal('0.00') else item.price_retail
            elif tier == 'WHOLESALE' or (item.wholesale_min_qty and qty >= item.wholesale_min_qty and item.price_wholesale > Decimal('0.00')):
                unit_price = item.price_wholesale if item.price_wholesale > Decimal('0.00') else item.price_retail
            else:
                unit_price = item.price_retail if item.price_retail > Decimal('0.00') else item.unit_cost

            # Fallback seguro
            if unit_price <= Decimal('0.00'):
                unit_price = item.unit_cost if item.unit_cost > Decimal('0.00') else Decimal('1.00')

        # Control FEFO & Lotes Farmacéuticos
        batch = None
        raw_batch = entry.get('batch')
        batch_id = entry.get('batch_id') or (raw_batch.id if isinstance(raw_batch, InventoryBatch) else raw_batch)

        if batch_id:
            batch = InventoryBatch.objects.select_for_update().filter(id=batch_id, organization=organization).first()
            if not batch:
                raise ValidationError("El lote sanitario especificado no existe o no pertenece a la empresa.")
        elif item.requires_batch_control or organization.is_pharmacy_vertical() or item.batches.filter(warehouse=warehouse).exists():
            # Buscar lote más próximo a vencer (Regla FEFO)
            # Primero tomamos el lote que tenga existencia mayor a cero
            fefo_candidate = InventoryBatch.objects.select_for_update().filter(
                organization=organization,
                warehouse=warehouse,
                item=item,
                quantity_available__gt=Decimal('0.00')
            ).order_by('expiration_date').first()

            if fefo_candidate:
                batch = fefo_candidate
            else:
                # Si no hay con saldo positivo, verificar si hay alguno registrado (para reportar si está vencido o agotado)
                any_batch = InventoryBatch.objects.select_for_update().filter(
                    organization=organization,
                    warehouse=warehouse,
                    item=item
                ).order_by('expiration_date').first()
                if any_batch and any_batch.expiry_status == 'EXPIRED':
                    raise ValidationError(
                        f"Operación rechazada: El lote {any_batch.batch_number} de '{item.name}' está vencido (bloqueado por normativa sanitaria MINSA)."
                    )
                raise ValidationError(f"No hay lotes disponibles para el producto '{item.name}' en la bodega seleccionada.")

        # Validación sanitaria inquebrantable de caducidad
        if batch:
            if batch.expiry_status == 'EXPIRED':
                raise ValidationError(
                    f"Operación rechazada: El lote {batch.batch_number} de '{item.name}' está vencido (bloqueado por normativa sanitaria MINSA)."
                )
            if batch.quantity_available < qty:
                raise ValidationError(
                    f"Existencia insuficiente en el lote {batch.batch_number} ({batch.quantity_available} {item.unit} disponibles, se solicitaron {qty} {item.unit})."
                )
            # Descontar lote
            batch.quantity_available -= qty
            batch.save(update_fields=['quantity_available', 'updated_at'])

        # Descontar existencia global de la bodega (StockBalance)
        balance, _ = StockBalance.objects.select_for_update().get_or_create(
            organization=organization,
            warehouse=warehouse,
            item=item,
            defaults={'quantity': Decimal('0.00')}
        )
        balance.quantity -= qty
        balance.save(update_fields=['quantity', 'updated_at'])

        # Partida de Factura Fiscal
        item_description = f"{item.name} [Lote: {batch.batch_number}]" if batch else item.name
        InvoiceItem.objects.create(
            invoice=invoice,
            item_type='PRODUCT',
            code=item.sku,
            description=item_description,
            unit=item.unit,
            quantity=qty,
            unit_price=unit_price,
            discount_percent=Decimal('0.00'),
        )

        # Kardex Inmutable OUT_SALE_POS
        StockMovement.objects.create(
            organization=organization,
            movement_type=StockMovement.MovementType.OUT_SALE_POS,
            warehouse=warehouse,
            item=item,
            batch=batch,
            invoice=invoice,
            quantity=qty,
            unit_cost_snapshot=item.unit_cost,
            balance_after=balance.quantity,
            reference_note=f"Venta Mostrador POS {invoice.number} - {account.commercial_name}",
            performed_by=user,
        )

    # 4. Cálculo final de impuestos y totales
    # Medicamentos básicos para consumo humano están exentos de IVA según Ley 822 Art. 127
    if organization.is_pharmacy_vertical():
        invoice.apply_tax = False

    invoice.recalculate_totals()
    invoice.save()

    # 5. Emisión de Recibo Oficial de Caja (ROC) al contado
    receipt = PaymentReceipt.objects.create(
        organization=organization,
        invoice=invoice,
        payment_date=timezone.now().date(),
        payment_method=payment_method or PaymentReceipt.PaymentMethod.CASH,
        reference_number=f"POS-{invoice.number}",
        currency_paid=invoice.currency_code,
        amount_in_payment_currency=invoice.net_receivable,
        amount_applied_to_invoice=invoice.net_receivable,
        exchange_rate_applied=invoice.exchange_rate,
        received_by=user,
        notes="Cancelación total de contado en terminal de mostrador (POS)",
    )

    # 6. Marcar factura cancelada
    invoice.amount_paid = invoice.net_receivable
    invoice.balance_due = Decimal('0.00')
    invoice.status = Invoice.Status.PAID

    # 7. Vinculación automática a Turno POS activo de la organización
    active_shift = PosRegisterShift.objects.filter(
        organization=organization,
        status=PosRegisterShift.Status.OPEN,
    ).filter(
        models.Q(cashier=user) | models.Q(cashier__isnull=False)
    ).order_by('-opened_at').first()

    if active_shift:
        invoice.pos_shift = active_shift

    invoice.save(update_fields=['amount_paid', 'balance_due', 'status', 'pos_shift', 'updated_at'])
    invoice.receipt = receipt

    return invoice

