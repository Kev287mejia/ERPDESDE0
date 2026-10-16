import threading
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts_auth.models import User
from apps.billing.models import Invoice, InvoiceItem, PaymentReceipt
from apps.crm.models import Account
from apps.finance.forms import BankAccountForm
from apps.finance.models import (
    AccountingAccount,
    BankAccount,
    FinancialTransaction,
    JournalEntry,
    JournalEntryLine,
)
from apps.finance.services import (
    ensure_default_chart_of_accounts,
    record_client_collection,
    record_invoice_sales_journal_entry,
    sync_commercial_and_purchasing_to_ledger,
)
from apps.finance.services_statements import FinancialStatementsService
from apps.core.models import CountryConfig
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel


class FinancialIntegrityPhase1B1TestCase(TestCase):
    """
    Suite de Pruebas de Integración End-to-End para Fase 1B.1 (Ventas y Cobros Bancarios).
    Verifica que:
    1. Formulario y vista rechazan o ignoran saldos iniciales arbitrarios inyectados en POST.
    2. Factura a crédito genera la póliza de ventas esperada exactamente una vez.
    3. Cobro por transferencia aumenta el saldo de la cuenta exactamente por el importe cobrado.
    4. Se crea FinancialTransaction y póliza de cobranza cuadrada (COLLECTIONS).
    5. Cuentas por cobrar (1103-01) disminuyen por el cobro y quedan en 0 tras liquidación total.
    6. Cuentas bancarias de otras organizaciones no pueden usarse para registrar cobros.
    7. La repetición de petición o sincronización no duplica movimientos ni asientos.
    8. Fallo a mitad de operación revierte atómicamente todos los cambios.
    9. Pagos parciales reducen CxC únicamente por el importe efectivamente cobrado.
    10. Facturas y cobros en USD se convierten a Córdobas (NIO) a la tasa oficial BCN.
    """

    def setUp(self):
        # 1. Configuración de Jurisdicción Fiscal Nicaragua
        self.country_ni, _ = CountryConfig.objects.get_or_create(
            code='NI',
            defaults={
                'name': 'Nicaragua',
                'flag_emoji': '🇳🇮',
                'primary_currency_code': 'NIO',
                'primary_currency_symbol': 'C$',
                'secondary_currency_code': 'USD',
                'secondary_currency_symbol': '$',
                'tax_id_label': 'RUC',
                'tax_id_regex': r'^[A-Z]\d{13}$',
                'personal_id_label': 'Cédula de Identidad',
                'personal_id_regex': r'^\d{3}-\d{6}-\d{4}[A-Z]$',
                'default_tax_name': 'IVA',
                'default_tax_rate': Decimal('15.00'),
                'is_active': True,
            }
        )

        # 2. Organización Principal
        self.org = Organization.objects.create(
            name="SERMANSA Electromecánica S.A.",
            legal_name="Servicios y Mantenimiento Electromecánico S.A.",
            slug="sermansa-phase1b1",
            tax_id="J0310000311223",
            country=self.country_ni,
            enabled_modules=['crm', 'operations', 'sst', 'inventory', 'finance', 'billing'],
            is_active=True,
        )

        # 3. Organización Intruso (Multi-Tenant Isolation)
        self.org_intruder = Organization.objects.create(
            name="Empresa Intruso Corp.",
            legal_name="Intruso de Nicaragua S.A.",
            slug="intruso-phase1b1",
            tax_id="J0310000999999",
            country=self.country_ni,
            enabled_modules=['finance', 'billing'],
            is_active=True,
        )

        # 4. Catálogo Contable Inicial
        ensure_default_chart_of_accounts(self.org)
        ensure_default_chart_of_accounts(self.org_intruder)

        # 5. Usuarios
        self.user_owner = User.objects.create_user(
            email='owner.1b1@sermansa.com.ni',
            full_name='Ing. Roberto Meza (Owner)',
            password='Password123!',
        )
        OrganizationMembership.objects.create(
            user=self.user_owner,
            organization=self.org,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
        )

        self.user_intruder = User.objects.create_user(
            email='intruder@intruso.com.ni',
            full_name='Usuario Intruso',
            password='Password123!',
        )
        OrganizationMembership.objects.create(
            user=self.user_intruder,
            organization=self.org_intruder,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
        )

        # 6. Cliente CRM
        self.client_account = Account.objects.create(
            organization=self.org,
            commercial_name="Ingenio San Antonio",
            legal_name="Nicaragua Sugar Estates Limited",
            tax_id="J0310000000001",
            default_currency='NIO',
        )

        # 7. Cliente HTTP autenticado
        self.client = Client()
        self.client.force_login(self.user_owner)
        session = self.client.session
        session['active_org_id'] = str(self.org.id)
        session.save()

    def test_01_bank_account_form_and_view_ignore_or_reject_injected_initial_balance(self):
        """El formulario y la vista ignoran cualquier saldo inicial inyectado en POST y crean la cuenta con saldo 0.00."""
        # 1. Prueba directa del formulario: se envía current_balance inyectado
        form_data = {
            'bank_name': BankAccount.BankName.BAC,
            'account_number': '100-999999-01',
            'currency': 'NIO',
            'account_type': BankAccount.AccountType.CHECKING,
            'current_balance': '500000.00',  # Inyección maliciosa
            'description': 'Cuenta Operativa BAC',
            'is_active': True,
        }
        form = BankAccountForm(form_data)
        self.assertTrue(form.is_valid(), f"Errores de validación: {form.errors}")
        bank = form.save(commit=False)
        bank.organization = self.org
        bank.save()
        # El saldo en libros debe permanecer en 0.00 (el modelo lo inicializa en 0.00 y el form lo ignora)
        self.assertEqual(bank.current_balance, Decimal('0.00'))

        # 2. Prueba vía petición POST a BankAccountCreateView
        url = reverse('finance:bank_account_create')
        res = self.client.post(url, {
            'bank_name': BankAccount.BankName.BANPRO,
            'account_number': '100-888888-02',
            'currency': 'NIO',
            'account_type': BankAccount.AccountType.CHECKING,
            'current_balance': '750000.00',  # Inyección maliciosa
            'description': 'Cuenta Banpro',
            'is_active': 'on',
        })
        self.assertEqual(res.status_code, 302)
        created_bank = BankAccount.objects.get(organization=self.org, account_number='100-888888-02')
        self.assertEqual(created_bank.current_balance, Decimal('0.00'))

    def test_02_credit_invoice_generates_sales_journal_entry_exactly_once(self):
        """Una factura emitida a crédito genera la póliza de ventas esperada exactamente una vez."""
        inv = Invoice.objects.create(
            organization=self.org,
            account=self.client_account,
            currency_code='NIO',
            currency_symbol='C$',
            exchange_rate=Decimal('36.6243'),
            apply_tax=True,
            created_by=self.user_owner,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=inv,
            description="Mantenimiento de Turbinas Eléctricas",
            quantity=Decimal('1.00'),
            unit_price=Decimal('10000.00'),
            discount_percent=Decimal('0.00'),
        )
        inv.recalculate_totals()
        inv.status = Invoice.Status.ISSUED
        inv.save()

        # Generar póliza de venta
        entry1 = record_invoice_sales_journal_entry(self.org, inv, self.user_owner)
        self.assertIsNotNone(entry1)
        self.assertEqual(entry1.entry_type, JournalEntry.EntryType.SALES)
        self.assertTrue(entry1.is_balanced)
        self.assertEqual(entry1.total_debit, Decimal('11500.00'))  # 10,000 + 15% IVA = 11,500
        self.assertEqual(entry1.total_credit, Decimal('11500.00'))

        # Verificar líneas
        lines = list(entry1.lines.all())
        cxc_line = next(line for line in lines if line.account.code == '1103-01')
        ventas_line = next(line for line in lines if line.account.code == '4101-01')
        iva_line = next(line for line in lines if line.account.code == '2102-01')

        self.assertEqual(cxc_line.debit, Decimal('11500.00'))
        self.assertEqual(ventas_line.credit, Decimal('10000.00'))
        self.assertEqual(iva_line.credit, Decimal('1500.00'))

        # Reintentos y sincronizaciones repetidas: NO deben duplicar el asiento
        entry2 = record_invoice_sales_journal_entry(self.org, inv, self.user_owner)
        self.assertEqual(entry1.pk, entry2.pk)
        sync_commercial_and_purchasing_to_ledger(self.org, self.user_owner)

        sales_entries_count = inv.journal_entries.filter(entry_type=JournalEntry.EntryType.SALES).count()
        self.assertEqual(sales_entries_count, 1)

    def test_03_and_04_bank_collection_flow_and_financial_transaction(self):
        """Un cobro mediante transferencia aumenta el saldo del banco, crea FinancialTransaction y póliza cuadrada."""
        bank_bac = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BAC,
            account_number='001-2026-BAC',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )

        inv = Invoice.objects.create(
            organization=self.org,
            account=self.client_account,
            currency_code='NIO',
            created_by=self.user_owner,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=inv,
            description="Rebobinado de Motores Trifásicos",
            quantity=Decimal('1.00'),
            unit_price=Decimal('20000.00'),
            discount_percent=Decimal('0.00'),
        )
        inv.recalculate_totals()
        inv.status = Invoice.Status.ISSUED
        inv.save()

        # Registrar cobro completo vía servicio atómico
        receipt, trx, collection_entry = record_client_collection(
            organization=self.org,
            invoice=inv,
            amount=Decimal('23000.00'),  # 20,000 + 15% IVA
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
            user=self.user_owner,
            bank_account=bank_bac,
            reference_number='TRF-BAC-998811',
            notes="Cobro total de factura",
        )

        # 3. Saldo bancario incrementado exactamente
        bank_bac.refresh_from_db()
        self.assertEqual(bank_bac.current_balance, Decimal('23000.00'))

        # 4. FinancialTransaction y Póliza de Cobranza (COLLECTIONS)
        self.assertIsNotNone(trx)
        self.assertEqual(trx.transaction_type, FinancialTransaction.TransactionType.CLIENT_COLLECTION)
        self.assertEqual(trx.amount, Decimal('23000.00'))
        self.assertEqual(trx.balance_after, Decimal('23000.00'))
        self.assertEqual(trx.bank_account, bank_bac)

        self.assertIsNotNone(collection_entry)
        self.assertEqual(collection_entry.entry_type, JournalEntry.EntryType.COLLECTIONS)
        self.assertTrue(collection_entry.is_balanced)
        self.assertEqual(collection_entry.total_debit, Decimal('23000.00'))
        self.assertEqual(collection_entry.total_credit, Decimal('23000.00'))
        self.assertEqual(collection_entry.source_payment_receipt, receipt)

        # Partida doble de cobranza: Debe Bancos (1102-01) y Haber Clientes (1103-01)
        col_lines = list(collection_entry.lines.all())
        bank_line = next(line for line in col_lines if line.account.code == '1102-01')
        cxc_line = next(line for line in col_lines if line.account.code == '1103-01')
        self.assertEqual(bank_line.debit, Decimal('23000.00'))
        self.assertEqual(cxc_line.credit, Decimal('23000.00'))

    def test_05_accounts_receivable_decreases_and_reaches_zero_in_balance_sheet(self):
        """La cuenta por cobrar disminuye por el cobro y queda en cero tras la liquidación completa en el Balance General."""
        bank_banpro = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BANPRO,
            account_number='002-2026-BANPRO',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )

        inv = Invoice.objects.create(
            organization=self.org,
            account=self.client_account,
            currency_code='NIO',
            created_by=self.user_owner,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=inv,
            description="Consultoría de Eficiencia Energética",
            quantity=Decimal('1.00'),
            unit_price=Decimal('5000.00'),
            discount_percent=Decimal('0.00'),
        )
        inv.recalculate_totals()
        inv.status = Invoice.Status.ISSUED
        inv.save()

        # Emitir póliza de venta
        record_invoice_sales_journal_entry(self.org, inv, self.user_owner)

        # Antes del cobro: la cuenta 1103-01 en el Balance General debe reflejar C$ 5,750.00 (5,000 + IVA)
        balance_before = FinancialStatementsService.get_balance_sheet(self.org)
        ar_item_before = next(item for item in balance_before['receivables'] if item['code'] == '1103-01')
        self.assertEqual(ar_item_before['balance'], Decimal('5750.00'))

        # Cobro completo
        record_client_collection(
            organization=self.org,
            invoice=inv,
            amount=Decimal('5750.00'),
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BANPRO,
            user=self.user_owner,
            bank_account=bank_banpro,
            reference_number='TRF-BANPRO-332211',
        )

        # Después del cobro: en el Balance General y Balanza de Comprobación, CxC debe quedar en 0.00
        balance_after = FinancialStatementsService.get_balance_sheet(self.org)
        # receivables no debe incluir 1103-01 porque su balance neto es 0.00 (filtrado por balance == 0)
        ar_items_after = [item for item in balance_after['receivables'] if item['code'] == '1103-01']
        self.assertEqual(len(ar_items_after), 0)

        # Verificar en Balanza de Comprobación
        trial = FinancialStatementsService.get_trial_balance(self.org)
        self.assertTrue(trial['is_balanced'])
        cxc_trial = next(acc for acc in trial['accounts'] if acc['code'] == '1103-01')
        self.assertEqual(cxc_trial['debit_balance'], Decimal('0.00'))
        self.assertEqual(cxc_trial['credit_balance'], Decimal('0.00'))

        # Bancos (1102-01) debe tener saldo deudor de C$ 5,750.00
        bank_trial = next(acc for acc in trial['accounts'] if acc['code'] == '1102-01')
        self.assertEqual(bank_trial['debit_balance'], Decimal('5750.00'))

    def test_06_bank_account_from_different_organization_rejected(self):
        """Una cuenta bancaria de otra organización no puede utilizarse para registrar el cobro."""
        bank_intruder = BankAccount.objects.create(
            organization=self.org_intruder,
            bank_name=BankAccount.BankName.LAFISE,
            account_number='999-INTRUDER-01',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )

        inv = Invoice.objects.create(
            organization=self.org,
            account=self.client_account,
            currency_code='NIO',
            created_by=self.user_owner,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=inv,
            description="Servicio Local",
            quantity=Decimal('1.00'),
            unit_price=Decimal('1000.00'),
        )
        inv.recalculate_totals()
        inv.status = Invoice.Status.ISSUED
        inv.save()

        # Intentar cobro con cuenta bancaria del intruso: debe fallar con ValidationError
        with self.assertRaises(ValidationError) as ctx:
            record_client_collection(
                organization=self.org,
                invoice=inv,
                amount=Decimal('1150.00'),
                payment_method=PaymentReceipt.PaymentMethod.TRANSFER_LAFISE,
                user=self.user_owner,
                bank_account=bank_intruder,
            )
        self.assertIn("La cuenta bancaria no pertenece a la organización", str(ctx.exception))

        # Probar vía vista HTTP
        url = reverse('billing:register_payment', args=[str(inv.pk)])
        res = self.client.post(url, {
            'amount': '1150.00',
            'payment_method': PaymentReceipt.PaymentMethod.TRANSFER_LAFISE,
            'bank_account_id': str(bank_intruder.pk),
        })
        self.assertEqual(res.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.balance_due, Decimal('1150.00'))
        self.assertEqual(inv.payments.count(), 0)

    def test_07_repeat_request_or_sync_does_not_duplicate_movements_or_entries(self):
        """La repetición de una petición o sincronización no duplica movimientos ni asientos."""
        bank = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BAC,
            account_number='003-IDEMPOTENT',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )
        inv = Invoice.objects.create(
            organization=self.org,
            account=self.client_account,
            currency_code='NIO',
            created_by=self.user_owner,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=inv,
            description="Item Idempotente",
            quantity=Decimal('1.00'),
            unit_price=Decimal('3000.00'),
        )
        inv.recalculate_totals()
        inv.status = Invoice.Status.ISSUED
        inv.save()

        # Primer cobro
        record_client_collection(
            organization=self.org,
            invoice=inv,
            amount=Decimal('3450.00'),
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
            user=self.user_owner,
            bank_account=bank,
            reference_number='REF-IDEM-001',
        )

        # Repetición idéntica con misma referencia: debe ser rechazada
        with self.assertRaises(ValidationError) as ctx:
            record_client_collection(
                organization=self.org,
                invoice=inv,
                amount=Decimal('3450.00'),
                payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
                user=self.user_owner,
                bank_account=bank,
                reference_number='REF-IDEM-001',
            )
        self.assertTrue(
            "Ya existe un cobro registrado con la referencia" in str(ctx.exception)
            or "No se pueden registrar cobros en una factura con estado" in str(ctx.exception)
        )

        # Verificar que solo exista 1 recibo, 1 transacción y 1 póliza de cobranza
        self.assertEqual(PaymentReceipt.objects.filter(invoice=inv).count(), 1)
        self.assertEqual(FinancialTransaction.objects.filter(bank_account=bank).count(), 1)
        self.assertEqual(JournalEntry.objects.filter(source_invoice=inv, entry_type=JournalEntry.EntryType.COLLECTIONS).count(), 1)

    def test_08_failure_mid_operation_rolls_back_all_related_changes(self):
        """Un fallo a mitad de la operación revierte todos los cambios relacionados (atomicidad)."""
        bank = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BAC,
            account_number='004-ROLLBACK',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )
        inv = Invoice.objects.create(
            organization=self.org,
            account=self.client_account,
            currency_code='NIO',
            created_by=self.user_owner,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=inv,
            description="Item Rollback",
            quantity=Decimal('1.00'),
            unit_price=Decimal('2000.00'),
        )
        inv.recalculate_totals()
        inv.status = Invoice.Status.ISSUED
        inv.save()

        # Forzar cobro con monto que excede el saldo pendiente
        with self.assertRaises(ValidationError):
            record_client_collection(
                organization=self.org,
                invoice=inv,
                amount=Decimal('5000.00'),  # Excede los 2,300 de saldo
                payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
                user=self.user_owner,
                bank_account=bank,
            )

        # Estado intacto
        inv.refresh_from_db()
        bank.refresh_from_db()
        self.assertEqual(inv.balance_due, Decimal('2300.00'))
        self.assertEqual(inv.amount_paid, Decimal('0.00'))
        self.assertEqual(bank.current_balance, Decimal('0.00'))
        self.assertEqual(PaymentReceipt.objects.filter(invoice=inv).count(), 0)
        self.assertEqual(FinancialTransaction.objects.filter(bank_account=bank).count(), 0)
        self.assertEqual(JournalEntry.objects.filter(source_invoice=inv, entry_type=JournalEntry.EntryType.COLLECTIONS).count(), 0)

    def test_09_partial_payments_reduce_cxc_proportionately(self):
        """Los pagos parciales reducen la cuenta por cobrar únicamente por el importe efectivamente cobrado."""
        bank = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BAC,
            account_number='005-PARTIAL',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )
        inv = Invoice.objects.create(
            organization=self.org,
            account=self.client_account,
            currency_code='NIO',
            created_by=self.user_owner,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=inv,
            description="Instalación en Planta",
            quantity=Decimal('1.00'),
            unit_price=Decimal('10000.00'),
        )
        inv.recalculate_totals()
        inv.status = Invoice.Status.ISSUED
        inv.save()  # Total 11,500.00

        # Abono 1: C$ 4,000.00
        record_client_collection(
            organization=self.org,
            invoice=inv,
            amount=Decimal('4000.00'),
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
            user=self.user_owner,
            bank_account=bank,
            reference_number='ABONO-1',
        )
        inv.refresh_from_db()
        bank.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PARTIAL)
        self.assertEqual(inv.amount_paid, Decimal('4000.00'))
        self.assertEqual(inv.balance_due, Decimal('7500.00'))
        self.assertEqual(bank.current_balance, Decimal('4000.00'))

        # Balance general después del abono 1: CxC debe reportar C$ 7,500.00
        bal1 = FinancialStatementsService.get_balance_sheet(self.org)
        cxc_bal1 = next(item for item in bal1['receivables'] if item['code'] == '1103-01')
        self.assertEqual(cxc_bal1['balance'], Decimal('7500.00'))

        # Abono 2: Liquidación final por C$ 7,500.00
        record_client_collection(
            organization=self.org,
            invoice=inv,
            amount=Decimal('7500.00'),
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
            user=self.user_owner,
            bank_account=bank,
            reference_number='ABONO-2',
        )
        inv.refresh_from_db()
        bank.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PAID)
        self.assertEqual(inv.balance_due, Decimal('0.00'))
        self.assertEqual(bank.current_balance, Decimal('11500.00'))

        # Balance general final: CxC en cero
        bal2 = FinancialStatementsService.get_balance_sheet(self.org)
        cxc_bal2 = [item for item in bal2['receivables'] if item['code'] == '1103-01']
        self.assertEqual(len(cxc_bal2), 0)

    def test_10_usd_invoice_and_collection_conversion_to_functional_currency(self):
        """Facturas y cobros en USD se convierten a Córdobas (NIO) a la tasa oficial BCN en el Libro Diario."""
        bank_nio = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BAC,
            account_number='006-USD-NIO-BRIDGE',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )
        bcn_rate = Decimal('36.6243')
        inv_usd = Invoice.objects.create(
            organization=self.org,
            account=self.client_account,
            currency_code='USD',
            currency_symbol='$',
            exchange_rate=bcn_rate,
            apply_tax=True,
            created_by=self.user_owner,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=inv_usd,
            description="Licencias de Software de Monitoreo",
            quantity=Decimal('1.00'),
            unit_price=Decimal('1000.00'),
        )
        inv_usd.recalculate_totals()
        inv_usd.status = Invoice.Status.ISSUED
        inv_usd.save()  # Total USD: 1,150.00 ($1,000 + 15% IVA)

        # Generar póliza de venta en Córdobas (NIO)
        sales_entry = record_invoice_sales_journal_entry(self.org, inv_usd, self.user_owner)
        from decimal import ROUND_HALF_UP
        expected_nio = (Decimal('1150.00') * bcn_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.assertEqual(sales_entry.total_debit, expected_nio)
        self.assertEqual(sales_entry.total_credit, expected_nio)

        # Cobro en cuenta bancaria NIO por $ 1,150.00 USD
        receipt, trx, col_entry = record_client_collection(
            organization=self.org,
            invoice=inv_usd,
            amount=Decimal('1150.00'),
            currency_paid='USD',
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
            user=self.user_owner,
            bank_account=bank_nio,
            reference_number='TRF-USD-001',
        )

        bank_nio.refresh_from_db()
        self.assertEqual(bank_nio.current_balance, expected_nio)
        self.assertEqual(trx.amount, expected_nio)
        self.assertEqual(col_entry.total_debit, expected_nio)
        self.assertEqual(col_entry.total_credit, expected_nio)

        # Balanza de Comprobación cuadrada
        trial = FinancialStatementsService.get_trial_balance(self.org)
        self.assertTrue(trial['is_balanced'])

    def test_12_sales_journal_entry_database_uniqueness(self):
        """Garantía de base de datos contra duplicidad de pólizas SALES para una misma factura."""
        from django.db import IntegrityError
        inv = Invoice.objects.create(
            organization=self.org,
            account=self.client_account,
            currency_code='NIO',
            created_by=self.user_owner,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=inv,
            description="Servicio Único",
            quantity=Decimal('1.00'),
            unit_price=Decimal('1000.00'),
        )
        inv.recalculate_totals()
        inv.status = Invoice.Status.ISSUED
        inv.save()

        # Primera creación legítima
        entry1 = record_invoice_sales_journal_entry(self.org, inv, self.user_owner)
        self.assertIsNotNone(entry1)

        # Reintento mediante servicio retorna exactamente la misma póliza
        entry2 = record_invoice_sales_journal_entry(self.org, inv, self.user_owner)
        self.assertEqual(entry1.pk, entry2.pk)
        self.assertEqual(JournalEntry.objects.filter(organization=self.org, source_invoice=inv, entry_type=JournalEntry.EntryType.SALES).count(), 1)

        # Intento directo en base de datos de violar el constraint único debe disparar IntegrityError
        with self.assertRaises(IntegrityError):
            JournalEntry.objects.create(
                organization=self.org,
                entry_type=JournalEntry.EntryType.SALES,
                concept="Intento Fraudulento de Segunda Póliza de Venta",
                source_invoice=inv,
                created_by=self.user_owner,
            )

    def test_13_collections_journal_entry_database_uniqueness(self):
        """Garantía de base de datos contra duplicidad de pólizas COLLECTIONS para un mismo recibo."""
        from django.db import IntegrityError
        bank = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BAC,
            account_number='099-UNIQUE-COL',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )
        inv = Invoice.objects.create(
            organization=self.org,
            account=self.client_account,
            currency_code='NIO',
            created_by=self.user_owner,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=inv,
            description="Item para Cobro Único",
            quantity=Decimal('1.00'),
            unit_price=Decimal('500.00'),
        )
        inv.recalculate_totals()
        inv.status = Invoice.Status.ISSUED
        inv.save()

        receipt, trx, entry1 = record_client_collection(
            organization=self.org,
            invoice=inv,
            amount=Decimal('575.00'),
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
            user=self.user_owner,
            bank_account=bank,
            reference_number='TRF-COL-UNIQUE-01',
        )
        self.assertEqual(JournalEntry.objects.filter(organization=self.org, source_payment_receipt=receipt, entry_type=JournalEntry.EntryType.COLLECTIONS).count(), 1)

        # Intento directo de crear una segunda póliza de cobranza para el mismo recibo debe fallar en BD
        with self.assertRaises(IntegrityError):
            JournalEntry.objects.create(
                organization=self.org,
                entry_type=JournalEntry.EntryType.COLLECTIONS,
                concept="Intento de Duplicar Cobranza en BD",
                source_payment_receipt=receipt,
                created_by=self.user_owner,
            )

    def test_14_bank_reference_duplicate_on_other_invoice_rejected(self):
        """Una misma referencia bancaria no puede usarse para justificar cobros en facturas distintas en la misma cuenta."""
        bank = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BAC,
            account_number='010-REF-TEST',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )
        inv1 = Invoice.objects.create(
            organization=self.org,
            account=self.client_account,
            currency_code='NIO',
            created_by=self.user_owner,
        )
        InvoiceItem.objects.create(organization=self.org, invoice=inv1, description="Factura 1", quantity=Decimal('1.00'), unit_price=Decimal('100.00'))
        inv1.recalculate_totals()
        inv1.status = Invoice.Status.ISSUED
        inv1.save()

        inv2 = Invoice.objects.create(
            organization=self.org,
            account=self.client_account,
            currency_code='NIO',
            created_by=self.user_owner,
        )
        InvoiceItem.objects.create(organization=self.org, invoice=inv2, description="Factura 2", quantity=Decimal('1.00'), unit_price=Decimal('100.00'))
        inv2.recalculate_totals()
        inv2.status = Invoice.Status.ISSUED
        inv2.save()

        # Cobro legítimo de Factura 1
        record_client_collection(
            organization=self.org,
            invoice=inv1,
            amount=Decimal('115.00'),
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
            user=self.user_owner,
            bank_account=bank,
            reference_number='TRF-BAC-SHARED-001',
        )

        # Intento de reusar la misma referencia en Factura 2 debe ser rechazado
        with self.assertRaises(ValidationError) as ctx:
            record_client_collection(
                organization=self.org,
                invoice=inv2,
                amount=Decimal('115.00'),
                payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
                user=self.user_owner,
                bank_account=bank,
                reference_number='TRF-BAC-SHARED-001',
            )
        self.assertIn("ya fue utilizada en esta cuenta bancaria", str(ctx.exception))

    def test_15_bank_reference_same_in_different_bank_accounts_allowed(self):
        """Referencias iguales en cuentas bancarias distintas son admitidas si pertenecen a bancos diferentes."""
        bank_bac = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BAC,
            account_number='BAC-001',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )
        bank_banpro = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BANPRO,
            account_number='BANPRO-002',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )
        inv1 = Invoice.objects.create(organization=self.org, account=self.client_account, currency_code='NIO', created_by=self.user_owner)
        InvoiceItem.objects.create(organization=self.org, invoice=inv1, description="Item 1", quantity=Decimal('1.00'), unit_price=Decimal('100.00'))
        inv1.recalculate_totals()
        inv1.status = Invoice.Status.ISSUED
        inv1.save()

        inv2 = Invoice.objects.create(organization=self.org, account=self.client_account, currency_code='NIO', created_by=self.user_owner)
        InvoiceItem.objects.create(organization=self.org, invoice=inv2, description="Item 2", quantity=Decimal('1.00'), unit_price=Decimal('100.00'))
        inv2.recalculate_totals()
        inv2.status = Invoice.Status.ISSUED
        inv2.save()

        # Mismo número de referencia externa pero en dos cuentas bancarias distintas
        r1, _, _ = record_client_collection(
            organization=self.org,
            invoice=inv1,
            amount=Decimal('115.00'),
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
            user=self.user_owner,
            bank_account=bank_bac,
            reference_number='REF-NUMERICO-100',
        )
        r2, _, _ = record_client_collection(
            organization=self.org,
            invoice=inv2,
            amount=Decimal('115.00'),
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BANPRO,
            user=self.user_owner,
            bank_account=bank_banpro,
            reference_number='REF-NUMERICO-100',
        )
        self.assertIsNotNone(r1)
        self.assertIsNotNone(r2)
        bank_bac.refresh_from_db()
        bank_banpro.refresh_from_db()
        self.assertEqual(bank_bac.current_balance, Decimal('115.00'))
        self.assertEqual(bank_banpro.current_balance, Decimal('115.00'))

    def test_16_cash_payment_without_reference_allowed_repeatedly(self):
        """Pagos legítimos en efectivo sin referencia externa son permitidos repetidamente."""
        inv = Invoice.objects.create(organization=self.org, account=self.client_account, currency_code='NIO', created_by=self.user_owner)
        InvoiceItem.objects.create(organization=self.org, invoice=inv, description="Venta en Efectivo", quantity=Decimal('1.00'), unit_price=Decimal('200.00'))
        inv.recalculate_totals()
        inv.status = Invoice.Status.ISSUED
        inv.save()  # Total 230.00

        # Primer abono en efectivo sin referencia
        r1, _, _ = record_client_collection(
            organization=self.org,
            invoice=inv,
            amount=Decimal('100.00'),
            payment_method=PaymentReceipt.PaymentMethod.CASH,
            user=self.user_owner,
            bank_account=None,
            reference_number='',
        )
        # Segundo abono en efectivo sin referencia
        r2, _, _ = record_client_collection(
            organization=self.org,
            invoice=inv,
            amount=Decimal('130.00'),
            payment_method=PaymentReceipt.PaymentMethod.CASH,
            user=self.user_owner,
            bank_account=None,
            reference_number='',
        )
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PAID)
        self.assertEqual(inv.balance_due, Decimal('0.00'))
        self.assertEqual(inv.payments.count(), 2)

    def test_17_idempotency_key_replays_same_receipt_without_duplication(self):
        """Una clave de idempotencia repite exactamente el mismo resultado sin duplicar recibo, movimiento ni asiento."""
        bank = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BAC,
            account_number='020-IDEMPOTENT',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )
        inv = Invoice.objects.create(organization=self.org, account=self.client_account, currency_code='NIO', created_by=self.user_owner)
        InvoiceItem.objects.create(organization=self.org, invoice=inv, description="Cobro con Idempotencia", quantity=Decimal('1.00'), unit_price=Decimal('1000.00'))
        inv.recalculate_totals()
        inv.status = Invoice.Status.ISSUED
        inv.save()

        # Primer intento con idempotency_key
        key = 'IDEM-KEY-UUID-9999'
        r1, t1, e1 = record_client_collection(
            organization=self.org,
            invoice=inv,
            amount=Decimal('500.00'),
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
            user=self.user_owner,
            bank_account=bank,
            reference_number='TRF-IDEM-01',
            idempotency_key=key,
        )

        bank.refresh_from_db()
        inv.refresh_from_db()
        self.assertEqual(bank.current_balance, Decimal('500.00'))
        self.assertEqual(inv.balance_due, Decimal('650.00'))
        self.assertEqual(inv.payments.count(), 1)
        self.assertEqual(JournalEntry.objects.filter(source_payment_receipt=r1).count(), 1)

        # Reintento idéntico de la misma petición con la misma idempotency_key
        r2, t2, e2 = record_client_collection(
            organization=self.org,
            invoice=inv,
            amount=Decimal('500.00'),
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
            user=self.user_owner,
            bank_account=bank,
            reference_number='TRF-IDEM-01',
            idempotency_key=key,
        )

        bank.refresh_from_db()
        inv.refresh_from_db()
        # El saldo no cambia, el recibo retornado es exactamente el mismo y no hay duplicados
        self.assertEqual(r1.pk, r2.pk)
        self.assertEqual(bank.current_balance, Decimal('500.00'))
        self.assertEqual(inv.balance_due, Decimal('650.00'))
        self.assertEqual(inv.payments.count(), 1)
        self.assertEqual(JournalEntry.objects.filter(source_payment_receipt=r1).count(), 1)

    def test_18_idempotency_key_mismatched_payload_rejected(self):
        """Reutilizar una clave de idempotencia con parámetros distintos es rechazado con ValidationError."""
        bank = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BAC,
            account_number='021-IDEM-TAMPER',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )
        inv = Invoice.objects.create(organization=self.org, account=self.client_account, currency_code='NIO', created_by=self.user_owner)
        InvoiceItem.objects.create(organization=self.org, invoice=inv, description="Cobro", quantity=Decimal('1.00'), unit_price=Decimal('500.00'))
        inv.recalculate_totals()
        inv.status = Invoice.Status.ISSUED
        inv.save()

        key = 'IDEM-KEY-TAMPER-TEST'
        record_client_collection(
            organization=self.org,
            invoice=inv,
            amount=Decimal('200.00'),
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
            user=self.user_owner,
            bank_account=bank,
            reference_number='TRF-IDEM-TAMPER',
            idempotency_key=key,
        )

        # Mismo key pero enviando monto 300.00
        with self.assertRaises(ValidationError) as ctx:
            record_client_collection(
                organization=self.org,
                invoice=inv,
                amount=Decimal('300.00'),
                payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
                user=self.user_owner,
                bank_account=bank,
                reference_number='TRF-IDEM-TAMPER',
                idempotency_key=key,
            )
        self.assertIn("La clave de idempotencia especificada ya fue utilizada con parámetros de solicitud diferentes", str(ctx.exception))

    def test_19_admin_cannot_create_or_delete_payment_receipts(self):
        """Verifica que la consola administrativa de Django impida add, delete y change directo en PaymentReceipt."""
        from django.contrib.admin.sites import AdminSite
        from apps.billing.admin import PaymentReceiptAdmin, PaymentReceiptInline
        from apps.billing.models import PaymentReceipt

        site = AdminSite()
        admin_obj = PaymentReceiptAdmin(PaymentReceipt, site)
        inline_obj = PaymentReceiptInline(PaymentReceipt, site)

        from unittest.mock import Mock
        mock_req = Mock()

        # En PaymentReceiptAdmin
        self.assertFalse(admin_obj.has_add_permission(mock_req))
        self.assertFalse(admin_obj.has_delete_permission(mock_req))
        self.assertFalse(admin_obj.has_change_permission(mock_req))

        # En PaymentReceiptInline
        self.assertFalse(inline_obj.has_add_permission(mock_req))
        self.assertFalse(inline_obj.has_delete_permission(mock_req))
        self.assertFalse(inline_obj.has_change_permission(mock_req))


