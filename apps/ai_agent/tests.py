import datetime
import hashlib
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import CountryConfig
from apps.crm.models import Account, Quote, QuoteItem
from apps.inventory.models import InventoryItem, Warehouse
from apps.operations.models import Crew, WorkOrder, WorkOrderItem
from apps.repository.models import CorporateDocument, RepositoryFolder
from apps.tickets.models import SupportTicket
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel
from apps.ai_agent.models import McpAccessToken, McpAuditLog
from apps.ai_agent.services import (
    authenticate_mcp_token,
    execute_mcp_tool,
    generate_mcp_token,
)

User = get_user_model()


class McpBaseTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        self.country, _ = CountryConfig.objects.get_or_create(
            code='NI',
            defaults={
                'name': 'Nicaragua',
                'primary_currency_code': 'NIO',
                'primary_currency_symbol': 'C$',
                'is_active': True,
            }
        )

        self.org_a = Organization.objects.create(
            name='IMESA INGENIERÍA S.A.',
            legal_name='IMESA INGENIERÍA S.A.',
            slug='imesa-ni',
            tax_id='J0310000000018',
            country=self.country,
            currency='NIO',
            enabled_modules=['crm', 'operations', 'sst', 'inventory', 'finance', 'billing', 'purchasing', 'repository', 'tickets', 'ai_agent'],
            onboarding_completed=True,
        )

        self.org_b = Organization.objects.create(
            name='TENANT B CORP S.A.',
            legal_name='TENANT B CORP S.A.',
            slug='tenant-b-ni',
            tax_id='J0310000009999',
            country=self.country,
            currency='NIO',
            enabled_modules=['crm', 'operations', 'sst', 'inventory', 'finance', 'billing', 'purchasing', 'repository', 'tickets', 'ai_agent'],
            onboarding_completed=True,
        )

        # 1. Owner Admin Org A (100)
        self.owner_a = User.objects.create_user(
            email='owner@imesa.ni',
            password='Password123*',
            full_name='Ing. Roberto Valenzuela'
        )
        OrganizationMembership.objects.create(
            user=self.owner_a,
            organization=self.org_a,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
        )

        # 2. Coordinador de Operaciones Org A (80)
        self.ops_coord_a = User.objects.create_user(
            email='mfonseca@imesa.ni',
            password='Password123*',
            full_name='Ing. Marcos Fonseca'
        )
        OrganizationMembership.objects.create(
            user=self.ops_coord_a,
            organization=self.org_a,
            role_level=RoleLevel.OPERATIONS_COORD,
            is_active=True,
        )

        # 3. Ingeniero Residente Org A (50)
        self.engineer_a = User.objects.create_user(
            email='cchamorro@imesa.ni',
            password='Password123*',
            full_name='Ing. Carlos Chamorro'
        )
        OrganizationMembership.objects.create(
            user=self.engineer_a,
            organization=self.org_a,
            role_level=RoleLevel.ENGINEER,
            is_active=True,
        )

        # 4. Técnico de Campo Org A (20)
        self.tech_a = User.objects.create_user(
            email='cruiz@imesa.ni',
            password='Password123*',
            full_name='Téc. Carlos Ruiz'
        )
        OrganizationMembership.objects.create(
            user=self.tech_a,
            organization=self.org_a,
            role_level=RoleLevel.TECHNICIAN,
            is_active=True,
        )

        # 5. Usuario Org B (Owner 100)
        self.user_b = User.objects.create_user(
            email='owner@tenantb.ni',
            password='Password123*',
            full_name='Lic. Sandra Morales'
        )
        OrganizationMembership.objects.create(
            user=self.user_b,
            organization=self.org_b,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
        )


