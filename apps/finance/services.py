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


def ensure_default_chart_of_accounts(organization):
    """
    Garantiza la existencia del catálogo básico NIIF / DGI Nicaragua para el tenant.
    Idempotente: crea únicamente las cuentas faltantes.
    """
    from apps.finance.models import AccountingAccount

    default_accounts = [
        ('1101-01', 'Caja General y Mostrador', AccountingAccount.AccountType.ASSET),
        ('1102-01', 'Bancos Institucionales', AccountingAccount.AccountType.ASSET),
        ('1103-01', 'Clientes por Cobrar (CxC)', AccountingAccount.AccountType.ASSET),
        ('1104-01', 'IVA Crédito Fiscal Acreditable (15%)', AccountingAccount.AccountType.ASSET),
        ('1105-01', 'Anticipo Retención IR Sufrida (1% - 2%)', AccountingAccount.AccountType.ASSET),
        ('1105-02', 'Anticipo Retención IMI Municipal Sufrida (1%)', AccountingAccount.AccountType.ASSET),
        ('2101-01', 'Proveedores Nacionales (CxP)', AccountingAccount.AccountType.LIABILITY),
        ('2102-01', 'IVA Débito Fiscal por Pagar (15%)', AccountingAccount.AccountType.LIABILITY),
        ('2103-01', 'Retenciones IR en la Fuente por Enterar DGI', AccountingAccount.AccountType.LIABILITY),
        ('2103-02', 'Retenciones IMI Alcaldía por Enterar', AccountingAccount.AccountType.LIABILITY),
        ('4101-01', 'Ingresos por Ventas de Bienes y Servicios', AccountingAccount.AccountType.INCOME),
        ('5101-01', 'Costo de Ventas, Compras e Insumos', AccountingAccount.AccountType.EXPENSE),
    ]
    accounts_map = {}
    for code, name, acct_type in default_accounts:
        acc, _ = AccountingAccount.objects.get_or_create(
            organization=organization,
            code=code,
            defaults={'name': name, 'account_type': acct_type, 'is_active': True}
        )
        accounts_map[code] = acc
    return accounts_map