class FinancialConcurrencyPhase1B1TestCase(TransactionTestCase):
    """
    Prueba de Concurrencia Real para Cobros Simultáneos.
    Verifica que dos hilos concurrentes no puedan sobreliquidar una factura
    gracias al bloqueo pesimista select_for_update() y comprobación atómica.
    """

    def setUp(self):
        self.country_ni, _ = CountryConfig.objects.get_or_create(
            code='NI',
            defaults={
                'name': 'Nicaragua',
                'flag_emoji': '🇳🇮',
                'primary_currency_code': 'NIO',
                'primary_currency_symbol': 'C$',
                'secondary_currency_code': 'USD',
                'secondary_currency_symbol': '$',
                'tax_id_label': 'RUC',
                'tax_id_regex': r'^[A-Z]\d{13}$',
                'default_tax_name': 'IVA',
                'default_tax_rate': Decimal('15.00'),
                'is_active': True,
            }
        )

        self.org = Organization.objects.create(
            name="SERMANSA Concurrencia S.A.",
            slug="sermansa-concurrency",
            tax_id="J0310000777777",
            country=self.country_ni,
            enabled_modules=['crm', 'finance', 'billing'],
            is_active=True,
        )
        ensure_default_chart_of_accounts(self.org)

        self.user = User.objects.create_user(
            email='cajero.concurrente@sermansa.com.ni',
            full_name='Cajero Concurrente',
            password='Password123!',
        )
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
        )

        self.bank = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BAC,
            account_number='009-CONCURRENCY',
            currency='NIO',
            current_balance=Decimal('0.00'),
            is_active=True,
        )

        self.client_acc = Account.objects.create(
            organization=self.org,
            commercial_name="Cliente Concurrente S.A.",
            tax_id="J0310000888888",
        )

        self.inv = Invoice.objects.create(
            organization=self.org,
            account=self.client_acc,
            currency_code='NIO',
            created_by=self.user,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=self.inv,
            description="Item para Concurrencia",
            quantity=Decimal('1.00'),
            unit_price=Decimal('10000.00'),
        )
        self.inv.recalculate_totals()
        self.inv.status = Invoice.Status.ISSUED
        self.inv.save()  # Saldo 11,500.00

    def test_11_concurrent_payments_cannot_double_settle_invoice(self):
        """Dos intentos concurrentes de cobro por el total: uno triunfa y el otro es rechazado por saldo excedente."""
        errors = []
        successes = []

        def worker(ref):
            # Cerrar conexión previa en el nuevo hilo para que abra su propia conexión independiente
            connection.close()
            try:
                receipt, trx, entry = record_client_collection(
                    organization=self.org,
                    invoice=self.inv,
                    amount=Decimal('11500.00'),
                    payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
                    user=self.user,
                    bank_account=self.bank,
                    reference_number=ref,
                )
                successes.append(receipt.pk)
            except (ValidationError, Exception) as e:
                errors.append(str(e))
            finally:
                connection.close()

        import time
        t1 = threading.Thread(target=worker, args=('REF-THREAD-1',))
        t2 = threading.Thread(target=worker, args=('REF-THREAD-2',))

        t1.start()
        time.sleep(0.02)
        t2.start()

        t1.join()
        t2.join()

        # Debe haber exactamente 1 cobro exitoso y 1 error capturado
        self.assertEqual(len(successes), 1, f"Éxitos: {len(successes)}, Errores: {errors}")
        self.assertEqual(len(errors), 1, f"Errores esperados: 1, encontrados: {len(errors)}")

        self.inv.refresh_from_db()
        self.bank.refresh_from_db()

        # Factura pagada exactamente una vez
        self.assertEqual(self.inv.status, Invoice.Status.PAID)
        self.assertEqual(self.inv.balance_due, Decimal('0.00'))
        self.assertEqual(self.inv.amount_paid, Decimal('11500.00'))
        self.assertEqual(self.bank.current_balance, Decimal('11500.00'))

    def test_20_concurrent_requests_with_same_reference(self):
        """Dos hilos enviando la misma referencia bancaria: uno triunfa y el otro es rechazado por conflicto."""
        errors = []
        successes = []

        def worker():
            connection.close()
            try:
                receipt, trx, entry = record_client_collection(
                    organization=self.org,
                    invoice=self.inv,
                    amount=Decimal('5000.00'),
                    payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
                    user=self.user,
                    bank_account=self.bank,
                    reference_number='CONCURRENT-REF-SAME-01',
                )
                successes.append(receipt.pk)
            except (ValidationError, Exception) as e:
                errors.append(str(e))
            finally:
                connection.close()

        import time
        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)

        t1.start()
        time.sleep(0.02)
        t2.start()

        t1.join()
        t2.join()

        self.assertEqual(len(successes), 1, f"Éxitos: {len(successes)}, Errores: {errors}")
        self.assertEqual(len(errors), 1, f"Errores esperados: 1, encontrados: {len(errors)}")
