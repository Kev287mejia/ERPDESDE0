import datetime
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views import View

from apps.core.services.alerts_engine import get_active_alerts_for_user
from apps.tenancy.models import CorporateEvent, RoleLevel
from apps.tenancy.permissions import RoleLevelRequiredMixin


class AlertsRadarCenterView(RoleLevelRequiredMixin, View):
    """
    Consola y Radar de Alertas Proactivas Multi-Giro en Tiempo Real.
    Visualiza hallazgos críticos y advertencias operativas según el nivel jerárquico del usuario.
    Accesible para todos los colaboradores desde Nivel 20 (Técnico de Campo).
    """
    min_role_level = RoleLevel.TECHNICIAN
    template_name = 'core/alerts_radar.html'

    def get(self, request, *args, **kwargs):
        org = request.organization
        role_level = getattr(request, 'role_level', 0)

        alerts_data = get_active_alerts_for_user(org, request.user, role_level)
        all_alerts = alerts_data['alerts']
        counts = alerts_data['counts']

        # Filtros de visualización
        selected_category = request.GET.get('category', 'ALL').strip()
        selected_severity = request.GET.get('severity', 'ALL').strip()

        filtered_alerts = all_alerts
        if selected_category and selected_category != 'ALL':
            filtered_alerts = [a for a in filtered_alerts if a['category'] == selected_category]
        if selected_severity and selected_severity != 'ALL':
            filtered_alerts = [a for a in filtered_alerts if a['severity'] == selected_severity]

        categories_choices = [
            ('ALL', 'Todas las Alertas'),
            ('INVENTORY_FEFO', 'Almacén & Lotes FEFO'),
            ('OPERATIONS_SST', 'Operaciones & SST'),
            ('FINANCE_DGI', 'Finanzas, Cartera & DGI'),
        ]

        severities_choices = [
            ('ALL', 'Todas las Severidades'),
            ('CRITICAL', 'Críticas'),
            ('HIGH', 'Altas'),
        ]

        context = {
            'alerts': filtered_alerts,
            'counts': counts,
            'selected_category': selected_category,
            'selected_severity': selected_severity,
            'categories_choices': categories_choices,
            'severities_choices': severities_choices,
            'can_view_finance': role_level >= RoleLevel.OPERATIONS_COORD,
            'can_view_inventory': role_level >= RoleLevel.ENGINEER,
        }
        return render(request, self.template_name, context)


class TopbarAlertsDropdownPartialView(RoleLevelRequiredMixin, View):
    """
    Fragmento Parcial HTMX para el Menú Desplegable de la Campana de Alertas en Topbar.
    Retorna las primeras 8 alertas prioritarias para interacción rápida sin recarga de página.
    """
    min_role_level = RoleLevel.TECHNICIAN
    template_name = 'core/partials/topbar_alerts_dropdown.html'

    def get(self, request, *args, **kwargs):
        org = request.organization
        role_level = getattr(request, 'role_level', 0)

        alerts_data = get_active_alerts_for_user(org, request.user, role_level)
        top_alerts = alerts_data['alerts'][:8]

        context = {
            'alerts': top_alerts,
            'counts': alerts_data['counts'],
        }
        return render(request, self.template_name, context)


