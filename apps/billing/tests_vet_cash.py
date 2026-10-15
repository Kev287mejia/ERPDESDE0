import datetime
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceItem, PaymentReceipt, CashRegisterSession
from apps.core.models import CountryConfig
from apps.crm.models import Account
from apps.finance.models import JournalEntry, AccountingAccount
from apps.finance.services import sync_commercial_and_purchasing_to_ledger, ensure_default_chart_of_accounts
from apps.inventory.models import InventoryItem, Warehouse
from apps.purchasing.models import PurchaseOrder, PurchaseOrderItem, Supplier
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel

User = get_user_model()


class VetCashBaseTestCase(TestCase):
    """
    Base de pruebas para Arqueo de Caja Z, VET-DGI y Sincronización Contable.
    Configura Organización multi-tenant, colaboradores en distintos RoleLevels y catálogo de cuentas.
    """
    def setUp(self):
        self.country_ni, _ = CountryConfig.objects.get_or_create(
            code='NI',
            defaults={
                'name': 'Nicaragua',
                'flag_emoji': 'NI',
                'primary_currency_code': 'NIO',
                'primary_currency_symbol': 'C$',
                'tax_id_label': 'RUC',
                'tax_id_regex': r'^[A-Z]\d{13}$',
                'is_active': True,
                'default_tax_rate': Decimal('15.00'),
                'default_tax_name': 'IVA',
            }
        )

        self.org = Organization.objects.create(
            name='SERVICIOS ELECTRO-INDUSTRIALES S.A.',
            legal_name='Servicios Electro-Industriales de Nicaragua S.A.',
            tax_id='J0310000778899',
            country=self.country_ni,
            currency=Organization.Currency.NIO,
            enabled_modules=['crm', 'operations', 'inventory', 'finance', 'billing', 'purchasing'],
        )

        # 1. Colaborador OWNER_ADMIN (100)
        self.user_owner = User.objects.create_user(
            email='owner@electro.ni',
            password='Password123!',
            full_name='Ing. Carlos Mántica',
        )
        self.mem_owner = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.user_owner,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
        )

        # 2. Colaborador COMMERCIAL_MGR (85)
        self.user_comm = User.objects.create_user(
            email='comercial@electro.ni',
            password='Password123!',
            full_name='Lic. Patricia Morales',
        )
        self.mem_comm = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.user_comm,
            role_level=RoleLevel.COMMERCIAL_MGR,
            is_active=True,
        )

        # 3. Colaborador OPERATIONS_COORD (80)
        self.user_coord = User.objects.create_user(
            email='coord@electro.ni',
            password='Password123!',
            full_name='Ing. Roberto Rivas',
        )
        self.mem_coord = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.user_coord,
            role_level=RoleLevel.OPERATIONS_COORD,
            is_active=True,
        )

        # 4. Colaborador TECHNICIAN / SST_OFFICER (70)
        self.user_sst = User.objects.create_user(
            email='sst@electro.ni',
            password='Password123!',
            full_name='Lic. Fernando Ortega',
        )
        self.mem_sst = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.user_sst,
            role_level=RoleLevel.SST_OFFICER,
            is_active=True,
        )

        # Cuentas Contables NIIF/DGI
        ensure_default_chart_of_accounts(self.org)

        # Bodega e Ítem de inventario
        self.warehouse = Warehouse.objects.create(
            organization=self.org,
            code='BOD-01',
            name='Bodega Central Managua',
        )
        self.item = InventoryItem.objects.create(
            organization=self.org,
            sku='MAT-CAB-01',
            name='Cable THHN 12 AWG',
            unit='MTS',
            unit_cost=Decimal('25.00'),
            price_retail=Decimal('35.00'),
        )

        # Cliente CRM
        self.account = Account.objects.create(
            organization=self.org,
            code='CLI-001',
            commercial_name='ENATREL Nicaragua',
            tax_id='J0310000000001',
        )

        # Proveedor Compras
        self.supplier = Supplier.objects.create(
            organization=self.org,
            code='PRV-001',
            commercial_name='SINSA Ferretería Industrial',
            tax_id='J0310000999999',
            default_ir_rate=Decimal('1.00'),
            default_imi_rate=Decimal('1.00'),
        )


