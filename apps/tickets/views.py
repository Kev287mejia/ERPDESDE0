from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.tenancy.models import RoleLevel
from apps.tenancy.permissions import ModuleAccessRequiredMixin, render_403_rbac
from .forms import (
    SupportTicketCreateForm,
    TicketCommentForm,
    TicketResolveForm,
)
from .models import SupportTicket, TicketComment


class TicketListView(ModuleAccessRequiredMixin, TemplateView):
    """
    Bandeja de Mesa de Ayuda y Soporte Técnico Operativo.
    Aislamiento RBAC:
    - Técnicos (20) e Ingenieros (50) consultan únicamente tickets reportados por ellos o asignados a ellos.
    - Oficiales SST (70), Coordinadores (80), Gerentes (85) y Administradores (100) gestionan la cola completa.
    """
    template_name = 'tickets/ticket_list.html'
    required_module = 'tickets'
    min_role_level = RoleLevel.TECHNICIAN

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        role_level = getattr(self.request, 'role_level', 0)
        user = self.request.user

        # 1. Filtro base de visibilidad según jerarquía RBAC
        base_qs = SupportTicket.objects.for_org(org).select_related(
            'reported_by', 'assigned_to', 'related_work_order'
        )

        if role_level <= RoleLevel.ENGINEER:
            tickets_qs = base_qs.filter(Q(reported_by=user) | Q(assigned_to=user))
        else:
            tickets_qs = base_qs

        # Filtros opcionales por GET
        status_filter = self.request.GET.get('status')
        priority_filter = self.request.GET.get('priority')
        category_filter = self.request.GET.get('category')

        if status_filter:
            tickets_qs = tickets_qs.filter(status=status_filter)
        if priority_filter:
            tickets_qs = tickets_qs.filter(priority=priority_filter)
        if category_filter:
            tickets_qs = tickets_qs.filter(category=category_filter)

        tickets = list(tickets_qs.order_by('-created_at'))

        # 2. Métricas y KPIs de SLA de la organización
        all_org_tickets = list(base_qs)
        open_tickets = [t for t in all_org_tickets if t.status in [SupportTicket.Status.OPEN, SupportTicket.Status.IN_PROGRESS]]
        critical_open = [t for t in open_tickets if t.priority == SupportTicket.Priority.CRITICAL]
        breached_tickets = [t for t in open_tickets if t.sla_status == 'BREACHED']
        resolved_tickets = [t for t in all_org_tickets if t.status in [SupportTicket.Status.RESOLVED, SupportTicket.Status.CLOSED]]

        context.update({
            'tickets': tickets,
            'total_tickets_count': len(tickets),
            'kpi_open': len(open_tickets),
            'kpi_critical': len(critical_open),
            'kpi_breached': len(breached_tickets),
            'kpi_resolved': len(resolved_tickets),
            'ticket_form': SupportTicketCreateForm(organization=org),
            'can_resolve_global': role_level >= RoleLevel.SST_OFFICER,
            'is_field_staff': role_level <= RoleLevel.ENGINEER,
            'selected_status': status_filter,
            'selected_priority': priority_filter,
            'selected_category': category_filter,
        })
        return context


class TicketCreateView(ModuleAccessRequiredMixin, View):
    """
    Apertura de Incidente Interno o Requerimiento de Soporte de Campo.
    Accesible para todos los colaboradores desde Nivel 20 (TECHNICIAN).
    """
    required_module = 'tickets'
    min_role_level = RoleLevel.TECHNICIAN

    def post(self, request):
        form = SupportTicketCreateForm(request.POST, organization=request.organization)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.organization = request.organization
            ticket.reported_by = request.user
            ticket.save()
            messages.success(
                request,
                f"Ticket '{ticket.number}' aperturado exitosamente. Compromiso SLA: {ticket.sla_hours} horas."
            )
            return redirect('tickets:ticket_detail', pk=ticket.pk)
        else:
            messages.error(request, "Error al aperturar ticket. Verifique los campos obligatorios.")
            return redirect('tickets:ticket_list')