@transaction.atomic
def sync_commercial_and_purchasing_to_ledger(organization, user):
    """
    Puente de Sincronización Contable Automática:
    Asienta pólizas de diario cuadradas (Debe == Haber) para todas las Facturas
    y Órdenes de Compra no sincronizadas previamente.
    """
    from apps.billing.models import Invoice
    from apps.purchasing.models import PurchaseOrder
    from apps.finance.models import JournalEntry, JournalEntryLine

    accounts = ensure_default_chart_of_accounts(organization)
    synced_invoices = 0
    synced_purchases = 0

    # 1. Pólizas de Ventas (Facturas Emitidas / Cobradas)
    invoices = Invoice.objects.filter(
        organization=organization,
        status__in=[Invoice.Status.ISSUED, Invoice.Status.PARTIAL, Invoice.Status.PAID],
    ).exclude(journal_entries__isnull=False)

    for inv in invoices:
        entry = JournalEntry.objects.create(
            organization=organization,
            date=inv.issue_date or timezone.now().date(),
            entry_type=JournalEntry.EntryType.SALES,
            concept=f"Facturación DGI {inv.number} - {inv.account.commercial_name if inv.account else 'Cliente'}",
            reference=inv.number,
            source_invoice=inv,
            created_by=user,
        )

        # DEBE: Clientes por Cobrar (Neto a cobrar)
        JournalEntryLine.objects.create(
            organization=organization,
            entry=entry,
            account=accounts['1103-01'],
            concept=f"CxC Factura {inv.number}",
            debit=inv.net_receivable,
            credit=Decimal('0.00'),
        )

        # DEBE: Retención IR sufrida (si aplica)
        if inv.ir_retention_amount > Decimal('0.00'):
            JournalEntryLine.objects.create(
                organization=organization,
                entry=entry,
                account=accounts['1105-01'],
                concept=f"Retención IR 1%-2% Sufrida {inv.number}",
                debit=inv.ir_retention_amount,
                credit=Decimal('0.00'),
            )

        # DEBE: Retención IMI sufrida (si aplica)
        if inv.imi_retention_amount > Decimal('0.00'):
            JournalEntryLine.objects.create(
                organization=organization,
                entry=entry,
                account=accounts['1105-02'],
                concept=f"Retención IMI 1% Sufrida {inv.number}",
                debit=inv.imi_retention_amount,
                credit=Decimal('0.00'),
            )

        # HABER: Ventas / Ingresos (Base Imponible)
        JournalEntryLine.objects.create(
            organization=organization,
            entry=entry,
            account=accounts['4101-01'],
            concept=f"Ingreso Gravado/Exento {inv.number}",
            debit=Decimal('0.00'),
            credit=inv.subtotal,
        )

        # HABER: IVA Débito Fiscal (si aplica)
        if inv.tax_total > Decimal('0.00'):
            JournalEntryLine.objects.create(
                organization=organization,
                entry=entry,
                account=accounts['2102-01'],
                concept=f"IVA 15% Débito Fiscal {inv.number}",
                debit=Decimal('0.00'),
                credit=inv.tax_total,
            )

        entry.verify_and_save_balance()
        synced_invoices += 1

    # 2. Pólizas de Compras (Órdenes Recibidas / En Cartera)
    purchases = PurchaseOrder.objects.filter(
        organization=organization,
        status__in=[PurchaseOrder.Status.RECEIVED, PurchaseOrder.Status.PARTIAL_PAID, PurchaseOrder.Status.PAID],
    ).exclude(journal_entries__isnull=False)

    for po in purchases:
        entry = JournalEntry.objects.create(
            organization=organization,
            date=po.issue_date or timezone.now().date(),
            entry_type=JournalEntry.EntryType.PURCHASES,
            concept=f"Compra Recibida {po.number} - {po.supplier.commercial_name if po.supplier else 'Proveedor'}",
            reference=po.number,
            source_purchase_order=po,
            created_by=user,
        )

        # DEBE: Compras / Inventarios (Subtotal)
        JournalEntryLine.objects.create(
            organization=organization,
            entry=entry,
            account=accounts['5101-01'],
            concept=f"Inventario/Gasto OC {po.number}",
            debit=po.subtotal,
            credit=Decimal('0.00'),
        )

        # DEBE: IVA Crédito Fiscal Acreditable (si aplica)
        if po.tax_total > Decimal('0.00'):
            JournalEntryLine.objects.create(
                organization=organization,
                entry=entry,
                account=accounts['1104-01'],
                concept=f"IVA Crédito Fiscal 15% OC {po.number}",
                debit=po.tax_total,
                credit=Decimal('0.00'),
            )

        # HABER: Retención IR DGI por pagar (si aplica)
        if po.ir_withheld_amount > Decimal('0.00'):
            JournalEntryLine.objects.create(
                organization=organization,
                entry=entry,
                account=accounts['2103-01'],
                concept=f"Retención IR DGI {po.withholding_certificate_number or po.number}",
                debit=Decimal('0.00'),
                credit=po.ir_withheld_amount,
            )

        # HABER: Retención IMI Alcaldía por pagar (si aplica)
        if po.imi_withheld_amount > Decimal('0.00'):
            JournalEntryLine.objects.create(
                organization=organization,
                entry=entry,
                account=accounts['2103-02'],
                concept=f"Retención IMI Alcaldía {po.withholding_certificate_number or po.number}",
                debit=Decimal('0.00'),
                credit=po.imi_withheld_amount,
            )

        # HABER: Proveedores Nacionales CxP (Neto a Pagar)
        JournalEntryLine.objects.create(
            organization=organization,
            entry=entry,
            account=accounts['2101-01'],
            concept=f"CxP Proveedor Fact. {po.supplier_invoice_number or po.number}",
            debit=Decimal('0.00'),
            credit=po.net_payable,
        )

        entry.verify_and_save_balance()
        synced_purchases += 1

    return {
        'invoices_synced': synced_invoices,
        'purchases_synced': synced_purchases,
        'total_entries': synced_invoices + synced_purchases,
    }

