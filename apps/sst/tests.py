import uuid
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import CountryConfig
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel
from apps.crm.models import Account
from apps.operations.models import Crew, WorkOrder, WorkOrderItem, WorkOrderTimelineLog
from apps.sst.models import SafetyChecklist, EPPDelivery, LeaveRequest

User = get_user_model()


class SSTModuleEndToEndTestCase(TestCase):
    """
    Suite de Pruebas End-to-End para el Módulo de Seguridad y Salud en el Trabajo (apps/sst).
    Verifica:
    1. Integración Checklist Pre-Operacional -> Liberación Automática de OT de Alto Riesgo.
    2. Control y Acuse de Dotación EPP bajo Normativa MITRAB.
    3. Regla Estricta Anti-Inversión de Mando en Permisos Laborales (approver_level > requester_level).
    4. Segregación Estricta de Funciones en BOM Operativo (SST_OFFICER 70 no puede ejecutar ítems del BOM).
    5. Aislamiento Multi-Tenant Estricto por Organización.
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
            name="Vector Ingeniería Nicaragua, S.A.",
            legal_name="Vector Ingeniería de Centroamérica, S.A.",
            slug="vector-ni-sst",
            tax_id="J0310000199999",
            country=self.country_ni,
            enabled_modules=['crm', 'operations', 'sst'],
            is_active=True,
        )

        # Organización Invasora
        self.org_intruder = Organization.objects.create(
            name="Constructora Invasora S.A.",
            legal_name="Invasora S.A.",
            slug="invasora-ni-sst",
            tax_id="J0310000188888",
            country=self.country_ni,
            enabled_modules=['sst'],
            is_active=True,
        )

        # 3. Usuarios de Distintos Niveles Jerárquicos RBAC
        # Nivel 100: Owner / Administrador General
        self.user_owner = User.objects.create_user(
            email='owner@vector.com.ni',
            full_name='Lic. Fernando Morales (Owner)',
            password='password123'
        )
        OrganizationMembership.objects.create(
            user=self.user_owner,
            organization=self.org,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 80: Coordinador de Operaciones
        self.user_ops_coord = User.objects.create_user(
            email='operaciones@vector.com.ni',
            full_name='Ing. Marcos Ruiz (Coordinador)',
            password='password123'
        )
        OrganizationMembership.objects.create(
            user=self.user_ops_coord,
            organization=self.org,
            role_level=RoleLevel.OPERATIONS_COORD,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 70: Oficial SST
        self.user_sst = User.objects.create_user(
            email='sst@vector.com.ni',
            full_name='Lic. Carmen Silva (Oficial SST)',
            password='password123'
        )
        OrganizationMembership.objects.create(
            user=self.user_sst,
            organization=self.org,
            role_level=RoleLevel.SST_OFFICER,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 50: Ingeniero Residente
        self.user_engineer = User.objects.create_user(
            email='ingeniero@vector.com.ni',
            full_name='Ing. Roberto Solís (Ingeniero)',
            password='password123'
        )
        OrganizationMembership.objects.create(
            user=self.user_engineer,
            organization=self.org,
            role_level=RoleLevel.ENGINEER,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 20: Técnico de Campo
        self.user_tech = User.objects.create_user(
            email='tecnico@vector.com.ni',
            full_name='Juan Pérez (Técnico)',
            password='password123'
        )
        OrganizationMembership.objects.create(
            user=self.user_tech,
            organization=self.org,
            role_level=RoleLevel.TECHNICIAN,
            is_active=True,
            is_default_org=True,
        )

        # 4. Cuenta y Cuadrilla
        self.account = Account.objects.create(
            organization=self.org,
            commercial_name="Planta Industrial Tipitapa",
            tax_id="J0310000112233",
            city="Tipitapa",
        )

        self.crew = Crew.objects.create(
            organization=self.org,
            code="CUAD-01",
            name="Cuadrilla Electromecánica Alfa",
            specialty="Media Tensión",
            leader=self.user_engineer,
            vehicle_plate="M 345-890",
            is_active=True,
        )
        self.crew.members.add(self.user_tech)

    def _get_client_for_user(self, user, org=None):
        """Helper para autenticar cliente HTTP con sesión de organización activa."""
        client = Client()
        client.force_login(user)
        session = client.session
        target_org = org or self.org
        session['active_org_id'] = str(target_org.id)
        session.save()
        return client

    # --------------------------------------------------------------------------
    # TEST 1: Integración Checklist Pre-Operacional -> Liberación SST de OT
    # --------------------------------------------------------------------------
    def test_checklist_submission_and_ot_clearance_by_sst_officer(self):
        """
        Verifica:
        1. Técnico (20) envía Checklist pre-operacional para OT de alto riesgo (sst_cleared=False).
        2. Se crea registro en estado PENDING y escribe en WorkOrderTimelineLog de la OT.
        3. Oficial SST (70) aprueba el checklist; automáticamente la OT cambia a sst_cleared=True
           y se registra el evento inmutable SST_CLEARANCE en la bitácora de la OT.
        """
        wo = WorkOrder.objects.create(
            organization=self.org,
            account=self.account,
            title="Mantenimiento en Línea de Media Tensión 13.8kV",
            is_high_risk=True,
            sst_cleared=False,
            assigned_crew=self.crew,
            phase=WorkOrder.Phase.SCHEDULED,
        )

        client_tech = self._get_client_for_user(self.user_tech)
        url_create = reverse('sst:checklist_create')

        response = client_tech.post(url_create, data={
            'work_order': str(wo.pk),
            'crew': str(self.crew.pk),
            'work_type': SafetyChecklist.WorkType.ELECTRICAL,
            'epp_verified': 'on',
            'loto_verified': 'on',
            'tools_inspected': 'on',
            'area_signaled': 'on',
            'risk_briefing_done': 'on',
            'hazard_notes': 'Línea desenergizada y puesta a tierra provisional colocada.',
        })
        self.assertEqual(response.status_code, 302)

        # Verificar que el checklist se guardó
        chk = SafetyChecklist.objects.filter(work_order=wo).first()
        self.assertIsNotNone(chk)
        self.assertTrue(chk.number.startswith('CHK-'))
        self.assertEqual(chk.status, SafetyChecklist.Status.PENDING)
        self.assertTrue(chk.all_checks_passed())
        self.assertEqual(chk.submitted_by, self.user_tech)

        # Verificar bitácora en la OT
        log_submitted = wo.timeline_logs.filter(event_type='SST_CHECKLIST_SUBMITTED').first()
        self.assertIsNotNone(log_submitted)
        self.assertEqual(log_submitted.actor, self.user_tech)

        # Oficial SST (70) aprueba el checklist
        client_sst = self._get_client_for_user(self.user_sst)
        url_review = reverse('sst:checklist_review', kwargs={'pk': chk.pk})
        resp_review = client_sst.post(url_review, data={
            'action': 'approve',
            'review_comments': 'Protocolo de seguridad verificado en sitio. Se autoriza inicio.',
        })
        self.assertEqual(resp_review.status_code, 302)

        chk.refresh_from_db()
        wo.refresh_from_db()

        self.assertEqual(chk.status, SafetyChecklist.Status.APPROVED)
        self.assertEqual(chk.reviewed_by, self.user_sst)
        self.assertTrue(wo.sst_cleared)

        # Verificar que la bitácora de la OT tiene el evento SST_CLEARANCE
        log_clearance = wo.timeline_logs.filter(event_type='SST_CLEARANCE').first()
        self.assertIsNotNone(log_clearance)
        self.assertIn(chk.number, log_clearance.summary)
        self.assertEqual(log_clearance.actor, self.user_sst)

    # --------------------------------------------------------------------------
    # TEST 2: Control de EPP y Acuse de Recibo (Normativa MITRAB)
    # --------------------------------------------------------------------------
    def test_epp_delivery_and_worker_acknowledgement(self):
        """
        Verifica:
        1. Oficial SST (70) registra entrega de Casco Dieléctrico al Técnico (20).
        2. Técnico (20) confirma recepción satisfactoria (acknowledged_by_worker=True).
        3. Técnico (20) intenta registrar entrega de EPP -> Recibe 403 Forbidden.
        """
        client_sst = self._get_client_for_user(self.user_sst)
        url_create = reverse('sst:epp_create')

        today = timezone.now().date()
        in_one_year = today + timezone.timedelta(days=365)

        response = client_sst.post(url_create, data={
            'collaborator': str(self.user_tech.pk),
            'category': EPPDelivery.Category.HEAD,
            'item_name': 'Casco Dieléctrico Clase E 20kV con Barbiquejo',
            'serial_or_batch': 'LOTE-MSA-2026',
            'quantity': 1,
            'delivery_date': today.strftime('%Y-%m-%d'),
            'expiration_date': in_one_year.strftime('%Y-%m-%d'),
        })
        self.assertEqual(response.status_code, 302)

        epp = EPPDelivery.objects.filter(collaborator=self.user_tech).first()
        self.assertIsNotNone(epp)
        self.assertTrue(epp.code.startswith('EPP-'))
        self.assertEqual(epp.status, EPPDelivery.Status.ACTIVE)
        self.assertFalse(epp.acknowledged_by_worker)
        self.assertEqual(epp.delivered_by, self.user_sst)

        # Técnico (20) confirma recepción
        client_tech = self._get_client_for_user(self.user_tech)
        url_ack = reverse('sst:epp_acknowledge', kwargs={'pk': epp.pk})
        resp_ack = client_tech.post(url_ack)
        self.assertEqual(resp_ack.status_code, 302)

        epp.refresh_from_db()
        self.assertTrue(epp.acknowledged_by_worker)

        # Técnico (20) intenta crear una entrega de EPP -> 403 Forbidden
        resp_forbidden = client_tech.post(url_create, data={
            'collaborator': str(self.user_tech.pk),
            'category': EPPDelivery.Category.HANDS,
            'item_name': 'Guantes de Cuero',
            'quantity': 1,
            'delivery_date': today.strftime('%Y-%m-%d'),
        })
        self.assertEqual(resp_forbidden.status_code, 403)

    # --------------------------------------------------------------------------
    # TEST 3: Regla Estricta Anti-Inversión de Mando en Permisos Laborales
    # --------------------------------------------------------------------------
    def test_leave_request_anti_command_inversion_rules(self):
        """
        Verifica:
        1. Técnico (20) solicita permiso -> Oficial SST (70) aprueba con éxito (HTTP 302).
        2. Coordinador (80) solicita vacaciones -> Oficial SST (70) intenta resolver
           y el servidor responde HTTP 403 (impidiendo que 70 mande sobre 80).
        3. Owner Admin (100) sí puede aprobar la solicitud del Coordinador (80).
        4. Oficial SST (70) solicita su propio permiso e intenta auto-aprobarlo -> HTTP 403.
        """
        today = timezone.now().date()
        next_week = today + timezone.timedelta(days=7)

        # CASO 1: Técnico (20) solicita permiso
        client_tech = self._get_client_for_user(self.user_tech)
        url_create = reverse('sst:leave_create')

        resp_t = client_tech.post(url_create, data={
            'leave_type': LeaveRequest.LeaveType.PERSONAL,
            'start_date': today.strftime('%Y-%m-%d'),
            'end_date': today.strftime('%Y-%m-%d'),
            'days_requested': 1,
            'reason': 'Trámites personales en Managua.',
        })
        self.assertEqual(resp_t.status_code, 302)

        leave_tech = LeaveRequest.objects.filter(requester=self.user_tech).first()
        self.assertIsNotNone(leave_tech)
        self.assertEqual(leave_tech.requester_role_level, RoleLevel.TECHNICIAN)

        # Oficial SST (70 > 20) aprueba con éxito
        client_sst = self._get_client_for_user(self.user_sst)
        url_review_t = reverse('sst:leave_review', kwargs={'pk': leave_tech.pk})
        resp_app_t = client_sst.post(url_review_t, data={'action': 'approve'})
        self.assertEqual(resp_app_t.status_code, 302)

        leave_tech.refresh_from_db()
        self.assertEqual(leave_tech.status, LeaveRequest.Status.APPROVED)
        self.assertEqual(leave_tech.reviewed_by, self.user_sst)

        # CASO 2: Coordinador Operativo (80) solicita vacaciones
        client_coord = self._get_client_for_user(self.user_ops_coord)
        resp_c = client_coord.post(url_create, data={
            'leave_type': LeaveRequest.LeaveType.VACATION,
            'start_date': today.strftime('%Y-%m-%d'),
            'end_date': next_week.strftime('%Y-%m-%d'),
            'days_requested': 5,
            'reason': 'Periodo semestral de vacaciones descansadas.',
        })
        self.assertEqual(resp_c.status_code, 302)

        leave_coord = LeaveRequest.objects.filter(requester=self.user_ops_coord).first()
        self.assertIsNotNone(leave_coord)
        self.assertEqual(leave_coord.requester_role_level, RoleLevel.OPERATIONS_COORD)

        # Oficial SST (70) intenta resolver solicitud del Coordinador (80) -> BLOQUEADO CON HTTP 403
        url_review_c = reverse('sst:leave_review', kwargs={'pk': leave_coord.pk})
        resp_inversion = client_sst.post(url_review_c, data={'action': 'approve'})
        self.assertEqual(resp_inversion.status_code, 403)

        leave_coord.refresh_from_db()
        self.assertEqual(leave_coord.status, LeaveRequest.Status.PENDING)

        # Owner Admin (100) resuelve exitosamente la solicitud del Coordinador
        client_owner = self._get_client_for_user(self.user_owner)
        resp_owner = client_owner.post(url_review_c, data={'action': 'approve'})
        self.assertEqual(resp_owner.status_code, 302)

        leave_coord.refresh_from_db()
        self.assertEqual(leave_coord.status, LeaveRequest.Status.APPROVED)
        self.assertEqual(leave_coord.reviewed_by, self.user_owner)

        # CASO 3: Oficial SST (70) solicita permiso propio e intenta auto-aprobarse -> HTTP 403
        resp_sst_req = client_sst.post(url_create, data={
            'leave_type': LeaveRequest.LeaveType.MEDICAL,
            'start_date': today.strftime('%Y-%m-%d'),
            'end_date': today.strftime('%Y-%m-%d'),
            'days_requested': 1,
            'reason': 'Cita médica periódica INSS.',
        })
        self.assertEqual(resp_sst_req.status_code, 302)

        leave_sst = LeaveRequest.objects.filter(requester=self.user_sst).first()
        self.assertIsNotNone(leave_sst)

        url_review_self = reverse('sst:leave_review', kwargs={'pk': leave_sst.pk})
        resp_self_approve = client_sst.post(url_review_self, data={'action': 'approve'})
        self.assertEqual(resp_self_approve.status_code, 403)

        leave_sst.refresh_from_db()
        self.assertEqual(leave_sst.status, LeaveRequest.Status.PENDING)

    # --------------------------------------------------------------------------
    # TEST 4: Segregación Estricta de Funciones en BOM Operativo
    # --------------------------------------------------------------------------
    def test_segregation_of_duties_sst_officer_cannot_execute_bom_items(self):
        """
        Verifica que el Oficial SST (70) tenga PROHIBIDO ejecutar partidas técnicas de ingeniería
        en WorkOrderItemExecuteView (recibe HTTP 403). Solo técnicos (20), ingenieros (50)
        y coordinadores (80) pueden reportar ejecución técnica.
        """
        wo = WorkOrder.objects.create(
            organization=self.org,
            account=self.account,
            title="Montaje de Banco de Transformadores",
            assigned_crew=self.crew,
            phase=WorkOrder.Phase.IN_PROGRESS,
        )

        item = WorkOrderItem.objects.create(
            organization=self.org,
            work_order=wo,
            code="SRV-TRAFO-01",
            description="Maniobra de izaje de transformador 500kVA",
            unit="UND",
            planned_quantity=Decimal('1.00'),
            executed_quantity=Decimal('0.00'),
        )

        # Oficial SST (70) intenta ejecutar la partida técnica del BOM
        client_sst = self._get_client_for_user(self.user_sst)
        url_execute = reverse('operations:workorder_item_execute', kwargs={
            'wo_pk': wo.pk,
            'item_pk': item.pk,
        })
        resp_sst = client_sst.post(url_execute, data={
            'executed_quantity': '1.00',
            'is_completed': '1',
        })
        # Debe recibir 403 Forbidden por segregación de funciones
        self.assertEqual(resp_sst.status_code, 403)

        item.refresh_from_db()
        self.assertEqual(item.executed_quantity, Decimal('0.00'))
        self.assertFalse(item.is_completed)

        # Técnico de Campo (20) ejecuta la partida técnica -> Exitoso
        client_tech = self._get_client_for_user(self.user_tech)
        resp_tech = client_tech.post(url_execute, data={
            'executed_quantity': '1.00',
            'is_completed': '1',
        })
        self.assertEqual(resp_tech.status_code, 302)

        item.refresh_from_db()
        self.assertEqual(item.executed_quantity, Decimal('1.00'))
        self.assertTrue(item.is_completed)
        self.assertEqual(item.completed_by, self.user_tech)

    # --------------------------------------------------------------------------
    # TEST 5: Aislamiento Multi-Tenant Estricto
    # --------------------------------------------------------------------------
    def test_sst_multi_tenant_isolation(self):
        """
        Verifica que los modelos SST de una organización no sean visibles por otra.
        """
        acc_intruder = Account.objects.create(
            organization=self.org_intruder,
            commercial_name="Empresa Competidora S.A.",
            tax_id="J0310000188888",
        )
        wo_intruder = WorkOrder.objects.create(
            organization=self.org_intruder,
            account=acc_intruder,
            title="OT Invasora",
        )
        chk_intruder = SafetyChecklist.objects.create(
            organization=self.org_intruder,
            work_order=wo_intruder,
            submitted_by=self.user_owner,
            work_type=SafetyChecklist.WorkType.GENERAL,
        )

        # Consultar por self.org nunca retorna el checklist de la organización invasora
        my_checklists = SafetyChecklist.objects.for_org(self.org)
        self.assertNotIn(chk_intruder, my_checklists)

        # Intentar revisar checklist invasor con Oficial SST de self.org -> 404
        client_sst = self._get_client_for_user(self.user_sst, org=self.org)
        url_review = reverse('sst:checklist_review', kwargs={'pk': chk_intruder.pk})
        resp = client_sst.post(url_review, data={'action': 'approve'})
        self.assertEqual(resp.status_code, 404)