class TicketDetailView(ModuleAccessRequiredMixin, TemplateView):
    """
    Ficha de Detalle de Incidente, Semáforo de SLA y Bitácora de Comentarios.
    Valida segregación RBAC: Técnicos e Ingenieros solo ven los suyos.
    """
    template_name = 'tickets/ticket_detail.html'
    required_module = 'tickets'
    min_role_level = RoleLevel.TECHNICIAN

    def get(self, request, pk, *args, **kwargs):
        org = request.organization
        role_level = getattr(request, 'role_level', 0)
        ticket = get_object_or_404(
            SupportTicket.objects.for_org(org).select_related(
                'reported_by', 'assigned_to', 'related_work_order'
            ),
            pk=pk
        )

        # Regla de Aislamiento para personal operativo
        if role_level <= RoleLevel.ENGINEER:
            if ticket.reported_by_id != request.user.id and ticket.assigned_to_id != request.user.id:
                return render_403_rbac(
                    request,
                    required_module='tickets',
                    min_role_level=RoleLevel.SST_OFFICER,
                    reason="Solo puede consultar tickets reportados por usted o asignados a su persona."
                )

        comments = ticket.comments.all().select_related('author').order_by('created_at')
        can_resolve = role_level >= RoleLevel.SST_OFFICER

        return render(request, self.template_name, {
            'ticket': ticket,
            'comments': comments,
            'can_resolve': can_resolve,
            'comment_form': TicketCommentForm(),
            'resolve_form': TicketResolveForm(instance=ticket) if can_resolve else None,
        })


class TicketCommentCreateView(ModuleAccessRequiredMixin, View):
    """
    Agrega una nota técnica o comentario de seguimiento en el ticket.
    """
    required_module = 'tickets'
    min_role_level = RoleLevel.TECHNICIAN

    def post(self, request, pk):
        org = request.organization
        role_level = getattr(request, 'role_level', 0)
        ticket = get_object_or_404(SupportTicket.objects.for_org(org), pk=pk)

        if role_level <= RoleLevel.ENGINEER:
            if ticket.reported_by_id != request.user.id and ticket.assigned_to_id != request.user.id:
                return render_403_rbac(
                    request,
                    required_module='tickets',
                    min_role_level=RoleLevel.SST_OFFICER,
                    reason="No tiene autorización para interactuar en este ticket ajeno."
                )

        form = TicketCommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.organization = org
            comment.ticket = ticket
            comment.author = request.user
            comment.save()
            messages.success(request, "Comentario técnico registrado exitosamente.")
        else:
            messages.error(request, "El mensaje no puede estar vacío.")

        return redirect('tickets:ticket_detail', pk=ticket.pk)


class TicketResolveView(ModuleAccessRequiredMixin, View):
    """
    Dictamen y Resolución de Ticket con Control de SLA.
    Exige Nivel 70 (SST_OFFICER) o superior (Coordinador / Admin).
    Los Técnicos (20) o Ingenieros (50) reciben 403 Forbidden.
    """
    required_module = 'tickets'
    min_role_level = RoleLevel.SST_OFFICER

    def post(self, request, pk):
        org = request.organization
        ticket = get_object_or_404(SupportTicket.objects.for_org(org), pk=pk)
        form = TicketResolveForm(request.POST, instance=ticket)

        if form.is_valid():
            ticket = form.save(commit=False)
            if not ticket.resolved_at:
                ticket.resolved_at = timezone.now()
            ticket.save(update_fields=['status', 'resolution_summary', 'resolved_at', 'updated_at'])
            messages.success(
                request,
                f"Ticket '{ticket.number}' actualizado a estado {ticket.get_status_display()}."
            )
        else:
            messages.error(request, "Error al actualizar estado del ticket.")

        return redirect('tickets:ticket_detail', pk=ticket.pk)
