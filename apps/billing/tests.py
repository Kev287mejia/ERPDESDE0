from decimal import Decimal
import datetime
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceItem, PaymentReceipt
from apps.core.models import CountryConfig
from apps.crm.models import Account, Quote, QuoteItem
from apps.operations.models import WorkOrder, WorkOrderItem, WorkOrderTimelineLog
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel

User = get_user_model()


class BillingModuleTestSuite(TestCase):
    """
    Suite Integral de Pruebas Unitarias y de Integración para el Módulo Fiscal y Cartera (apps/billing).
    Garantiza:
    1. Aislamiento Multi-Tenant estricto.
    2. Precisión Matemática Ley 822 DGI & IMI Alcaldía sobre Base Imponible Gravable.
    3. Conversión bimonetaria y cierre de saldo a PAID en Recibos Oficiales de Caja (ROC).
    4. Inmutabilidad de los Recibos ROC.
    5. Conversión en 1 Clic desde Cotización (Quote -> Invoice) y Orden de Trabajo (WorkOrder -> Invoice).
    6. Versatilidad de Perfiles de Giro de Negocio (Business Presets).
    7. Matriz de Autorización RBAC por nivel jerárquico.
    """

    def setUp(self):
        # 1. Configuración Regional Nicaragua
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
                'default_tax_name': 'IVA',
                'default_tax_rate': Decimal('15.00'),
                'is_active': True,
            }
        )

        # 2. Organización Principal y Organización Invasora
        self.org = Organization.objects.create(
            name="SERMANSA Ingeniería S.A.",
            legal_name="Servicios y Mantenimiento Electromecánico S.A.",
            slug="sermansa-ni",
            tax_id="J0310000458912",
            country=self.country_ni,
            currency=Organization.Currency.NIO,
            enabled_modules=['crm', 'operations', 'sst', 'inventory', 'billing'],
            business_profile=Organization.BusinessProfile.ENGINEERING_SERVICES,
            is_active=True,
        )

        self.org_other = Organization.objects.create(
            name="Competencia Industrial S.A.",
            slug="competencia-ni",
            tax_id="J0310000999999",
            country=self.country_ni,
            currency=Organization.Currency.NIO,
            enabled_modules=['crm', 'billing'],
            is_active=True,
        )

        # 3. Usuarios de Distintos Niveles Jerárquicos
        # Nivel 100: Owner / Administrador General
        self.owner = User.objects.create_user(
            email='owner@sermansa.ni',
            full_name='Ing. Carlos Mendoza (Owner)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.org,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 85: Gerente Comercial
        self.commercial_mgr = User.objects.create_user(
            email='comercial@sermansa.ni',
            full_name='Lic. Valentina Jarquín (Comercial)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.commercial_mgr,
            organization=self.org,
            role_level=RoleLevel.COMMERCIAL_MGR,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 80: Coordinador de Operaciones
        self.ops_coord = User.objects.create_user(
            email='operaciones@sermansa.ni',
            full_name='Ing. Marcos Fonseca (Operaciones)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.ops_coord,
            organization=self.org,
            role_level=RoleLevel.OPERATIONS_COORD,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 50: Ingeniero Residente
        self.engineer = User.objects.create_user(
            email='ingeniero@sermansa.ni',
            full_name='Ing. Roberto Dávila (Ingeniero)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.engineer,
            organization=self.org,
            role_level=RoleLevel.ENGINEER,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 20: Técnico de Campo
        self.technician = User.objects.create_user(
            email='tecnico@sermansa.ni',
            full_name='Téc. Pedro Martínez (Técnico)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.technician,
            organization=self.org,
            role_level=RoleLevel.TECHNICIAN,
            is_active=True,
            is_default_org=True,
        )

        # 4. Clientes Corporativos
        self.client_enatrel = Account.objects.create(
            organization=self.org,
            code='CLI-001',
            commercial_name='ENATREL',
            legal_name='Empresa Nacional de Transmisión Eléctrica',
            tax_id='J0310000000018',
            is_tax_exempt=False,
        )

        self.client_exempt = Account.objects.create(
            organization=self.org,
            code='CLI-002',
            commercial_name='Zona Franca Las Mercedes S.A.',
            tax_id='J0310000088888',
            is_tax_exempt=True,
        )

        self.client = Client()

    def test_01_ley_822_exact_tax_and_retention_calculation(self):
        """
        Prueba el cálculo fiscal exacto según la Ley 822 de la República de Nicaragua:
        - Subtotal: C$ 95,000.00
        - Descuento: C$ 0.00
        - Base Imponible: C$ 95,000.00
        - IVA 15%: C$ 14,250.00
        - Total Facturado Bruto: C$ 109,250.00
        - Retención IR Servicios (2% sobre C$ 95,000.00): C$ 1,900.00
        - Retención Alcaldía IMI (1% sobre C$ 95,000.00): C$ 950.00
        - Total Retenciones: C$ 2,850.00
        - Neto a Cobrar en Caja: C$ 106,400.00
        """
        invoice = Invoice.objects.create(
            organization=self.org,
            account=self.client_enatrel,
            status=Invoice.Status.ISSUED,
            currency_code='NIO',
            currency_symbol='C$',
            exchange_rate=Decimal('36.6243'),
            apply_tax=True,
            tax_name='IVA',
            tax_rate=Decimal('15.00'),
            ir_retention_rate=Decimal('2.00'),
            imi_retention_rate=Decimal('1.00'),
            created_by=self.commercial_mgr,
        )

        InvoiceItem.objects.create(
            organization=self.org,
            invoice=invoice,
            description="Mantenimiento preventivo subestación",
            quantity=Decimal('1.00'),
            unit_price=Decimal('65000.00'),
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=invoice,
            description="Calibración de interruptores SF6",
            quantity=Decimal('1.00'),
            unit_price=Decimal('30000.00'),
        )

        invoice.recalculate_totals()
        invoice.save()

        self.assertEqual(invoice.subtotal, Decimal('95000.00'))
        self.assertEqual(invoice.taxable_base, Decimal('95000.00'))
        self.assertEqual(invoice.tax_total, Decimal('14250.00'))
        self.assertEqual(invoice.gross_total, Decimal('109250.00'))
        self.assertEqual(invoice.ir_retention_amount, Decimal('1900.00'))
        self.assertEqual(invoice.imi_retention_amount, Decimal('950.00'))
        self.assertEqual(invoice.total_retentions, Decimal('2850.00'))
        self.assertEqual(invoice.net_receivable, Decimal('106400.00'))
        self.assertEqual(invoice.balance_due, Decimal('106400.00'))
        self.assertEqual(invoice.status, Invoice.Status.ISSUED)

    def test_02_tax_exempt_client_calculation(self):
        """
        Verifica que para un cliente exento de impuestos (Zona Franca), el IVA no se compute,
        pero las retenciones se apliquen correctamente sobre la base imponible.
        """
        invoice = Invoice.objects.create(
            organization=self.org,
            account=self.client_exempt,
            status=Invoice.Status.ISSUED,
            currency_code='NIO',
            apply_tax=True,
            tax_rate=Decimal('15.00'),
            ir_retention_rate=Decimal('1.00'),  # 1% Bienes
            imi_retention_rate=Decimal('1.00'),
            created_by=self.commercial_mgr,
        )

        InvoiceItem.objects.create(
            organization=self.org,
            invoice=invoice,
            description="Suministro de cable de cobre",
            quantity=Decimal('10.00'),
            unit_price=Decimal('5000.00'),
        )

        invoice.recalculate_totals()
        invoice.save()

        self.assertEqual(invoice.subtotal, Decimal('50000.00'))
        self.assertEqual(invoice.tax_total, Decimal('0.00'))
        self.assertEqual(invoice.gross_total, Decimal('50000.00'))
        self.assertEqual(invoice.ir_retention_amount, Decimal('500.00'))
        self.assertEqual(invoice.imi_retention_amount, Decimal('500.00'))
        self.assertEqual(invoice.net_receivable, Decimal('49000.00'))

    def test_03_bimonetary_cashier_and_balance_closure(self):
        """
        Verifica la caja bimonetaria y liquidación de saldo:
        1. Emisión con neto a cobrar C$ 106,400.00.
        2. Abono parcial de C$ 50,000.00 -> Estado pasa a PARTIAL (Saldo C$ 56,400.00).
        3. Liquidación restante en USD con tasa de cambio oficial BCN (C$ 36.6243).
           Monto USD = 56,400.00 / 36.6243 ≈ 1,539.96 USD.
           La factura pasa automáticamente a PAID y balance_due = 0.00.
        """
        invoice = Invoice.objects.create(
            organization=self.org,
            account=self.client_enatrel,
            status=Invoice.Status.ISSUED,
            currency_code='NIO',
            currency_symbol='C$',
            exchange_rate=Decimal('36.6243'),
            apply_tax=True,
            tax_rate=Decimal('15.00'),
            ir_retention_rate=Decimal('2.00'),
            imi_retention_rate=Decimal('1.00'),
            created_by=self.commercial_mgr,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=invoice,
            description="Servicio integral",
            quantity=Decimal('1.00'),
            unit_price=Decimal('95000.00'),
        )
        invoice.recalculate_totals()
        invoice.save()
        self.assertEqual(invoice.net_receivable, Decimal('106400.00'))

        # Primer Recibo Oficial de Caja: Abono de C$ 50,000.00
        roc1 = PaymentReceipt.objects.create(
            organization=self.org,
            invoice=invoice,
            currency_paid='NIO',
            amount_in_payment_currency=Decimal('50000.00'),
            exchange_rate_applied=invoice.exchange_rate,
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_BAC,
            received_by=self.commercial_mgr,
        )

        invoice.refresh_from_db()
        self.assertTrue(roc1.number.startswith('ROC-'))
        self.assertEqual(invoice.amount_paid, Decimal('50000.00'))
        self.assertEqual(invoice.balance_due, Decimal('56400.00'))
        self.assertEqual(invoice.status, Invoice.Status.PARTIAL)

        # Segundo Recibo Oficial de Caja: Pago en USD por el saldo remanente
        # 56,400 / 36.6243 = 1539.96 USD
        usd_amount = (Decimal('56400.00') / invoice.exchange_rate).quantize(Decimal('0.01'))
        roc2 = PaymentReceipt.objects.create(
            organization=self.org,
            invoice=invoice,
            currency_paid='USD',
            amount_in_payment_currency=usd_amount,
            exchange_rate_applied=invoice.exchange_rate,
            payment_method=PaymentReceipt.PaymentMethod.TRANSFER_LAFISE,
            received_by=self.commercial_mgr,
        )

        invoice.refresh_from_db()
        self.assertAlmostEqual(invoice.balance_due, Decimal('0.00'), delta=Decimal('0.05'))
        self.assertEqual(invoice.status, Invoice.Status.PAID)

    def test_04_payment_receipt_strict_immutability(self):
        """
        Verifica que una vez emitido un Recibo Oficial de Caja (ROC), no puede modificarse
        ni eliminarse, garantizando inviolabilidad de auditoría fiscal.
        """
        invoice = Invoice.objects.create(
            organization=self.org,
            account=self.client_enatrel,
            status=Invoice.Status.ISSUED,
            created_by=self.commercial_mgr,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=invoice,
            description="Item",
            quantity=Decimal('1.00'),
            unit_price=Decimal('1000.00'),
        )
        invoice.recalculate_totals()
        invoice.save()

        receipt = PaymentReceipt.objects.create(
            organization=self.org,
            invoice=invoice,
            currency_paid='NIO',
            amount_in_payment_currency=Decimal('500.00'),
            exchange_rate_applied=invoice.exchange_rate,
            received_by=self.commercial_mgr,
        )

        # Intentar modificar el recibo
        receipt.amount_in_payment_currency = Decimal('600.00')
        with self.assertRaises(ValidationError):
            receipt.save()

        # Intentar eliminar el recibo
        with self.assertRaises(ValidationError):
            receipt.delete()

    def test_05_convert_quote_to_invoice_1_click(self):
        """
        Verifica la conversión en 1 clic de una Cotización Aprobada a Factura Fiscal (Quote -> Invoice).
        """
        quote = Quote.objects.create(
            organization=self.org,
            account=self.client_enatrel,
            title="Licitación Transformadores",
            status=Quote.Status.APPROVED,
            currency_code='NIO',
            currency_symbol='C$',
            exchange_rate=Decimal('36.6243'),
            apply_tax=True,
            tax_name='IVA',
            tax_rate=Decimal('15.00'),
            created_by=self.commercial_mgr,
        )
        QuoteItem.objects.create(
            organization=self.org,
            quote=quote,
            item_type='SERVICE',
            code='SRV-001',
            description='Servicio de Termografía',
            unit='SRV',
            quantity=Decimal('2.00'),
            unit_price=Decimal('15000.00'),
        )

        self.client.force_login(self.commercial_mgr)
        url = reverse('billing:from_quote', kwargs={'quote_pk': quote.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        invoice = Invoice.objects.get(source_quote=quote)
        self.assertEqual(invoice.status, Invoice.Status.ISSUED)
        self.assertEqual(invoice.items.count(), 1)
        self.assertEqual(invoice.subtotal, Decimal('30000.00'))
        self.assertEqual(invoice.gross_total, Decimal('34500.00'))
        self.assertTrue(invoice.number.startswith('FAC-'))

    def test_06_convert_work_order_to_invoice_1_click(self):
        """
        Verifica la conversión en 1 clic de una Orden de Trabajo a Factura Fiscal (WorkOrder -> Invoice).
        Prioriza las cantidades ejecutadas (executed_quantity) y registra evento en WorkOrderTimelineLog.
        """
        quote = Quote.objects.create(
            organization=self.org,
            account=self.client_enatrel,
            title="Mantenimiento Subestaciones",
            status=Quote.Status.APPROVED,
            currency_code='NIO',
            created_by=self.commercial_mgr,
        )
        QuoteItem.objects.create(
            organization=self.org,
            quote=quote,
            item_type='SERVICE',
            code='SRV-OIL',
            description='Tratamiento de aceite dieléctrico',
            quantity=Decimal('10.00'),
            unit_price=Decimal('2500.00'),
        )

        wo = WorkOrder.objects.create(
            organization=self.org,
            account=self.client_enatrel,
            source_quote=quote,
            title="OT de Tratamiento de Aceite",
            phase=WorkOrder.Phase.COMPLETED,
            created_by=self.commercial_mgr,
        )
        WorkOrderItem.objects.create(
            organization=self.org,
            work_order=wo,
            item_type='SERVICE',
            code='SRV-OIL',
            description='Tratamiento de aceite dieléctrico',
            planned_quantity=Decimal('10.00'),
            executed_quantity=Decimal('12.00'),  # Se ejecutaron 12 unidades reales
        )

        self.client.force_login(self.commercial_mgr)
        url = reverse('billing:from_workorder', kwargs={'wo_pk': wo.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        invoice = Invoice.objects.get(source_work_order=wo)
        self.assertEqual(invoice.items.count(), 1)
        item = invoice.items.first()
        self.assertEqual(item.quantity, Decimal('12.00'))
        self.assertEqual(item.unit_price, Decimal('2500.00'))
        self.assertEqual(invoice.subtotal, Decimal('30000.00'))

        # Verificar bitácora cronológica inmutable en la OT
        log = WorkOrderTimelineLog.objects.filter(work_order=wo, event_type='INVOICED').first()
        self.assertIsNotNone(log)
        self.assertIn(invoice.number, log.summary)

    def test_07_business_profile_presets(self):
        """
        Verifica la versatilidad de los Perfiles de Giro de Negocio:
        Aplicar COMMERCIAL_RETAIL actualiza enabled_modules eliminando 'operations' y 'sst',
        dejando el flujo comercial CRM -> Inventario -> Facturación.
        """
        self.client.force_login(self.owner)
        url = reverse('tenancy:apply_preset')

        # Aplicar Preset Comercio / Ferretería
        response = self.client.post(url, {'preset': 'COMMERCIAL_RETAIL'})
        self.assertEqual(response.status_code, 302)

        self.org.refresh_from_db()
        self.assertEqual(self.org.business_profile, Organization.BusinessProfile.COMMERCIAL_RETAIL)
        self.assertIn('crm', self.org.enabled_modules)
        self.assertIn('inventory', self.org.enabled_modules)
        self.assertIn('billing', self.org.enabled_modules)
        self.assertNotIn('operations', self.org.enabled_modules)
        self.assertNotIn('sst', self.org.enabled_modules)

        # Aplicar Preset Servicios de Ingeniería
        response = self.client.post(url, {'preset': 'ENGINEERING_SERVICES'})
        self.assertEqual(response.status_code, 302)
        self.org.refresh_from_db()
        self.assertIn('operations', self.org.enabled_modules)
        self.assertIn('sst', self.org.enabled_modules)

    def test_08_rbac_authorization_matrix(self):
        """
        Verifica la matriz de permisos RBAC para Facturación DGI (/billing/*):
        - COMMERCIAL_MGR (85): Emite facturas, aplica retenciones, registra pagos ROC (200 / 302).
        - OPERATIONS_COORD (80): Lectura permitida (200), pero mutación bloqueada con HTTP 403.
        - ENGINEER (50) & TECHNICIAN (20): Bloqueo total HTTP 403 en todo /billing/*.
        """
        invoice = Invoice.objects.create(
            organization=self.org,
            account=self.client_enatrel,
            status=Invoice.Status.ISSUED,
            created_by=self.commercial_mgr,
        )
        InvoiceItem.objects.create(
            organization=self.org,
            invoice=invoice,
            description="Item",
            quantity=Decimal('1.00'),
            unit_price=Decimal('1000.00'),
        )
        invoice.recalculate_totals()
        invoice.save()

        list_url = reverse('billing:invoice_list')
        detail_url = reverse('billing:invoice_detail', kwargs={'pk': invoice.pk})
        retention_url = reverse('billing:apply_retentions', kwargs={'pk': invoice.pk})
        payment_url = reverse('billing:register_payment', kwargs={'pk': invoice.pk})

        # 1. COMMERCIAL_MGR (85): Acceso total
        self.client.force_login(self.commercial_mgr)
        self.assertEqual(self.client.get(list_url).status_code, 200)
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        # Aplicar retenciones
        resp = self.client.post(retention_url, {'ir_retention_rate': '2.00', 'imi_retention_rate': '1.00'})
        self.assertEqual(resp.status_code, 302)

        # 2. OPERATIONS_COORD (80): Solo Lectura
        self.client.force_login(self.ops_coord)
        self.assertEqual(self.client.get(list_url).status_code, 200)
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        # Intento de registrar cobro -> Bloqueado con HTTP 403
        resp = self.client.post(payment_url, {'amount': '100.00', 'currency_paid': 'NIO'})
        self.assertEqual(resp.status_code, 403)
        # Intento de modificar retenciones -> Bloqueado con HTTP 403
        resp = self.client.post(retention_url, {'ir_retention_rate': '2.00'})
        self.assertEqual(resp.status_code, 403)

        # 3. ENGINEER (50) y TECHNICIAN (20): Bloqueo estricto HTTP 403
        for user in [self.engineer, self.technician]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(list_url).status_code, 403)
            self.assertEqual(self.client.get(detail_url).status_code, 403)

    def test_09_multi_tenant_isolation(self):
        """
        Verifica el aislamiento multi-tenant estricto:
        Un usuario de la organización A no puede ver ni consultar facturas de la organización B.
        """
        other_mgr = User.objects.create_user(
            email='mgr@competencia.ni',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=other_mgr,
            organization=self.org_other,
            role_level=RoleLevel.COMMERCIAL_MGR,
            is_active=True,
            is_default_org=True,
        )

        inv_org = Invoice.objects.create(
            organization=self.org,
            account=self.client_enatrel,
            created_by=self.commercial_mgr,
        )

        self.client.force_login(other_mgr)
        detail_url = reverse('billing:invoice_detail', kwargs={'pk': inv_org.pk})
        response = self.client.get(detail_url)
        # Debe dar 404 porque el queryset está aislado con .for_org(request.organization)
        self.assertEqual(response.status_code, 404)
