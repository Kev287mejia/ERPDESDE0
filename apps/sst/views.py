from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.tenancy.models import RoleLevel
from apps.tenancy.permissions import ModuleAccessRequiredMixin, render_403_rbac
from apps.operations.models import WorkOrder, WorkOrderTimelineLog
from apps.sst.models import SafetyChecklist, EPPDelivery, LeaveRequest
from apps.sst.forms import SafetyChecklistForm, EPPDeliveryForm, LeaveRequestForm


class SSTDashboardAndChecklistsView(ModuleAccessRequiredMixin, TemplateView):
    """
    Consola Técnica de Checklists Pre-Operacionales y Dotación EPP.
    - Técnicos (20): Visualizan sus propios checklists y dotación EPP asignada.
    - Oficiales SST / Ingenieros / Coordinadores (50+ / 70+): Visualizan toda la dotación
      y controles pre-operacionales de la organización activa.
    """
    template_name = 'sst/checklists_and_epp.html'
    required_module = 'sst'
    min_role_level = RoleLevel.TECHNICIAN

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        user = self.request.user
        role_level = getattr(self.request, 'role_level', 0)
        is_field_tech = (role_level == RoleLevel.TECHNICIAN)

        # 1. Queryset de Checklists Pre-Operacionales
        if is_field_tech:
            checklists = SafetyChecklist.objects.for_org(org).filter(
                Q(submitted_by=user) | Q(crew__members=user) | Q(crew__leader=user)
            ).distinct().select_related('work_order', 'crew', 'submitted_by', 'reviewed_by')
        else:
            checklists = SafetyChecklist.objects.for_org(org).select_related(
                'work_order', 'crew', 'submitted_by', 'reviewed_by'
            )

        # 2. Queryset de Dotaciones EPP
        if is_field_tech:
            epps = EPPDelivery.objects.for_org(org).filter(
                collaborator=user
            ).select_related('collaborator', 'delivered_by')
        else:
            epps = EPPDelivery.objects.for_org(org).select_related(
                'collaborator', 'delivered_by'
            )

        # 3. Métricas y KPIs SST
        all_checklists = SafetyChecklist.objects.for_org(org)
        all_epps = EPPDelivery.objects.for_org(org)
        all_ots = WorkOrder.objects.for_org(org)

        today = timezone.now().date()
        in_30_days = today + timezone.timedelta(days=30)

        context.update({
            'checklists': checklists[:50],
            'epps': epps[:50],
            'is_field_tech': is_field_tech,
            'can_manage_sst': role_level >= RoleLevel.SST_OFFICER,
            'pending_checklists_count': all_checklists.filter(status=SafetyChecklist.Status.PENDING).count(),
            'cleared_high_risk_ots_count': all_ots.filter(is_high_risk=True, sst_cleared=True).count(),
            'active_epp_count': all_epps.filter(status=EPPDelivery.Status.ACTIVE).count(),
            'expiring_epp_count': all_epps.filter(
                status=EPPDelivery.Status.ACTIVE,
                expiration_date__isnull=False,
                expiration_date__lte=in_30_days,
            ).count(),
            'checklist_form': SafetyChecklistForm(organization=org),
            'epp_form': EPPDeliveryForm(organization=org) if role_level >= RoleLevel.SST_OFFICER else None,
        })
        return context


class SafetyChecklistCreateView(ModuleAccessRequiredMixin, View):
    """
    Registro en campo de Lista de Chequeo Pre-Operacional vinculada a una OT.
    Accesible para Técnicos (20), Ingenieros (50) y superiores.
    """
    required_module = 'sst'
    min_role_level = RoleLevel.TECHNICIAN

    @transaction.atomic
    def post(self, request):
        org = request.organization
        form = SafetyChecklistForm(request.POST, organization=org)

        if form.is_valid():
            chk = form.save(commit=False)
            chk.organization = org
            chk.submitted_by = request.user
            chk.save()

            # Registro de auditoría en la OT vinculada
            WorkOrderTimelineLog.objects.create(
                organization=org,
                work_order=chk.work_order,
                event_type='SST_CHECKLIST_SUBMITTED',
                summary=f"Checklist Pre-Operacional {chk.number} presentado ({chk.get_work_type_display()})",
                details=(
                    f"Presentado por {request.user.full_name}. "
                    f"Verificaciones de seguridad: {'Cumplidas (5/5)' if chk.all_checks_passed() else 'Incompletas / Con hallazgos'}. "
                    f"Condiciones: {chk.hazard_notes or 'Ninguna novedad reportada.'}"
                ),
                actor=request.user,
            )

            messages.success(request, f"Checklist Pre-Operacional {chk.number} registrado con éxito.")
            # Redirigir de regreso a la OT si vino desde su consola técnica
            next_url = request.POST.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('sst:checklists_and_epp')
        else:
            messages.error(request, "Error al registrar checklist pre-operacional. Verifique los campos obligatorios.")
            return redirect('sst:checklists_and_epp')


