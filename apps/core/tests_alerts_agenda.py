import datetime
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceItem
from apps.core.models import CountryConfig
from apps.core.services.alerts_engine import get_active_alerts_for_user
from apps.crm.models import Account
from apps.inventory.models import InventoryItem, Warehouse, InventoryBatch, StockBalance
from apps.operations.models import WorkOrder
from apps.purchasing.models import PurchaseOrder, Supplier
from apps.sst.models import EPPDelivery
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel, CorporateEvent

User = get_user_model()


class AlertsAndAgendaBaseTestCase(TestCase):
    """
    Fixtures y configuración base para pruebas de Radar de Alertas y Agenda Corporativa.
    Configura Organización multi-tenant y usuarios en los 4 niveles jerárquicos clave:
    - Owner/Admin (100)
    - Gerente Comercial (85)
    - Ingeniero Residente (50)
    - Técnico de Campo (20)
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
                'is_active': True,
                'default_tax_rate': Decimal('15.00'),
                'default_tax_name': 'IVA',
            }
        )

        self.org = Organization.objects.create(
            name='INGENIERÍA Y SERVICIOS INTEGRALES S.A.',
            legal_name='Ingeniería y Servicios Integrales de Nicaragua S.A.',
            tax_id='J0310000889911',
            country=self.country_ni,
            currency=Organization.Currency.NIO,
            enabled_modules=['crm', 'operations', 'inventory', 'finance', 'billing', 'purchasing', 'sst', 'tickets'],
        )

        # 1. Propietario / Administrador General (100)
        self.user_owner = User.objects.create_user(
            email='owner@integral.ni',
            password='Password123!',
            full_name='Ing. Fernando Mantilla',
        )
        self.mem_owner = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.user_owner,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
        )

        # 2. Gerente Comercial (85)
        self.user_comm = User.objects.create_user(
            email='comercial@integral.ni',
            password='Password123!',
            full_name='Lic. Marcela Barreto',
        )
        self.mem_comm = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.user_comm,
            role_level=RoleLevel.COMMERCIAL_MGR,
            is_active=True,
        )

        # 3. Ingeniero Residente / Operaciones (50)
        self.user_engineer = User.objects.create_user(
            email='ingeniero@integral.ni',
            password='Password123!',
            full_name='Ing. Carlos Duarte',
        )
        self.mem_engineer = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.user_engineer,
            role_level=RoleLevel.ENGINEER,
            is_active=True,
        )

        # 4. Técnico Electricista de Campo (20)
        self.user_tech = User.objects.create_user(
            email='tecnico@integral.ni',
            password='Password123!',
            full_name='Téc. Marlon Espinoza',
        )
        self.mem_tech = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.user_tech,
            role_level=RoleLevel.TECHNICIAN,
            is_active=True,
        )

        # Entidades Operativas para Hallazgos del Radar
        self.warehouse = Warehouse.objects.create(
            organization=self.org,
            code='BOD-01',
            name='Bodega Central Tipitapa',
        )

        # Ítem con lote caducado (FEFO)
        self.item_med = InventoryItem.objects.create(
            organization=self.org,
            sku='MED-AMX-01',
            name='Amoxicilina 500mg',
            unit='CJ',
            requires_batch_control=True,
            min_stock_level=Decimal('10.00'),
            unit_cost=Decimal('100.00'),
            price_retail=Decimal('150.00'),
        )
        today = timezone.now().date()
        self.batch_expired = InventoryBatch.objects.create(
            organization=self.org,
            warehouse=self.warehouse,
            item=self.item_med,
            batch_number='LOT-EXP-2025',
            manufacturing_date=today - datetime.timedelta(days=400),
            expiration_date=today - datetime.timedelta(days=15),
            quantity_available=Decimal('20.00'),
        )

        # Ítem con stock bajo (LOW_STOCK)
        self.item_cable = InventoryItem.objects.create(
            organization=self.org,
            sku='MAT-CAB-01',
            name='Cable de Potencia 15kV',
            unit='MTS',
            min_stock_level=Decimal('50.00'),
            unit_cost=Decimal('200.00'),
            price_retail=Decimal('260.00'),
        )
        StockBalance.objects.create(
            organization=self.org,
            warehouse=self.warehouse,
            item=self.item_cable,
            quantity=Decimal('8.00'),  # 8.00 <= 50.00 -> LOW_STOCK
        )

        # Cliente para facturación y OT
        self.account = Account.objects.create(
            organization=self.org,
            code='CLI-001',
            commercial_name='ENATREL Transmisión',
            legal_name='Empresa Nacional de Transmisión Eléctrica',
            tax_id='J0310000123456',
        )

        # Orden de Trabajo de Alto Riesgo Bloqueada por SST
        self.wo_locked = WorkOrder.objects.create(
            organization=self.org,
            number='OT-2026-9901',
            account=self.account,
            title='Mantenimiento en Subestación 138kV',
            phase=WorkOrder.Phase.IN_PROGRESS,
            is_high_risk=True,
            sst_cleared=False,  # Bloqueada
            assigned_engineer=self.user_engineer,
            created_by=self.user_engineer,
        )

        # Factura en Mora (CxC Overdue)
        self.invoice_overdue = Invoice.objects.create(
            organization=self.org,
            number='FAC-2026-9901',
            account=self.account,
            status=Invoice.Status.ISSUED,
            payment_condition=Invoice.PaymentCondition.CREDIT_30,
            issue_date=today - datetime.timedelta(days=45),
            due_date=today - datetime.timedelta(days=15),  # Vencida hace 15 días
            currency_code='NIO',
            currency_symbol='C$',
            subtotal=Decimal('80000.00'),
            tax_total=Decimal('12000.00'),
            gross_total=Decimal('92000.00'),
            net_receivable=Decimal('92000.00'),
            balance_due=Decimal('92000.00'),
            created_by=self.user_comm,
        )


class AlertsRadarEngineTests(AlertsAndAgendaBaseTestCase):
    """
    Pruebas del Motor de Detección en Tiempo Real de Alertas Multi-Giro (alerts_engine.py).
    """
    def test_owner_admin_detects_all_vertical_alerts(self):
        """
        Para OWNER_ADMIN (100), el motor detecta alertas de almacén (BATCH_EXPIRED, LOW_STOCK),
        seguridad SST (HIGH_RISK_OT_LOCKED) y finanzas/cartera (INVOICE_OVERDUE).
        """
        data = get_active_alerts_for_user(self.org, self.user_owner, RoleLevel.OWNER_ADMIN)
        codes = [a['code'] for a in data['alerts']]

        self.assertIn('BATCH_EXPIRED', codes)
        self.assertIn('LOW_STOCK', codes)
        self.assertIn('HIGH_RISK_OT_LOCKED', codes)
        self.assertIn('INVOICE_OVERDUE', codes)

        self.assertGreaterEqual(data['counts']['critical'], 2)
        self.assertGreaterEqual(data['counts']['high'], 1)
        self.assertGreaterEqual(data['counts']['total'], 4)

    def test_strict_rbac_confidentiality_technician_sees_no_financial_alerts(self):
        """
        Para TECHNICIAN (20), el motor no incluye CERO alertas financieras ni de almacén
        y no expone datos de facturación ni montos.
        """
        data = get_active_alerts_for_user(self.org, self.user_tech, RoleLevel.TECHNICIAN)
        codes = [a['code'] for a in data['alerts']]

        self.assertNotIn('INVOICE_OVERDUE', codes)
        self.assertNotIn('PURCHASE_PAYABLE_DUE', codes)
        self.assertNotIn('BATCH_EXPIRED', codes)
        self.assertNotIn('LOW_STOCK', codes)

        self.assertEqual(data['counts']['by_category'].get('FINANCE_DGI', 0), 0)
        self.assertEqual(data['counts']['by_category'].get('INVENTORY_FEFO', 0), 0)

    def test_engineer_sees_ops_and_fefo_but_zero_financial_alerts(self):
        """
        Para ENGINEER (50), el motor detecta alertas de FEFO y SST, pero CERO alertas financieras.
        """
        data = get_active_alerts_for_user(self.org, self.user_engineer, RoleLevel.ENGINEER)
        codes = [a['code'] for a in data['alerts']]

        self.assertIn('BATCH_EXPIRED', codes)
        self.assertIn('LOW_STOCK', codes)
        self.assertIn('HIGH_RISK_OT_LOCKED', codes)
        self.assertNotIn('INVOICE_OVERDUE', codes)
        self.assertNotIn('PURCHASE_PAYABLE_DUE', codes)
        self.assertEqual(data['counts']['by_category'].get('FINANCE_DGI', 0), 0)


class AlertsRadarViewsAndHTMXTests(AlertsAndAgendaBaseTestCase):
    """
    Pruebas HTTP de las Vistas de Radar y Dropdown Parcial HTMX.
    """
    def test_technician_radar_view_http_200_and_zero_financial_amounts(self):
        """
        TECHNICIAN (20) consulta /alerts-radar/ y recibe HTTP 200 pero CERO mención a montos
        de facturación 'C$ 92,000.00' ni códigos INVOICE_OVERDUE.
        """
        client = Client()
        client.force_login(self.user_tech)

        response = client.get(reverse('alerts_radar'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertNotIn('INVOICE_OVERDUE', content)
        self.assertNotIn('92,000.00', content)
        self.assertNotIn('FAC-2026-9901', content)

    def test_topbar_alerts_dropdown_partial_htmx(self):
        """
        Consulta del parcial HTMX en /alerts-radar/dropdown/ devuelve el componente Swiss Grid.
        """
        client = Client()
        client.force_login(self.user_owner)

        response = client.get(reverse('alerts_dropdown_partial'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('Radar Proactivo', content)
        self.assertIn('BATCH_EXPIRED', content)
        self.assertIn('INVOICE_OVERDUE', content)


class CorporateAgendaAndFiscalCalendarTests(AlertsAndAgendaBaseTestCase):
    """
    Pruebas de la Agenda Corporativa Unificada y Generador de Calendario Fiscal DGI.
    """
    def test_commercial_manager_generates_fiscal_calendar_idempotently(self):
        """
        COMMERCIAL_MGR (85) genera el calendario fiscal DGI/Alcaldía/INSS del mes.
        Se crean los 3 hitos con min_role_level=OPERATIONS_COORD (80).
        Llamadas repetidas son idempotentes y no duplican eventos.
        """
        client = Client()
        client.force_login(self.user_comm)

        resp = client.post(reverse('generate_fiscal_calendar'))
        self.assertEqual(resp.status_code, 302)

        events = CorporateEvent.objects.filter(
            organization=self.org,
            event_type=CorporateEvent.EventType.TAX_DEADLINE,
        )
        self.assertEqual(events.count(), 3)
        for ev in events:
            self.assertEqual(ev.min_role_level, RoleLevel.OPERATIONS_COORD)

        # Segunda llamada idempotente
        resp2 = client.post(reverse('generate_fiscal_calendar'))
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(events.count(), 3)

    def test_technician_cannot_generate_fiscal_calendar_and_gets_403(self):
        """
        TECHNICIAN (20) recibe HTTP 403 si intenta generar el calendario fiscal.
        """
        client = Client()
        client.force_login(self.user_tech)

        resp = client.post(reverse('generate_fiscal_calendar'))
        self.assertEqual(resp.status_code, 403)

    def test_technician_cannot_see_tax_deadline_events_in_agenda(self):
        """
        TECHNICIAN (20) consulta la agenda /agenda/ y NO ve eventos de tipo TAX_DEADLINE.
        """
        # Crear hito fiscal
        now = timezone.now()
        CorporateEvent.objects.create(
            organization=self.org,
            code='EVT-2026-T001',
            title='Vencimiento Fiscal VET-DGI IVA Mensual',
            event_type=CorporateEvent.EventType.TAX_DEADLINE,
            start_datetime=now,
            min_role_level=RoleLevel.OPERATIONS_COORD,
            created_by=self.user_owner,
        )

        client = Client()
        client.force_login(self.user_tech)

        resp = client.get(reverse('corporate_agenda'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertNotIn('EVT-2026-T001', content)
        self.assertNotIn('Vencimiento Fiscal VET-DGI', content)

    def test_technician_cannot_create_event_and_gets_403(self):
        """
        TECHNICIAN (20) recibe HTTP 403 al intentar programar eventos en /agenda/create/.
        """
        client = Client()
        client.force_login(self.user_tech)

        resp = client.post(reverse('corporate_event_create'), {
            'title': 'Intento de evento por técnico',
            'start_datetime': '2026-10-20T08:00',
        })
        self.assertEqual(resp.status_code, 403)

    def test_engineer_can_create_event_and_auto_elevation_elevates_tax_events(self):
        """
        ENGINEER (50) puede crear un evento técnico. Si crea un TAX_DEADLINE o COMMERCIAL_VISIT,
        save() eleva automáticamente min_role_level a OPERATIONS_COORD (80).
        """
        client = Client()
        client.force_login(self.user_engineer)

        # 1. Crear evento técnico normal
        resp = client.post(reverse('corporate_event_create'), {
            'title': 'Inspección de Transformador 15kVA',
            'event_type': CorporateEvent.EventType.TECHNICAL_MAINTENANCE,
            'priority': CorporateEvent.Priority.HIGH,
            'start_datetime': '2026-10-25T08:00',
            'min_role_level': '50',
        })
        self.assertEqual(resp.status_code, 302)

        ev_tech = CorporateEvent.objects.filter(title='Inspección de Transformador 15kVA').first()
        self.assertIsNotNone(ev_tech)
        self.assertEqual(ev_tech.min_role_level, RoleLevel.ENGINEER)

        # 2. Intentar crear TAX_DEADLINE con min_role_level=20 -> auto elevación a 80
        ev_fiscal = CorporateEvent(
            organization=self.org,
            title='Prueba Elevación Fiscal',
            event_type=CorporateEvent.EventType.TAX_DEADLINE,
            start_datetime=timezone.now(),
            min_role_level=RoleLevel.TECHNICIAN,  # 20
        )
        ev_fiscal.save()
        self.assertEqual(ev_fiscal.min_role_level, RoleLevel.OPERATIONS_COORD)  # Elevado a 80