class McpTokenSecurityTests(McpBaseTestCase):
    def test_token_generation_and_hashing(self):
        """
        El generador produce un hash SHA-256 inalterable y retorna el secreto plano una única vez.
        """
        token_obj, raw_token = generate_mcp_token(
            organization=self.org_a,
            name="Agente Pruebas Seguras",
            scoped_role_level=RoleLevel.OPERATIONS_COORD,
            allowed_tools=['query_workorders'],
            created_by=self.owner_a,
        )
        self.assertTrue(raw_token.startswith('etn_mcp_'))
        self.assertEqual(token_obj.token_prefix, f"{raw_token[:12]}...")
        expected_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
        self.assertEqual(token_obj.token_hash, expected_hash)
        self.assertTrue(token_obj.is_usable)

    def test_authenticate_mcp_token_success_and_failure(self):
        """
        Verifica autenticación criptográfica vía hash SHA-256.
        """
        token_obj, raw_token = generate_mcp_token(
            organization=self.org_a,
            name="Claude Desktop Ops",
            scoped_role_level=RoleLevel.OPERATIONS_COORD,
            allowed_tools=['query_workorders'],
            created_by=self.owner_a,
        )

        # Autenticación exitosa
        auth_token = authenticate_mcp_token(raw_token)
        self.assertIsNotNone(auth_token)
        self.assertEqual(auth_token.pk, token_obj.pk)

        # Falla con token alterado
        fake_token = raw_token[:-4] + "dead"
        self.assertIsNone(authenticate_mcp_token(fake_token))

        # Falla con string malformado
        self.assertIsNone(authenticate_mcp_token("invalido_sin_prefijo"))
        self.assertIsNone(authenticate_mcp_token(""))

    def test_token_revocation_and_expiration(self):
        """
        Un token revocado (is_active=False) o expirado queda inutilizable inmediatamente.
        """
        token_obj, raw_token = generate_mcp_token(
            organization=self.org_a,
            name="Token Temporal",
            scoped_role_level=RoleLevel.OPERATIONS_COORD,
            allowed_tools=['query_workorders'],
            created_by=self.owner_a,
        )

        # Revocación instantánea en 1-clic
        token_obj.is_active = False
        token_obj.save(update_fields=['is_active'])
        self.assertIsNone(authenticate_mcp_token(raw_token))

        # Expiración
        token_obj.is_active = True
        token_obj.expires_at = timezone.now() - datetime.timedelta(minutes=1)
        token_obj.save(update_fields=['is_active', 'expires_at'])
        self.assertIsNone(authenticate_mcp_token(raw_token))

    def test_audit_log_strict_immutability(self):
        """
        McpAuditLog prohíbe terminantemente modificaciones y borrados individuales.
        """
        token_obj, _raw = generate_mcp_token(
            organization=self.org_a,
            name="Token Auditoría",
            scoped_role_level=RoleLevel.OPERATIONS_COORD,
            allowed_tools=['query_workorders'],
            created_by=self.owner_a,
        )

        log_entry = McpAuditLog.objects.create(
            organization=self.org_a,
            token=token_obj,
            tool_name='query_workorders',
            request_payload={'phase': 'ALL'},
            response_status=McpAuditLog.ResponseStatus.SUCCESS,
            execution_ms=25,
            ip_address='127.0.0.1',
        )

        # Intentar modificar el registro de auditoría debe disparar ValidationError
        with self.assertRaises(ValidationError):
            log_entry.response_status = McpAuditLog.ResponseStatus.DENIED
            log_entry.save()

        # Intentar borrar el registro debe disparar ValidationError
        with self.assertRaises(ValidationError):
            log_entry.delete()