class SafetyChecklistReviewView(ModuleAccessRequiredMixin, View):
    """
    Dictamen y Validación de Checklist Pre-Operacional por Oficial SST.
    Exige min_role_level = RoleLevel.SST_OFFICER (70).
    Efecto colateral: si se aprueba, otorga liberación SST (sst_cleared=True) a la OT vinculada.
    """
    required_module = 'sst'
    min_role_level = RoleLevel.SST_OFFICER

    @transaction.atomic
    def post(self, request, pk):
        org = request.organization
        chk = get_object_or_404(SafetyChecklist.objects.for_org(org), pk=pk)
        action = request.POST.get('action')
        comments = request.POST.get('review_comments', '').strip()

        if action not in ['approve', 'reject']:
            messages.error(request, "Acción de validación SST no válida.")
            return redirect('sst:checklists_and_epp')

        chk.reviewed_by = request.user
        chk.reviewed_at = timezone.now()
        chk.review_comments = comments

        if action == 'approve':
            chk.status = SafetyChecklist.Status.APPROVED
            chk.save()

            # Actualizar OT vinculada
            wo = chk.work_order
            wo.sst_cleared = True
            wo.save(update_fields=['sst_cleared', 'updated_at'])

            # Bitácora inmutable en la OT
            WorkOrderTimelineLog.objects.create(
                organization=org,
                work_order=wo,
                event_type='SST_CLEARANCE',
                summary=f"Liberación SST Otorgada mediante Checklist {chk.number}",
                details=(
                    f"Checklist pre-operacional ({chk.get_work_type_display()}) verificado y aprobado "
                    f"por el Oficial SST {request.user.full_name}. Cuadrilla autorizada para campo."
                ),
                actor=request.user,
            )
            messages.success(request, f"Checklist {chk.number} aprobado. Se liberó la OT {wo.number} para labores de campo.")

        elif action == 'reject':
            chk.status = SafetyChecklist.Status.REJECTED
            chk.save()

            wo = chk.work_order
            wo.sst_cleared = False
            wo.save(update_fields=['sst_cleared', 'updated_at'])

            WorkOrderTimelineLog.objects.create(
                organization=org,
                work_order=wo,
                event_type='SST_REJECTED',
                summary=f"Checklist {chk.number} Rechazado por SST — Detención de Labor",
                details=(
                    f"Dictamen de no conformidad emitido por {request.user.full_name}. "
                    f"Motivo: {comments or 'Condiciones no seguras en sitio.'}"
                ),
                actor=request.user,
            )
            messages.warning(request, f"Checklist {chk.number} rechazado. OT {wo.number} bloqueada preventivamente para campo.")

        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
        return redirect('sst:checklists_and_epp')


class EPPDeliveryCreateView(ModuleAccessRequiredMixin, View):
    """
    Registro y Asignación de Equipos de Protección Personal (EPP).
    Exige min_role_level = RoleLevel.SST_OFFICER (70).
    """
    required_module = 'sst'
    min_role_level = RoleLevel.SST_OFFICER

    @transaction.atomic
    def post(self, request):
        org = request.organization
        form = EPPDeliveryForm(request.POST, organization=org)

        if form.is_valid():
            epp = form.save(commit=False)
            epp.organization = org
            epp.delivered_by = request.user
            epp.save()

            messages.success(
                request,
                f"Dotación {epp.code} ({epp.item_name}) asignada exitosamente a {epp.collaborator.full_name or epp.collaborator.email}."
            )
        else:
            messages.error(request, "Error al registrar dotación de EPP. Verifique los datos ingresados.")

        return redirect('sst:checklists_and_epp')


class EPPAcknowledgeView(ModuleAccessRequiredMixin, View):
    """
    Confirmación de Recepción de Dotación EPP por el Colaborador.
    Accesible para el trabajador receptor (Nivel 20+) o Oficial SST (70+).
    """
    required_module = 'sst'
    min_role_level = RoleLevel.TECHNICIAN

    @transaction.atomic
    def post(self, request, pk):
        org = request.organization
        epp = get_object_or_404(EPPDelivery.objects.for_org(org), pk=pk)
        role_level = getattr(request, 'role_level', 0)

        # Regla de seguridad: solo el receptor legítimo o un supervisor SST (70+) puede firmar la recepción
        if request.user.id != epp.collaborator_id and role_level < RoleLevel.SST_OFFICER:
            return render_403_rbac(
                request,
                required_module='sst',
                min_role_level=RoleLevel.SST_OFFICER,
                reason="Solo el colaborador asignado o un Oficial SST pueden confirmar la recepción del EPP."
            )

        epp.acknowledged_by_worker = True
        epp.save(update_fields=['acknowledged_by_worker', 'updated_at'])

        messages.success(request, f"Recepción de {epp.item_name} ({epp.code}) confirmada satisfactoriamente.")
        return redirect('sst:checklists_and_epp')