class CashRegisterSessionLifecycleTests(VetCashBaseTestCase):
    """
    Pruebas del ciclo completo de vida del Arqueo de Caja Z Bimonetario (CashRegisterSession):
    Apertura -> Venta POS Efectivo -> Recálculo del Sistema -> Cierre Físico -> Diferencia -> Sello SHA-256 e Inmutabilidad.
    """
    def test_full_cash_session_lifecycle(self):
        # 1. Apertura de turno con C$ 5,000.00 y $ 100.00
        session = CashRegisterSession.objects.create(
            organization=self.org,
            cashier=self.user_comm,
            status=CashRegisterSession.Status.OPEN,
            opening_cash_nio=Decimal('5000.00'),
            opening_cash_usd=Decimal('100.00'),
            exchange_rate=Decimal('36.6243'),
            notes="Turno Matutino Caja Principal",
        )
        self.assertTrue(session.number.startswith('ARQ-'))
        self.assertEqual(session.status, CashRegisterSession.Status.OPEN)

        # 2. Venta en mostrador por C$ 1,150.00 cancelada al contado en efectivo
        invoice = Invoice.objects.create(
            organization=self.org,
            account=self.account,
            status=Invoice.Status.PAID,
            issue_date=timezone.now().date(),
            currency_code='NIO',
            currency_symbol='C$',
            subtotal=Decimal('1000.00'),
            tax_total=Decimal('150.00'),
            gross_total=Decimal('1150.00'),
            net_receivable=Decimal('1150.00'),
        )
        receipt = PaymentReceipt.objects.create(
            organization=self.org,
            invoice=invoice,
            payment_date=timezone.now().date(),
            payment_method=PaymentReceipt.PaymentMethod.CASH,
            currency_paid='NIO',
            amount_in_payment_currency=Decimal('1150.00'),
            exchange_rate_applied=Decimal('36.6243'),
            amount_applied_to_invoice=Decimal('1150.00'),
            received_by=self.user_comm,
        )

        # 3. Recálculo automático de totales del sistema
        session.recalculate_system_totals()
        self.assertEqual(session.system_cash_nio, Decimal('1150.00'))
        self.assertEqual(session.system_cash_usd, Decimal('0.00'))
        self.assertEqual(session.expected_cash_nio, Decimal('6150.00'))
        self.assertEqual(session.expected_cash_usd, Decimal('100.00'))

        # 4. Cierre con conteo físico declarado en gaveta: C$ 6,100.00 y $ 100.00 (Faltante exacto -50.00)
        session.close_and_seal_session(
            declared_nio=Decimal('6100.00'),
            declared_usd=Decimal('100.00'),
            notes="Cierre con faltante menor de 50 córdobas",
        )

        session.refresh_from_db()
        self.assertEqual(session.status, CashRegisterSession.Status.CLOSED)
        self.assertEqual(session.declared_cash_nio, Decimal('6100.00'))
        self.assertEqual(session.difference_nio, Decimal('-50.00'))
        self.assertEqual(session.difference_usd, Decimal('0.00'))
        self.assertTrue(len(session.audit_hash) == 64)  # SHA-256 hex digest válido

        # 5. Inmutabilidad estricta: intento de alteración posterior
        session.declared_cash_nio = Decimal('6150.00')
        with self.assertRaises(ValidationError):
            session.clean()

        with self.assertRaises(ValidationError):
            session.save()

        # 6. Inmutabilidad estricta: intento de eliminación
        session.refresh_from_db()
        with self.assertRaises(ValidationError):
            session.delete()

        # 7. Intento de reabrir o volver a cerrar sesión sellada
        with self.assertRaises(ValidationError):
            session.close_and_seal_session(Decimal('6000.00'), Decimal('100.00'))


