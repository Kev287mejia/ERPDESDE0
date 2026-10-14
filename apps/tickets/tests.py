import datetime
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import CountryConfig
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel
from apps.tickets.models import SupportTicket, TicketComment

User = get_user_model()


class TicketsTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        self.country = CountryConfig.objects.create(
            code='NI',
            name='Nicaragua',
            primary_currency_code='NIO',
            primary_currency_symbol='C$',
            is_active=True,
        )

        self.org = Organization.objects.create(
            name='SERMANSA Engineering Org',
            tax_id='J0310000000018',
            country=self.country,
            currency='NIO',
            enabled_modules=['tickets'],
            onboarding_completed=True,
        )

        # 1. Coordinador de Operaciones (80)
        self.ops_coord = User.objects.create_user(
            email='mfonseca@sermansa.ni',
            password='Password123*',
            full_name='Ing. Marcos Fonseca'
        )
        OrganizationMembership.objects.create(
            user=self.ops_coord,
            organization=self.org,
            role_level=RoleLevel.OPERATIONS_COORD,
            is_active=True,
        )

        # 2. Técnico 1: Carlos Ruiz (20)
        self.tech_carlos = User.objects.create_user(
            email='cruiz@sermansa.ni',
            password='Password123*',
            full_name='Téc. Carlos Ruiz'
        )
        OrganizationMembership.objects.create(
            user=self.tech_carlos,
            organization=self.org,
            role_level=RoleLevel.TECHNICIAN,
            is_active=True,
        )

        # 3. Técnico 2: Josué Espinoza (20)
        self.tech_josue = User.objects.create_user(
            email='jespinoza@sermansa.ni',
            password='Password123*',
            full_name='Téc. Josué Espinoza'
        )
        OrganizationMembership.objects.create(
            user=self.tech_josue,
            organization=self.org,
            role_level=RoleLevel.TECHNICIAN,
            is_active=True,
        )

    def test_sla_hours_and_due_date_calculation_by_priority(self):
        """
        Verifica que al crear un ticket se asignen automáticamente las horas de SLA:
        - CRITICAL -> 4h
        - HIGH -> 12h
        - NORMAL -> 24h
        - LOW -> 72h
        """
        tck_critical = SupportTicket.objects.create(
            organization=self.org,
            title='Falla de frenos camioneta Hilux M 345-890',
            category=SupportTicket.Category.VEHICLE_FLEET,
            priority=SupportTicket.Priority.CRITICAL,
            reported_by=self.tech_carlos,
            description='Frenos sin presión.',
        )
        self.assertEqual(tck_critical.sla_hours, 4)
        self.assertIsNotNone(tck_critical.sla_due_at)
        self.assertTrue(tck_critical.number.startswith('TCK-'))
        self.assertEqual(tck_critical.sla_status, 'ON_TIME')

        tck_high = SupportTicket.objects.create(
            organization=self.org,
            title='Falla en taladro rotomartillo',
            category=SupportTicket.Category.TOOL_EQUIPMENT,
            priority=SupportTicket.Priority.HIGH,
            reported_by=self.tech_carlos,
            description='Mandril trabado.',
        )
        self.assertEqual(tck_high.sla_hours, 12)

        tck_normal = SupportTicket.objects.create(
            organization=self.org,
            title='Solicitud de viáticos',
            category=SupportTicket.Category.ADMIN_REQ,
            priority=SupportTicket.Priority.NORMAL,
            reported_by=self.tech_carlos,
            description='Viáticos gira Chinandega.',
        )
        self.assertEqual(tck_normal.sla_hours, 24)

        tck_low = SupportTicket.objects.create(
            organization=self.org,
            title='Actualización de software',
            category=SupportTicket.Category.IT_SYSTEM,
            priority=SupportTicket.Priority.LOW,
            reported_by=self.tech_carlos,
            description='Instalación de visor CAD.',
        )
        self.assertEqual(tck_low.sla_hours, 72)

    def test_sla_status_properties(self):
        """
        Verifica los tres estados del semáforo de SLA: ON_TIME, BREACHED y COMPLETED.
        """
        now = timezone.now()
        tck = SupportTicket.objects.create(
            organization=self.org,
            title='Prueba SLA',
            priority=SupportTicket.Priority.CRITICAL,
            reported_by=self.tech_carlos,
            description='Test',
        )
        self.assertEqual(tck.sla_status, 'ON_TIME')

        # Vencido
        tck.sla_due_at = now - datetime.timedelta(hours=1)
        tck.save(update_fields=['sla_due_at'])
        self.assertEqual(tck.sla_status, 'BREACHED')

        # Resuelto
        tck.status = SupportTicket.Status.RESOLVED
        tck.save(update_fields=['status'])
        self.assertEqual(tck.sla_status, 'COMPLETED')

    def test_technician_creation_and_comment_flow(self):
        """
        El Técnico (20) puede crear el ticket y comentarlo en el suyo propio.
        """
        self.client.force_login(self.tech_carlos)

        # 1. Crear Ticket
        create_url = reverse('tickets:ticket_create')
        res_create = self.client.post(create_url, {
            'title': 'Avería en camioneta Hilux M 345-890',
            'category': SupportTicket.Category.VEHICLE_FLEET,
            'priority': SupportTicket.Priority.CRITICAL,
            'description': 'Pérdida de líquido de frenos.',
        })
        self.assertEqual(res_create.status_code, 302)

        ticket = SupportTicket.objects.get(title='Avería en camioneta Hilux M 345-890')
        self.assertEqual(ticket.reported_by, self.tech_carlos)
        self.assertEqual(ticket.sla_hours, 4)

        # 2. Agregar Comentario en su ticket
        comment_url = reverse('tickets:ticket_comment_create', kwargs={'pk': ticket.pk})
        res_comment = self.client.post(comment_url, {
            'message': 'Unidad estacionada en patio trasero.',
        })
        self.assertEqual(res_comment.status_code, 302)
        self.assertEqual(ticket.comments.count(), 1)
        self.assertEqual(ticket.comments.first().author, self.tech_carlos)

    def test_technician_rbac_isolation_from_other_tickets(self):
        """
        El Técnico Josué (20) NO ve ni puede comentar en un ticket ajeno reportado por Carlos (20).
        """
        ticket_carlos = SupportTicket.objects.create(
            organization=self.org,
            title='Ticket privado de Carlos',
            priority=SupportTicket.Priority.HIGH,
            reported_by=self.tech_carlos,
            description='Descripción privada.',
        )

        # Josué intenta consultar el ticket de Carlos -> 403 Forbidden
        self.client.force_login(self.tech_josue)
        res_detail = self.client.get(reverse('tickets:ticket_detail', kwargs={'pk': ticket_carlos.pk}))
        self.assertEqual(res_detail.status_code, 403)

        # Josué intenta comentar en el ticket de Carlos -> 403 Forbidden
        res_comment = self.client.post(reverse('tickets:ticket_comment_create', kwargs={'pk': ticket_carlos.pk}), {
            'message': 'Intrusión no autorizada',
        })
        self.assertEqual(res_comment.status_code, 403)
        self.assertEqual(ticket_carlos.comments.count(), 0)

    def test_resolution_rbac_permissions(self):
        """
        El Técnico (20) recibe HTTP 403 si intenta cerrar o resolver un ticket;
        el Coordinador (80) lo resuelve exitosamente.
        """
        ticket = SupportTicket.objects.create(
            organization=self.org,
            title='Revisión de multímetro',
            priority=SupportTicket.Priority.NORMAL,
            reported_by=self.tech_carlos,
            description='Calibración pendiente.',
        )

        resolve_url = reverse('tickets:ticket_resolve', kwargs={'pk': ticket.pk})

        # 1. Técnico intenta resolver ticket -> 403 Forbidden
        self.client.force_login(self.tech_carlos)
        res_tech_resolve = self.client.post(resolve_url, {
            'status': SupportTicket.Status.RESOLVED,
            'resolution_summary': 'Intento de resolución por técnico',
        })
        self.assertEqual(res_tech_resolve.status_code, 403)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, SupportTicket.Status.OPEN)

        # 2. Coordinador de Operaciones (80) resuelve el ticket -> 302 Redirect & Status RESOLVED
        self.client.force_login(self.ops_coord)
        res_coord_resolve = self.client.post(resolve_url, {
            'status': SupportTicket.Status.RESOLVED,
            'resolution_summary': 'Equipo calibrado con patrón trazable de laboratorio. Certificado archivado.',
        })
        self.assertEqual(res_coord_resolve.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, SupportTicket.Status.RESOLVED)
        self.assertIsNotNone(ticket.resolved_at)
        self.assertEqual(ticket.sla_status, 'COMPLETED')