class CorporateAgendaView(RoleLevelRequiredMixin, View):
    """
    Agenda Corporativa Unificada & Calendario de Hitos Fiscales/Operativos.
    Filtra los eventos según el nivel de autoridad jerárquico:
    - role_level >= 80: Visualiza vencimientos tributarios (DGI/Alcaldía/INSS) y visitas comerciales.
    - role_level == 20: Técnicos visualizan únicamente eventos asignados a su persona o públicos de campo.
    """
    min_role_level = RoleLevel.TECHNICIAN
    template_name = 'core/corporate_agenda.html'

    def get(self, request, *args, **kwargs):
        org = request.organization
        role_level = getattr(request, 'role_level', 0)
        now = timezone.now()

        # Filtro base de confidencialidad jerárquica
        qs = (
            CorporateEvent.objects.for_org(org)
            .filter(min_role_level__lte=role_level)
            .select_related('related_account', 'related_work_order', 'assigned_to', 'created_by')
        )

        # Regla especial de confidencialidad de campo para técnicos (20)
        if role_level == RoleLevel.TECHNICIAN:
            from django.db.models import Q
            qs = qs.filter(
                Q(assigned_to=request.user) |
                Q(related_work_order__assigned_engineer=request.user) |
                Q(related_work_order__assigned_crew__leader=request.user) |
                (Q(min_role_level__lte=RoleLevel.TECHNICIAN) & Q(assigned_to__isnull=True))
            )

        # Filtros de búsqueda y estado
        selected_type = request.GET.get('event_type', '').strip()
        selected_status = request.GET.get('status', '').strip()
        search_q = request.GET.get('q', '').strip()

        if selected_type:
            qs = qs.filter(event_type=selected_type)
        if selected_status:
            qs = qs.filter(status=selected_status)
        if search_q:
            qs = qs.filter(title__icontains=search_q)

        events_list = list(qs.order_by('start_datetime'))

        # Clasificación en Programados vs. Concluidos
        upcoming_events = [e for e in events_list if e.status == CorporateEvent.Status.SCHEDULED]
        completed_events = [e for e in events_list if e.status in (CorporateEvent.Status.COMPLETED, CorporateEvent.Status.CANCELLED)]

        can_create_event = (role_level >= RoleLevel.ENGINEER)
        can_generate_fiscal = (role_level >= RoleLevel.COMMERCIAL_MGR)

        accounts = []
        if org.is_module_enabled('crm'):
            from apps.crm.models import Account
            accounts = Account.objects.for_org(org).order_by('commercial_name')[:50]

        work_orders = []
        if org.is_module_enabled('operations'):
            from apps.operations.models import WorkOrder
            work_orders = WorkOrder.objects.for_org(org).order_by('-created_at')[:50]

        from django.contrib.auth import get_user_model
        User = get_user_model()
        users = User.objects.filter(memberships__organization=org).order_by('email')

        context = {
            'events': events_list,
            'upcoming_events': upcoming_events,
            'completed_events': completed_events,
            'selected_type': selected_type,
            'selected_status': selected_status,
            'search_q': search_q,
            'event_types': CorporateEvent.EventType.choices,
            'statuses': CorporateEvent.Status.choices,
            'priorities': CorporateEvent.Priority.choices,
            'role_choices': RoleLevel.choices,
            'accounts': accounts,
            'work_orders': work_orders,
            'users': users,
            'can_create_event': can_create_event,
            'can_generate_fiscal': can_generate_fiscal,
            'current_month_name': now.strftime('%B %Y'),
            'current_role_level': role_level,
        }
        return render(request, self.template_name, context)


class CorporateEventCreateView(RoleLevelRequiredMixin, View):
    """
    Creación Manual de Eventos y Compromisos en la Agenda.
    Requiere nivel mínimo ENGINEER (50+).
    """
    min_role_level = RoleLevel.ENGINEER

    def post(self, request, *args, **kwargs):
        org = request.organization
        title = request.POST.get('title', '').strip()
        event_type = request.POST.get('event_type', CorporateEvent.EventType.TECHNICAL_MAINTENANCE)
        priority = request.POST.get('priority', CorporateEvent.Priority.NORMAL)
        start_str = request.POST.get('start_datetime', '').strip()
        end_str = request.POST.get('end_datetime', '').strip()
        location = request.POST.get('location', '').strip()
        description = request.POST.get('description', '').strip()
        min_role_str = request.POST.get('min_role_level', str(RoleLevel.ENGINEER)).strip()
        related_wo_id = request.POST.get('related_work_order', '').strip()
        related_acc_id = request.POST.get('related_account', '').strip()
        assigned_to_id = request.POST.get('assigned_to', '').strip()

        if not title or not start_str:
            messages.error(request, "El título y la fecha/hora de inicio son obligatorios.")
            return redirect('corporate_agenda')

        try:
            start_dt = parse_datetime(start_str)
            if start_dt and timezone.is_naive(start_dt):
                start_dt = timezone.make_aware(start_dt)
            elif not start_dt:
                start_dt = timezone.now()

            end_dt = parse_datetime(end_str) if end_str else None
            if end_dt and timezone.is_naive(end_dt):
                end_dt = timezone.make_aware(end_dt)

            min_role = int(min_role_str) if min_role_str.isdigit() else RoleLevel.ENGINEER

            event = CorporateEvent(
                organization=org,
                title=title,
                event_type=event_type,
                priority=priority,
                status=CorporateEvent.Status.SCHEDULED,
                start_datetime=start_dt,
                end_datetime=end_dt,
                location=location,
                description=description,
                min_role_level=min_role,
                created_by=request.user,
            )
            if assigned_to_id:
                event.assigned_to_id = assigned_to_id
            if related_wo_id:
                event.related_work_order_id = related_wo_id
            if related_acc_id:
                event.related_account_id = related_acc_id

            event.save()
            messages.success(request, f"Evento {event.code} ({event.title}) programado exitosamente.")
        except Exception as e:
            messages.error(request, f"Error al crear evento: {str(e)}")

        return redirect('corporate_agenda')