class McpToolExecutionAndRbacTests(McpBaseTestCase):
    def setUp(self):
        super().setUp()
        # Sembrar datos operativos en Org A
        self.account_a = Account.objects.create(
            organization=self.org_a,
            code='CLI-001',
            commercial_name='ENATREL Subestaciones',
            tax_id='J0310000000018',
        )
        self.wo_a = WorkOrder.objects.create(
            organization=self.org_a,
            number='OT-2026-0001',
            title='Mantenimiento Preventivo Transformador T1',
            account=self.account_a,
            phase=WorkOrder.Phase.IN_PROGRESS,
            is_high_risk=False,
            sst_cleared=True,
        )

    def test_level_50_token_denied_for_financial_summary(self):
        """
        Un token con scoped_role_level=50 (ENGINEER) que intente ejecutar query_financial_summary
        debe ser DENEGADO por RBAC (status='DENIED') y quedar registrado en McpAuditLog.
        """
        token_eng, _raw = generate_mcp_token(
            organization=self.org_a,
            name="Agente Ingeniero Nivel 50",
            scoped_role_level=RoleLevel.ENGINEER,  # 50
            allowed_tools=['query_workorders', 'query_financial_summary'],
            created_by=self.owner_a,
        )

        # Ejecución interna por servicio
        result = execute_mcp_tool(
            organization=self.org_a,
            token_obj=token_eng,
            tool_name='query_financial_summary',
            params={},
            ip_address='192.168.1.100',
        )

        self.assertEqual(result.get('status'), 'DENIED')
        self.assertEqual(result.get('error'), 'RBAC_INSUFFICIENT_LEVEL')
        self.assertIn("Acceso denegado por RBAC", result.get('message', ''))

        # Verificar que se grabó en McpAuditLog con estado DENIED
        latest_log = McpAuditLog.objects.filter(token=token_eng).first()
        self.assertIsNotNone(latest_log)
        self.assertEqual(latest_log.response_status, McpAuditLog.ResponseStatus.DENIED)
        self.assertEqual(latest_log.tool_name, 'query_financial_summary')

    def test_level_80_token_executes_financial_summary_successfully(self):
        """
        Un token con scoped_role_level=80 (OPERATIONS_COORD) ejecuta query_financial_summary con éxito.
        """
        token_ops, _raw = generate_mcp_token(
            organization=self.org_a,
            name="Agente Operaciones Nivel 80",
            scoped_role_level=RoleLevel.OPERATIONS_COORD,  # 80
            allowed_tools=['query_workorders', 'query_financial_summary'],
            created_by=self.owner_a,
        )

        result = execute_mcp_tool(
            organization=self.org_a,
            token_obj=token_ops,
            tool_name='query_financial_summary',
            params={},
            ip_address='127.0.0.1',
        )

        self.assertEqual(result.get('status'), 'SUCCESS')
        self.assertIn('bank_accounts', result.get('data', {}))
        self.assertIn('petty_cash_funds', result.get('data', {}))

        # Verificar telemetría en McpAuditLog
        latest_log = McpAuditLog.objects.filter(token=token_ops).first()
        self.assertIsNotNone(latest_log)
        self.assertEqual(latest_log.response_status, McpAuditLog.ResponseStatus.SUCCESS)

    def test_mcp_http_endpoint_bearer_auth_and_rbac_enforcement(self):
        """
        Endpoint POST /mcp/v1/execute/ con autenticación Bearer y rechazo 403 por RBAC.
        """
        token_eng, raw_token_eng = generate_mcp_token(
            organization=self.org_a,
            name="Agente API L50",
            scoped_role_level=RoleLevel.ENGINEER,
            allowed_tools=['query_workorders', 'query_financial_summary'],
            created_by=self.owner_a,
        )

        url = reverse('ai_agent:mcp_execute')

        # 1. Petición sin token -> 401 Unauthorized
        res_no_auth = self.client.post(
            url,
            data=json.dumps({'tool': 'query_workorders', 'parameters': {}}),
            content_type='application/json',
        )
        self.assertEqual(res_no_auth.status_code, 401)

        # 2. Invocación permitida (query_workorders con L50) -> 200 OK
        res_success = self.client.post(
            url,
            data=json.dumps({'tool': 'query_workorders', 'params': {}}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f"Bearer {raw_token_eng}",
        )
        self.assertEqual(res_success.status_code, 200)
        data_success = res_success.json()
        self.assertEqual(data_success.get('status'), 'SUCCESS')
        self.assertEqual(data_success.get('data', {}).get('total_count'), 1)

        # 3. Invocación prohibida por RBAC (query_financial_summary con L50) -> 403 Forbidden
        res_denied = self.client.post(
            url,
            data=json.dumps({'tool': 'query_financial_summary', 'params': {}}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f"Bearer {raw_token_eng}",
        )
        self.assertEqual(res_denied.status_code, 403)
        data_denied = res_denied.json()
        self.assertEqual(data_denied.get('status'), 'DENIED')

        # Verificar que el log registra el rechazo
        denied_log = McpAuditLog.objects.filter(token=token_eng, response_status=McpAuditLog.ResponseStatus.DENIED).first()
        self.assertIsNotNone(denied_log)


class GlobalOmniSearchRbacTests(McpBaseTestCase):
    def setUp(self):
        super().setUp()
        # Sembrar datos en Org A
        self.acc_a = Account.objects.create(
            organization=self.org_a,
            code='CLI-001',
            commercial_name='ENATREL Subestación Central',
            tax_id='J0310000000018',
        )
        self.quote_a = Quote.objects.create(
            organization=self.org_a,
            number='COT-2026-0001',
            account=self.acc_a,
            title='Construcción de Bahía 230kV ENATREL',
            subtotal=Decimal('45000.00'),
            tax_total=Decimal('6750.00'),
            grand_total=Decimal('51750.00'),
            created_by=self.ops_coord_a,
        )

        # Cuadrilla para el Técnico Carlos Ruiz
        self.crew_a = Crew.objects.create(
            organization=self.org_a,
            code='CUAD-01',
            name='Cuadrilla Electromecánica Alfa',
            leader=self.tech_a,
        )

        self.wo_assigned = WorkOrder.objects.create(
            organization=self.org_a,
            number='OT-2026-0001',
            title='Pruebas Dieléctricas ENATREL',
            account=self.acc_a,
            assigned_engineer=self.engineer_a,
            assigned_crew=self.crew_a,
            phase=WorkOrder.Phase.IN_PROGRESS,
        )
        self.wo_unassigned = WorkOrder.objects.create(
            organization=self.org_a,
            number='OT-2026-0002',
            title='Inspección ENATREL Planta Térmica',
            account=self.acc_a,
            phase=WorkOrder.Phase.IN_PROGRESS,
        )
        self.folder_confidential = RepositoryFolder.objects.create(
            organization=self.org_a,
            code='DIR-FIN-01',
            name='Auditorías Financieras ENATREL',
            min_role_level_view=RoleLevel.OPERATIONS_COORD,  # 80
        )
        self.doc_confidential = CorporateDocument.objects.create(
            organization=self.org_a,
            folder=self.folder_confidential,
            code='DOC-2026-0001',
            title='Auditoría de Rentabilidad ENATREL 2026',
        )

        # Sembrar datos idénticos en Org B para probar aislamiento Multi-Tenant
        self.acc_b = Account.objects.create(
            organization=self.org_b,
            code='CLI-999',
            commercial_name='ENATREL Falso Tenant B',
            tax_id='J0310000009999',
        )

    def test_technician_does_not_see_quotes_or_confidential_docs(self):
        """
        Un Técnico (Nivel 20) busca 'ENATREL':
        - NO debe recibir Cotizaciones (Quotes)
        - NO debe recibir Clientes comerciales (Accounts)
        - NO debe recibir Documentos confidenciales de carpetas Nivel 80+
        - Solo debe recibir su Orden de Trabajo asignada
        """
        self.client.force_login(self.tech_a)

        search_url = reverse('tenancy:omnisearch')
        res = self.client.get(search_url, {'q': 'ENATREL'})
        self.assertEqual(res.status_code, 200)

        # Verificar contexto de la vista
        self.assertEqual(len(res.context.get('quotes', [])), 0, "El Técnico no debe ver Cotizaciones.")
        self.assertEqual(len(res.context.get('accounts', [])), 0, "El Técnico no debe ver Clientes CRM.")
        self.assertEqual(len(res.context.get('documents', [])), 0, "El Técnico no debe ver Documentos Confidenciales N80+.")

        # Debe ver únicamente la OT asignada a su cuadrilla
        wo_results = res.context.get('work_orders', [])
        self.assertEqual(len(wo_results), 1)
        self.assertEqual(wo_results[0].number, 'OT-2026-0001')

    def test_operations_coordinator_sees_all_authorized_sections(self):
        """
        El Coordinador de Operaciones (Nivel 80) busca 'ENATREL':
        - Recibe Clientes, Cotizaciones, OTs del Tenant y Documentos de su nivel.
        - Jamás recibe datos del Tenant B.
        """
        self.client.force_login(self.ops_coord_a)

        search_url = reverse('tenancy:omnisearch')
        res = self.client.get(search_url, {'q': 'ENATREL'})
        self.assertEqual(res.status_code, 200)

        self.assertGreaterEqual(len(res.context.get('accounts', [])), 1)
        self.assertGreaterEqual(len(res.context.get('quotes', [])), 1)
        self.assertEqual(len(res.context.get('work_orders', [])), 2)
        self.assertGreaterEqual(len(res.context.get('documents', [])), 1)

        # Verificar estricto aislamiento de Tenant: ninguno debe pertenecer al Tenant B
        for acc in res.context.get('accounts', []):
            self.assertEqual(acc.organization_id, self.org_a.id)


class SwissGridPrintViewsTests(McpBaseTestCase):
    def setUp(self):
        super().setUp()
        self.account = Account.objects.create(
            organization=self.org_a,
            code='CLI-001',
            commercial_name='ENATREL - Transmisión Eléctrica',
            legal_name='Empresa Nacional de Transmisión Eléctrica',
            tax_id='J0310000000018',
            address='Managua, Nicaragua',
        )
        self.quote = Quote.objects.create(
            organization=self.org_a,
            number='COT-2026-0001',
            account=self.account,
            title='Instalación de Transformador de Potencia 230kV',
            subtotal=Decimal('35000.00'),
            tax_rate=Decimal('15.00'),
            tax_total=Decimal('5250.00'),
            grand_total=Decimal('40250.00'),
            currency_code='NIO',
            currency_symbol='C$',
            exchange_rate=Decimal('36.80'),
            created_by=self.ops_coord_a,
            approved_by=self.owner_a,
        )
        QuoteItem.objects.create(
            organization=self.org_a,
            quote=self.quote,
            item_type=QuoteItem.ItemType.SERVICE,
            description='Montaje y calibración mecánica de bahía de llegada',
            quantity=Decimal('1.00'),
            unit_price=Decimal('20000.00'),
        )

        self.work_order = WorkOrder.objects.create(
            organization=self.org_a,
            number='OT-2026-0001',
            title='Pruebas de Campo Transformador T1',
            account=self.account,
            source_quote=self.quote,
            phase=WorkOrder.Phase.IN_PROGRESS,
            is_high_risk=False,
            sst_cleared=True,
            assigned_engineer=self.engineer_a,
        )
        WorkOrderItem.objects.create(
            organization=self.org_a,
            work_order=self.work_order,
            code='PRV-01',
            description='Prueba de factor de potencia y resistencia de devanados',
            unit='SERV',
            planned_quantity=Decimal('1.00'),
            executed_quantity=Decimal('1.00'),
        )

    def test_quote_print_view_renders_200_ok(self):
        """
        La vista de impresión de Cotización Formal Bimonetaria devuelve 200 OK y
        cumple con el membrete fiscal, desglose de impuestos e importes.
        """
        self.client.force_login(self.ops_coord_a)
        url = reverse('crm:quote_print', kwargs={'pk': self.quote.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('COTIZACIÓN TÉCNICA FORMAL', content)
        self.assertIn(self.quote.number, content)
        self.assertIn('ENATREL - Transmisión Eléctrica', content)
        self.assertIn('LIQUIDACIÓN TRIBUTARIA', content)
        self.assertIn('20000.00', content)
        self.assertIn('3000.00', content)

    def test_workorder_print_view_renders_200_ok(self):
        """
        La vista de impresión de Orden de Trabajo & Acta de Entrega devuelve 200 OK
        con recuadros para Ingeniero Residente, Oficial SST y Cliente.
        """
        self.client.force_login(self.ops_coord_a)
        url = reverse('operations:workorder_print', kwargs={'pk': self.work_order.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('ACTA DE ENTREGA TÉCNICA', content)
        self.assertIn(self.work_order.number, content)
        self.assertIn('INGENIERO RESIDENTE', content)
        self.assertIn('OFICIAL SST · LEY 618', content)
        self.assertIn('RECEPCIÓN CONFORME · CLIENTE', content)

    def test_print_views_cross_tenant_isolation(self):
        """
        Un usuario de otra organización (Tenant B) no puede acceder a las hojas impresas de Org A.
        """
        self.client.force_login(self.user_b)
        url_quote = reverse('crm:quote_print', kwargs={'pk': self.quote.pk})
        res_quote = self.client.get(url_quote)
        self.assertEqual(res_quote.status_code, 404)

        url_wo = reverse('operations:workorder_print', kwargs={'pk': self.work_order.pk})
        res_wo = self.client.get(url_wo)
        self.assertEqual(res_wo.status_code, 404)