class LeaveRequestListView(ModuleAccessRequiredMixin, TemplateView):
    """
    Consola de Permisos Laborales, Reposos Médicos y Vacaciones.
    - Técnicos (20): Visualizan únicamente sus solicitudes propias.
    - Oficiales SST / Coordinadores (70+): Visualizan todas las solicitudes para resolución.
    """
    template_name = 'sst/leave_requests.html'
    required_module = 'sst'
    min_role_level = RoleLevel.TECHNICIAN

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        user = self.request.user
        role_level = getattr(self.request, 'role_level', 0)
        is_field_tech = (role_level == RoleLevel.TECHNICIAN)

        if is_field_tech:
            leaves = LeaveRequest.objects.for_org(org).filter(requester=user).select_related('reviewed_by')
        else:
            leaves = LeaveRequest.objects.for_org(org).select_related('requester', 'reviewed_by')

        all_leaves = LeaveRequest.objects.for_org(org)

        # Determinar si el usuario actual puede autorizar solicitudes en base a su jerarquía
        leaves_data = []
        for l in leaves:
            can_review, _ = l.can_be_reviewed_by(user, role_level)
            leaves_data.append({
                'leave': l,
                'can_review': can_review,
            })

        context.update({
            'leaves_data': leaves_data,
            'is_field_tech': is_field_tech,
            'can_manage_leaves': role_level >= RoleLevel.SST_OFFICER,
            'total_pending': all_leaves.filter(status=LeaveRequest.Status.PENDING).count(),
            'total_approved': all_leaves.filter(status=LeaveRequest.Status.APPROVED).count(),
            'user_pending': all_leaves.filter(requester=user, status=LeaveRequest.Status.PENDING).count(),
            'leave_form': LeaveRequestForm(),
        })
        return context


class LeaveRequestCreateView(ModuleAccessRequiredMixin, View):
    """
    Presentación formal de Solicitud de Permiso Laboral.
    Accesible para todos los colaboradores (Nivel 20+).
    Guarda automáticamente requester y snapshot de requester_role_level.
    """
    required_module = 'sst'
    min_role_level = RoleLevel.TECHNICIAN

    @transaction.atomic
    def post(self, request):
        org = request.organization
        form = LeaveRequestForm(request.POST)

        if form.is_valid():
            leave = form.save(commit=False)
            leave.organization = org
            leave.requester = request.user
            leave.requester_role_level = getattr(request, 'role_level', RoleLevel.TECHNICIAN)
            leave.save()

            messages.success(
                request,
                f"Solicitud de permiso {leave.number} ({leave.get_leave_type_display()}) presentada con éxito."
            )
        else:
            messages.error(request, "Error al presentar solicitud de permiso. Verifique las fechas y campos obligatorios.")

        return redirect('sst:leave_list')


class LeaveRequestReviewView(ModuleAccessRequiredMixin, View):
    """
    Resolución (Aprobación o Rechazo) de Solicitud de Permiso Laboral.
    Aplica Regla Estricta Anti-Inversión de Mando:
    - Exige min_role_level = RoleLevel.SST_OFFICER (70).
    - Ejecuta leave.can_be_reviewed_by(request.user, request.role_level).
    - Bloquea con HTTP 403 si la jerarquía es insuficiente o si se intenta auto-aprobar.
    """
    required_module = 'sst'
    min_role_level = RoleLevel.SST_OFFICER

    @transaction.atomic
    def post(self, request, pk):
        org = request.organization
        leave = get_object_or_404(LeaveRequest.objects.for_org(org), pk=pk)
        role_level = getattr(request, 'role_level', 0)

        # Regla Anti-Inversión de Mando
        can_review, reason = leave.can_be_reviewed_by(request.user, role_level)
        if not can_review:
            return render_403_rbac(
                request,
                required_module='sst',
                min_role_level=leave.requester_role_level + 1,
                reason=reason,
            )

        action = request.POST.get('action')
        notes = request.POST.get('resolution_notes', '').strip()

        if action not in ['approve', 'reject']:
            messages.error(request, "Acción de resolución no válida.")
            return redirect('sst:leave_list')

        leave.reviewed_by = request.user
        leave.reviewed_at = timezone.now()
        leave.resolution_notes = notes

        if action == 'approve':
            leave.status = LeaveRequest.Status.APPROVED
            messages.success(request, f"Solicitud de permiso {leave.number} autorizada exitosamente.")
        else:
            leave.status = LeaveRequest.Status.REJECTED
            messages.warning(request, f"Solicitud de permiso {leave.number} rechazada.")

        leave.save()
        return redirect('sst:leave_list')