class VETDGITaxCenterAndCSVTests(VetCashBaseTestCase):
    """
    Pruebas del Centro Tributario VET-DGI Nicaragua y Exportador Oficial CSV.
    """
    def setUp(self):
        super().setUp()

        # 1. Compra con IVA Crédito Fiscal 15% y Retenciones RET-2026-0001
        self.po = PurchaseOrder.objects.create(
            organization=self.org,
            number='OC-2026-0001',
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            supplier_invoice_number='FAC-PRV-9901',
            status=PurchaseOrder.Status.RECEIVED,
            issue_date=timezone.now().date(),
            currency_code='NIO',
            currency_symbol='C$',
            subtotal=Decimal('100000.00'),
            tax_total=Decimal('15000.00'),
            gross_total=Decimal('115000.00'),
            ir_withheld_amount=Decimal('1000.00'),
            imi_withheld_amount=Decimal('1000.00'),
            net_payable=Decimal('113000.00'),
            withholding_certificate_number='RET-2026-0001',
            created_by=self.user_comm,
        )

        # 2. Factura emitida con IVA Débito Fiscal 15% y Retenciones sufridas
        self.invoice = Invoice.objects.create(
            organization=self.org,
            number='FAC-2026-0001',
            account=self.account,
            status=Invoice.Status.ISSUED,
            issue_date=timezone.now().date(),
            currency_code='NIO',
            currency_symbol='C$',
            subtotal=Decimal('80000.00'),
            tax_total=Decimal('12000.00'),
            gross_total=Decimal('92000.00'),
            ir_retention_amount=Decimal('1600.00'),
            imi_retention_amount=Decimal('800.00'),
            net_receivable=Decimal('89600.00'),
            created_by=self.user_comm,
        )

    def test_tax_center_view_calculations(self):
        client = Client()
        client.force_login(self.user_coord)

        response = client.get(reverse('billing:vet_dgi_center'))
        self.assertEqual(response.status_code, 200)

        # Verificación del Cuadro de Liquidación Mensual DGI
        # IVA Débito (12,000) - IVA Crédito (15,000) = Saldo a Favor C$ 3,000.00
        self.assertEqual(response.context['tot_sales_iva'], Decimal('12000.00'))
        self.assertEqual(response.context['tot_purchases_iva'], Decimal('15000.00'))
        self.assertEqual(response.context['iva_neto_dgi'], Decimal('-3000.00'))
        self.assertFalse(response.context['is_iva_payable'])
        self.assertEqual(response.context['iva_favor_amount'], Decimal('3000.00'))

        # Retenciones practicadas (IR 1,000 + IMI 1,000 = 2,000 por enterar a DGI/Alcaldía)
        self.assertEqual(response.context['tot_ret_ir'], Decimal('1000.00'))
        self.assertEqual(response.context['tot_ret_imi'], Decimal('1000.00'))
        self.assertEqual(response.context['tot_ret_practiced'], Decimal('2000.00'))

    def test_csv_export_endpoints(self):
        client = Client()
        client.force_login(self.user_comm)

        # 1. Export Retenciones CSV
        resp_ret = client.get(reverse('billing:vet_dgi_export_csv', kwargs={'report_type': 'retentions'}))
        self.assertEqual(resp_ret.status_code, 200)
        self.assertEqual(resp_ret['Content-Type'], 'text/csv; charset=utf-8')
        content_ret = resp_ret.content.decode('utf-8')
        self.assertIn('J0310000999999', content_ret)
        self.assertIn('RET-2026-0001', content_ret)
        self.assertIn('1000.00', content_ret)

        # 2. Export Compras IVA CSV
        resp_pur = client.get(reverse('billing:vet_dgi_export_csv', kwargs={'report_type': 'purchases_iva'}))
        self.assertEqual(resp_pur.status_code, 200)
        self.assertEqual(resp_pur['Content-Type'], 'text/csv; charset=utf-8')
        content_pur = resp_pur.content.decode('utf-8')
        self.assertIn('OC-2026-0001', content_pur)
        self.assertIn('100000.00', content_pur)
        self.assertIn('15000.00', content_pur)

        # 3. Export Ventas DGI CSV
        resp_sal = client.get(reverse('billing:vet_dgi_export_csv', kwargs={'report_type': 'sales_dgi'}))
        self.assertEqual(resp_sal.status_code, 200)
        self.assertEqual(resp_sal['Content-Type'], 'text/csv; charset=utf-8')
        content_sal = resp_sal.content.decode('utf-8')
        self.assertIn('FAC-2026-0001', content_sal)
        self.assertIn('J0310000000001', content_sal)
        self.assertIn('12000.00', content_sal)
        self.assertIn('89600.00', content_sal)


