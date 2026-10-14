from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.operations.models import WorkOrderTimelineLog
from apps.finance.models import (
    BankAccount,
    PettyCashFund,
    PettyCashExpense,
    PettyCashReplenishment,
    FinancialTransaction,
)


@transaction.atomic
def allocate_petty_cash_fund(
    organization,
    fund: PettyCashFund,
    bank_account: BankAccount,
    amount: Decimal,
    user
) -> FinancialTransaction:
    """
    Desembolsa la apertura o dotación inicial de una Caja Chica desde una cuenta bancaria.
    Bloquea la cuenta con select_for_update().
    """
    amt = Decimal(str(amount))
    if amt <= Decimal('0.00'):
        raise ValidationError("El monto a dotar debe ser estrictamente mayor a 0.00.")

    bank = BankAccount.objects.select_for_update().get(pk=bank_account.pk, organization=organization)
    caja = PettyCashFund.objects.select_for_update().get(pk=fund.pk, organization=organization)

    if bank.current_balance < amt:
        raise ValidationError(
            f"Saldo bancario insuficiente en {bank.bank_name} ({bank.account_number}). "
            f"Disponible: C$ {bank.current_balance:,.2f}, Requerido: C$ {amt:,.2f}."
        )

    # 1. Descuento bancario
    bank.current_balance -= amt
    bank.save(update_fields=['current_balance', 'updated_at'])

    # 2. Incremento en caja chica
    caja.current_balance += amt
    caja.save(update_fields=['current_balance', 'updated_at'])

    # 3. Asiento inmutable en libro mayor financiero
    trx = FinancialTransaction.objects.create(
        organization=organization,
        transaction_type=FinancialTransaction.TransactionType.PETTY_CASH_ALLOCATION,
        bank_account=bank,
        petty_cash_fund=caja,
        amount=amt,
        balance_after=caja.current_balance,
        concept=f"Apertura / Dotación de Fondo Fijo {caja.code} ({caja.name})",
        reference_code=f"CHQ-{caja.code}",
        performed_by=user,
    )
    return trx


@transaction.atomic
def record_petty_cash_expense(
    organization,
    fund: PettyCashFund,
    expense_category: str,
    vendor_name: str,
    amount: Decimal,
    description: str,
    user,
    work_order=None,
    vendor_tax_id: str = '',
    invoice_number: str = '',
    spent_at=None,
) -> PettyCashExpense:
    """
    Registra un gasto operativo en el frente de obra.
    Bloquea la caja chica con select_for_update() impidiendo sobregiros o saldos negativos.
    Si se imputa a una OT, asienta el costo y la bitácora técnica automáticamente.
    """
    amt = Decimal(str(amount))
    if amt <= Decimal('0.00'):
        raise ValidationError("El monto del comprobante de gasto debe ser mayor a 0.00.")

    caja = PettyCashFund.objects.select_for_update().get(pk=fund.pk, organization=organization)

    if caja.current_balance < amt:
        raise ValidationError(
            f"Saldo insuficiente en la caja chica '{caja.name}'. "
            f"Disponible en mano: C$ {caja.current_balance:,.2f}, Gasto presentado: C$ {amt:,.2f}. "
            f"Se requiere solicitar reposición de fondo fijo."
        )

    # 1. Descontar saldo físico de la caja
    caja.current_balance -= amt
    caja.save(update_fields=['current_balance', 'updated_at'])

    # 2. Crear comprobante de gasto
    expense = PettyCashExpense.objects.create(
        organization=organization,
        fund=caja,
        work_order=work_order,
        expense_category=expense_category,
        vendor_name=vendor_name,
        vendor_tax_id=vendor_tax_id,
        invoice_number=invoice_number,
        amount=amt,
        description=description,
        spent_at=spent_at or timezone.now().date(),
        created_by=user,
        is_replenished=False,
    )

    # 3. Asiento inmutable en libro mayor financiero
    FinancialTransaction.objects.create(
        organization=organization,
        transaction_type=FinancialTransaction.TransactionType.PETTY_CASH_EXPENSE,
        petty_cash_fund=caja,
        amount=amt,
        balance_after=caja.current_balance,
        concept=f"Comprobante {expense.voucher_number}: {description} ({vendor_name})",
        reference_code=invoice_number or expense.voucher_number,
        performed_by=user,
    )

    # 4. Trazabilidad en la OT de Operaciones (si aplica)
    if work_order:
        WorkOrderTimelineLog.objects.create(
            organization=organization,
            work_order=work_order,
            event_type='PETTY_CASH_EXPENSE',
            summary=f"Gasto operativo imputado: C$ {amt:,.2f} ({expense.get_expense_category_display()})",
            details=(
                f"Folio Recibo: {expense.voucher_number}. "
                f"Proveedor: {vendor_name} (Factura #{invoice_number or 'S/N'}). "
                f"Caja Chica: {caja.name}. "
                f"Justificación: {description}. "
                f"Registrado por: {user.full_name or user.email}."
            ),
            actor=user,
        )

    return expense