class CorporateEventStatusUpdateView(RoleLevelRequiredMixin, View):
    """
    Actualización de Estado de un Evento (Completado / Cancelado).
    Requiere nivel mínimo ENGINEER (50+).
    """
    min_role_level = RoleLevel.ENGINEER

    def post(self, request, pk, *args, **kwargs):
        org = request.organization
        event = get_object_or_404(CorporateEvent, pk=pk, organization=org)
        new_status = request.POST.get('status', '').strip()

        if new_status in CorporateEvent.Status.values:
            event.status = new_status
            event.save(update_fields=['status', 'updated_at'])
            messages.success(request, f"Evento {event.code} marcado como {event.get_status_display()}.")
        else:
            messages.error(request, "Estado no válido.")

        return redirect('corporate_agenda')


class GenerateFiscalCalendarView(RoleLevelRequiredMixin, View):
    """
    Generador Automático e Idempotente del Calendario Fiscal DGI / Alcaldía / INSS del Mes.
    Exclusivo para Gerencia Comercial y Propietario (RoleLevel >= 85).

    Crea los 3 hitos de ley nicaragüense para el mes en curso:
    - Día 05: Declaración y Pago Retenciones en la Fuente e IVA Mensual (VET-DGI Ley 822)
    - Día 15: Declaración y Pago Impuesto Municipal sobre Ingresos (IMI Alcaldía de Managua)
    - Día 20: Pago de Facturación y Planilla Mensual INSS / INATEC
    """
    min_role_level = RoleLevel.COMMERCIAL_MGR

    def post(self, request, *args, **kwargs):
        org = request.organization
        now = timezone.now()
        year = now.year
        month = now.month

        # Fechas de corte tributario en Nicaragua
        day_05 = timezone.make_aware(datetime.datetime(year, month, 5, 9, 0, 0))
        day_15 = timezone.make_aware(datetime.datetime(year, month, 15, 9, 0, 0))
        day_20 = timezone.make_aware(datetime.datetime(year, month, 20, 9, 0, 0))

        milestones = [
            {
                'title': 'Declaración y Pago de Retenciones en la Fuente e IVA Mensual (VET-DGI Ley 822)',
                'date': day_05,
                'priority': CorporateEvent.Priority.CRITICAL,
                'location': 'Ventanilla Electrónica Tributaria (VET - DGI)',
                'description': (
                    'Fecha límite legal para declarar y enterar las retenciones en la fuente '
                    'practicadas a proveedores (IR 1%-2% e IMI 1%) y la liquidación mensual de IVA Débito Fiscal.'
                ),
            },
            {
                'title': 'Declaración y Pago de Impuesto Municipal sobre Ingresos (IMI Alcaldía)',
                'date': day_15,
                'priority': CorporateEvent.Priority.HIGH,
                'location': 'Alcaldía Municipal de Managua / Dirección de Recaudación',
                'description': (
                    'Fecha de entero del 1.00% de Impuesto Municipal sobre Ingresos (IMI) '
                    'correspondiente a la facturación comercial del mes anterior.'
                ),
            },
            {
                'title': 'Pago de Facturación y Planilla Mensual INSS / INATEC',
                'date': day_20,
                'priority': CorporateEvent.Priority.HIGH,
                'location': 'Portal de Servicios Electrónicos INSS',
                'description': (
                    'Vencimiento de la factura de cotizaciones de la seguridad social laboral y patronal '
                    '(INSS 21.5% patronal / 7% laboral + 2% INATEC).'
                ),
            },
        ]

        created_count = 0
        for m in milestones:
            existing = CorporateEvent.objects.filter(
                organization=org,
                event_type=CorporateEvent.EventType.TAX_DEADLINE,
                start_datetime__date=m['date'].date(),
                title=m['title'],
            ).first()

            if not existing:
                CorporateEvent.objects.create(
                    organization=org,
                    title=m['title'],
                    event_type=CorporateEvent.EventType.TAX_DEADLINE,
                    priority=m['priority'],
                    status=CorporateEvent.Status.SCHEDULED,
                    start_datetime=m['date'],
                    end_datetime=m['date'] + datetime.timedelta(hours=8),
                    location=m['location'],
                    description=m['description'],
                    min_role_level=RoleLevel.OPERATIONS_COORD,  # Confidencialidad fiscal
                    created_by=request.user,
                )
                created_count += 1

        if created_count > 0:
            messages.success(
                request,
                f"Calendario Fiscal DGI/Alcaldía/INSS generado exitosamente: {created_count} hitos tributarios programados."
            )
        else:
            messages.info(
                request,
                "Los hitos del Calendario Fiscal del mes en curso ya se encuentran programados y vigentes."
            )

        return redirect('corporate_agenda')