class AccountingLedgerSyncTests(VetCashBaseTestCase):
    """
    Pruebas del Puente de Sincronización Contable con apps/finance.
    Verifica Partida Doble cuadrada (Debe == Haber).
    """
    def test_sync_ledger_maintains_balanced_double_entry(self):
        # 1. Compra recibida
        po = PurchaseOrder.objects.create(
            organization=self.org,
            number='OC-2026-0099',
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            supplier_invoice_number='FAC-SIN-5521',
            status=PurchaseOrder.Status.RECEIVED,
            issue_date=timezone.now().date(),
            currency_code='NIO',
            currency_symbol='C$',
            subtotal=Decimal('50000.00'),
            tax_total=Decimal('7500.00'),
            gross_total=Decimal('57500.00'),
            ir_withheld_amount=Decimal('500.00'),
            imi_withheld_amount=Decimal('500.00'),
            net_payable=Decimal('56500.00'),
            withholding_certificate_number='RET-2026-0099',
            created_by=self.user_comm,
        )

        # 2. Factura emitida
        inv = Invoice.objects.create(
            organization=self.org,
            number='FAC-2026-0099',
            account=self.account,
            status=Invoice.Status.ISSUED,
            issue_date=timezone.now().date(),
            currency_code='NIO',
            currency_symbol='C$',
            subtotal=Decimal('60000.00'),
            tax_total=Decimal('9000.00'),
            gross_total=Decimal('69000.00'),
            ir_retention_amount=Decimal('1200.00'),
            imi_retention_amount=Decimal('600.00'),
            net_receivable=Decimal('67200.00'),
            created_by=self.user_comm,
        )

        # Ejecutar sincronización
        stats = sync_commercial_and_purchasing_to_ledger(self.org, self.user_owner)
        self.assertGreaterEqual(stats['total_entries'], 2)

        # Verificar todas las pólizas generadas
        entries = JournalEntry.objects.filter(organization=self.org)
        self.assertGreaterEqual(entries.count(), 2)

        for entry in entries:
            self.assertTrue(entry.is_balanced, f"Póliza {entry.number} no está cuadrada: D={entry.total_debit} H={entry.total_credit}")
            self.assertEqual(entry.total_debit, entry.total_credit)
            self.assertGreater(entry.total_debit, Decimal('0.00'))


class RBACPermissionsMatrixTests(VetCashBaseTestCase):
    """
    Pruebas de la Matriz Jerárquica RBAC:
    - role_level < 80: HTTP 403 en caja y reportes VET-DGI.
    - role_level 80: Lectura permitida (HTTP 200), pero operaciones de escritura/cierre y exportación bloqueadas (HTTP 403).
    - role_level 85+: Acceso total a apertura/cierre, reportes, exportación CSV y sincronización contable.
    """
    def test_role_level_below_80_gets_403(self):
        client = Client()
        client.force_login(self.user_sst)  # SST_OFFICER (70)

        # 1. Arqueos de Caja
        resp_cash_list = client.get(reverse('billing:cash_session_list'))
        self.assertEqual(resp_cash_list.status_code, 403)

        resp_cash_open = client.post(reverse('billing:cash_session_open'), {'opening_cash_nio': '1000.00'})
        self.assertEqual(resp_cash_open.status_code, 403)

        # 2. VET-DGI
        resp_vet = client.get(reverse('billing:vet_dgi_center'))
        self.assertEqual(resp_vet.status_code, 403)

        resp_csv = client.get(reverse('billing:vet_dgi_export_csv', kwargs={'report_type': 'retentions'}))
        self.assertEqual(resp_csv.status_code, 403)

        resp_sync = client.post(reverse('billing:vet_dgi_sync_ledger'))
        self.assertEqual(resp_sync.status_code, 403)

    def test_role_level_80_read_only_and_write_blocked(self):
        client = Client()
        client.force_login(self.user_coord)  # OPERATIONS_COORD (80)

        # Lectura permitida
        resp_cash_list = client.get(reverse('billing:cash_session_list'))
        self.assertEqual(resp_cash_list.status_code, 200)

        resp_vet = client.get(reverse('billing:vet_dgi_center'))
        self.assertEqual(resp_vet.status_code, 200)

        # Escritura / Exportación bloqueada (requiere 85+)
        resp_cash_open = client.post(reverse('billing:cash_session_open'), {'opening_cash_nio': '1000.00'})
        self.assertEqual(resp_cash_open.status_code, 403)

        resp_csv = client.get(reverse('billing:vet_dgi_export_csv', kwargs={'report_type': 'retentions'}))
        self.assertEqual(resp_csv.status_code, 403)

        resp_sync = client.post(reverse('billing:vet_dgi_sync_ledger'))
        self.assertEqual(resp_sync.status_code, 403)

    def test_role_level_85_full_access(self):
        client = Client()
        client.force_login(self.user_comm)  # COMMERCIAL_MGR (85)

        # Acceso total a lecturas y exportaciones
        resp_cash_list = client.get(reverse('billing:cash_session_list'))
        self.assertEqual(resp_cash_list.status_code, 200)

        resp_vet = client.get(reverse('billing:vet_dgi_center'))
        self.assertEqual(resp_vet.status_code, 200)

        resp_csv = client.get(reverse('billing:vet_dgi_export_csv', kwargs={'report_type': 'retentions'}))
        self.assertEqual(resp_csv.status_code, 200)

        resp_sync = client.post(reverse('billing:vet_dgi_sync_ledger'))
        self.assertEqual(resp_sync.status_code, 302)  # Redirección tras éxito