@transaction.atomic
def submit_petty_cash_replenishment(
    organization,
    fund: PettyCashFund,
    notes: str,
    user
) -> PettyCashReplenishment:
    """
    Genera el arqueo de caja chica agrupando todos los comprobantes pendientes
    y emite la solicitud de reposición para revisión de Coordinación/Gerencia.
    """
    caja = PettyCashFund.objects.select_for_update().get(pk=fund.pk, organization=organization)
    pending_expenses = list(caja.expenses.filter(is_replenished=False, replenishment__isnull=True))

    if not pending_expenses:
        raise ValidationError("No existen comprobantes de gastos pendientes de reposición en esta caja chica.")

    total_amount = sum((exp.amount for exp in pending_expenses), Decimal('0.00'))

    replenishment = PettyCashReplenishment.objects.create(
        organization=organization,
        fund=caja,
        status=PettyCashReplenishment.Status.SUBMITTED,
        total_expenses_amount=total_amount,
        requested_amount=total_amount,
        notes=notes,
        submitted_by=user,
    )

    # Vincular gastos a esta reposición
    PettyCashExpense.objects.filter(
        pk__in=[exp.pk for exp in pending_expenses]
    ).update(replenishment=replenishment, updated_at=timezone.now())

    return replenishment


@transaction.atomic
def disburse_petty_cash_replenishment(
    organization,
    replenishment: PettyCashReplenishment,
    bank_account: BankAccount,
    user
) -> FinancialTransaction:
    """
    Aprueba y desembolsa la reposición de fondo fijo desde la cuenta bancaria.
    Restaura el saldo físico de la caja chica y marca los gastos como liquidados.
    """
    rep = PettyCashReplenishment.objects.select_for_update().get(pk=replenishment.pk, organization=organization)
    if rep.status == PettyCashReplenishment.Status.DISBURSED:
        raise ValidationError("Esta reposición ya fue desembolsada anteriormente.")

    bank = BankAccount.objects.select_for_update().get(pk=bank_account.pk, organization=organization)
    caja = PettyCashFund.objects.select_for_update().get(pk=rep.fund.pk, organization=organization)

    amt = rep.requested_amount
    if bank.current_balance < amt:
        raise ValidationError(
            f"Saldo bancario insuficiente en {bank.bank_name}. "
            f"Disponible: C$ {bank.current_balance:,.2f}, Monto de reposición: C$ {amt:,.2f}."
        )

    # 1. Descuento bancario
    bank.current_balance -= amt
    bank.save(update_fields=['current_balance', 'updated_at'])

    # 2. Reintegro a la caja chica (topeado al fondo fijo asignado)
    caja.current_balance += amt
    caja.save(update_fields=['current_balance', 'updated_at'])

    # 3. Actualizar estado de la reposición
    rep.status = PettyCashReplenishment.Status.DISBURSED
    rep.approved_by = user
    rep.approved_at = timezone.now()
    rep.disbursed_from_bank = bank
    rep.disbursed_at = timezone.now()
    rep.save(update_fields=[
        'status', 'approved_by', 'approved_at',
        'disbursed_from_bank', 'disbursed_at', 'updated_at'
    ])

    # 4. Marcar gastos como liquidados formalmente
    rep.expenses.all().update(is_replenished=True, updated_at=timezone.now())

    # 5. Asiento inmutable en libro mayor financiero
    trx = FinancialTransaction.objects.create(
        organization=organization,
        transaction_type=FinancialTransaction.TransactionType.PETTY_CASH_REPLENISH,
        bank_account=bank,
        petty_cash_fund=caja,
        amount=amt,
        balance_after=caja.current_balance,
        concept=f"Desembolso de Reposición {rep.code} para {caja.name}",
        reference_code=rep.code,
        performed_by=user,
    )
    return trx
