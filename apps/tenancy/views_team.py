import uuid
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.tenancy.forms import MemberRoleUpdateForm, TeamCreateMemberForm
from apps.tenancy.models import OrganizationMembership, RoleLevel
from apps.tenancy.permissions import RoleLevelRequiredMixin, TenantRequiredMixin

User = get_user_model()


class SimulateRoleView(TenantRequiredMixin, View):
    """
    Simulador de Rol Jerárquico en Tiempo Real.
    Permite exclusivamente al Administrador General (real_role_level == 100)
    conmutar su vista operativa a cualquier nivel subordinado (85, 80, 70, 50, 20, 10)
    para auditar la visibilidad de menús y la seguridad de los controladores sin salir de la sesión.
    """
    def post(self, request, *args, **kwargs):
        # Exigir que el rol REAL en base de datos sea OWNER_ADMIN
        if getattr(request, 'real_role_level', 0) < RoleLevel.OWNER_ADMIN:
            messages.error(request, "Solo el Administrador General puede ejecutar la simulación de roles.")
            return redirect('tenancy:dashboard')

        target_role = request.POST.get('role_level', '').strip()

        if target_role in ('', 'clear', '100', str(RoleLevel.OWNER_ADMIN)):
            request.session.pop('simulated_role_level', None)
            messages.info(request, "Simulación desactivada. Sesión restaurada a vista real OWNER / ADMIN.")
        else:
            try:
                sim_level = int(target_role)
                if sim_level in RoleLevel.values:
                    request.session['simulated_role_level'] = sim_level
                    messages.warning(
                        request,
                        f"Modo Simulación Activo: Navegando como {RoleLevel(sim_level).label} (Nivel {sim_level})."
                    )
                else:
                    request.session.pop('simulated_role_level', None)
            except (ValueError, TypeError):
                request.session.pop('simulated_role_level', None)

        referer = request.META.get('HTTP_REFERER')
        return redirect(referer if referer else 'tenancy:dashboard')


class TeamListView(RoleLevelRequiredMixin, View):
    """
    Consola de Gobierno Corporativo, Nómina de Personal y Cadena de Mando RBAC.
    Protegido con RoleLevelRequiredMixin (min_role_level = OWNER_ADMIN 100).
    """
    min_role_level = RoleLevel.OWNER_ADMIN
    template_name = 'tenancy/team_management.html'

    def get(self, request, *args, **kwargs):
        members = (
            OrganizationMembership.objects
            .filter(organization=request.organization)
            .select_related('user')
            .order_by('-role_level', 'user__full_name')
        )

        create_form = TeamCreateMemberForm(
            organization=request.organization,
            current_user_role_level=request.role_level
        )

        return render(request, self.template_name, {
            'members': members,
            'create_form': create_form,
            'all_modules': [
                {'code': 'crm', 'name': 'MOD-CRM · Gestión Comercial & Cotizaciones', 'min_role': 'Nivel 80+'},
                {'code': 'operations', 'name': 'MOD-OPS · Órdenes de Trabajo & Cuadrillas', 'min_role': 'Nivel 20+'},
                {'code': 'sst', 'name': 'MOD-SST · Seguridad Laboral & Permisos MITRAB', 'min_role': 'Nivel 20+ / 70+'},
                {'code': 'inventory', 'name': 'MOD-INV · Control de Materiales & Almacén', 'min_role': 'Nivel 50+'},
                {'code': 'finance', 'name': 'MOD-FIN · Tesorería, Cajas Chicas & Bancos', 'min_role': 'Nivel 50+ / 80+'},
                {'code': 'tech', 'name': 'MOD-TECH · Tecnología, Soporte IT & Activos Digitales', 'min_role': 'Nivel 20+'},
                {'code': 'marketing', 'name': 'MOD-MKT · Marketing Digital, Campañas & Growth', 'min_role': 'Nivel 80+'},
            ],
        })


class TeamCreateMemberView(RoleLevelRequiredMixin, View):
    """
    Registra y enrola a un nuevo colaborador en la organización.
    Si el correo ya existe, añade la membresía con el nivel indicado; si no, crea el User.
    """
    min_role_level = RoleLevel.OWNER_ADMIN

    def post(self, request, *args, **kwargs):
        form = TeamCreateMemberForm(
            organization=request.organization,
            current_user_role_level=request.role_level,
            data=request.POST,
        )

        if form.is_valid():
            email = form.cleaned_data['email']
            full_name = form.cleaned_data['full_name']
            personal_id = form.cleaned_data['personal_id_number']
            phone = form.cleaned_data['phone']
            job_title = form.cleaned_data['job_title']
            role_level = form.cleaned_data['role_level']
            password = form.cleaned_data['password']

            with transaction.atomic():
                user = User.objects.filter(email=email).first()
                if not user:
                    user = User.objects.create_user(
                        email=email,
                        password=password if password else 'Vector2026!',
                        full_name=full_name,
                        personal_id_number=personal_id,
                        phone=phone,
                    )
                else:
                    # Actualizar datos de identidad si estaban vacíos
                    updated = False
                    if not user.full_name:
                        user.full_name = full_name
                        updated = True
                    if not user.personal_id_number:
                        user.personal_id_number = personal_id
                        updated = True
                    if not user.phone:
                        user.phone = phone
                        updated = True
                    if updated:
                        user.save()

                membership = OrganizationMembership.objects.create(
                    user=user,
                    organization=request.organization,
                    role_level=role_level,
                    job_title=job_title,
                    is_active=True,
                )

            messages.success(
                request,
                f"Colaborador {user.full_name} enrolado con éxito como {membership.get_role_level_display()}."
            )
            return redirect('tenancy:team_management')

        # Si hubo errores de validación, renderizar de nuevo con código 422
        members = (
            OrganizationMembership.objects
            .filter(organization=request.organization)
            .select_related('user')
            .order_by('-role_level', 'user__full_name')
        )
        return render(request, 'tenancy/team_management.html', {
            'members': members,
            'create_form': form,
            'all_modules': [
                {'code': 'crm', 'name': 'MOD-CRM · Gestión Comercial & Cotizaciones', 'min_role': 'Nivel 80+'},
                {'code': 'operations', 'name': 'MOD-OPS · Órdenes de Trabajo & Cuadrillas', 'min_role': 'Nivel 20+'},
                {'code': 'sst', 'name': 'MOD-SST · Seguridad Laboral & Permisos MITRAB', 'min_role': 'Nivel 20+ / 70+'},
                {'code': 'inventory', 'name': 'MOD-INV · Control de Materiales & Almacén', 'min_role': 'Nivel 50+'},
            ],
            'show_modal_on_load': True,
        }, status=422)


class OrganizationModulesUpdateView(RoleLevelRequiredMixin, View):
    """
    Gobierno de Módulos Operativos en Caliente.
    Permite activar o desactivar en caliente cualquiera de los 4 módulos contratados.
    """
    min_role_level = RoleLevel.OWNER_ADMIN

    def post(self, request, *args, **kwargs):
        submitted_modules = request.POST.getlist('enabled_modules')
        valid_modules = ['crm', 'operations', 'sst', 'inventory', 'finance', 'tech', 'marketing']

        cleaned_modules = [m for m in submitted_modules if m in valid_modules]

        if not cleaned_modules:
            messages.error(request, "Debe mantener al menos un módulo operativo activo en la organización.")
            return redirect('tenancy:team_management')

        request.organization.enabled_modules = cleaned_modules
        request.organization.save(update_fields=['enabled_modules', 'updated_at'])

        messages.success(
            request,
            f"Configuración modular actualizada. Módulos activos: {', '.join(cleaned_modules).upper()}."
        )
        return redirect('tenancy:team_management')


class MemberRoleUpdateView(RoleLevelRequiredMixin, View):
    """
    Actualiza el rol jerárquico, cargo o estado de una membresía existente.
    Protege contra degradación o desactivación del último Owner/Admin.
    """
    min_role_level = RoleLevel.OWNER_ADMIN

    def post(self, request, membership_id, *args, **kwargs):
        membership = get_object_or_404(
            OrganizationMembership,
            id=membership_id,
            organization=request.organization,
        )

        form = MemberRoleUpdateForm(
            current_user_role_level=request.role_level,
            data=request.POST,
            instance=membership,
        )

        if form.is_valid():
            form.save()
            messages.success(
                request,
                f"Membresía de {membership.user.full_name} actualizada: {membership.get_role_level_display()} "
                f"[{'ACTIVO' if membership.is_active else 'INACTIVO'}]."
            )
        else:
            for field, errs in form.errors.items():
                for err in errs:
                    messages.error(request, f"Error en {field}: {err}")

        return redirect('tenancy:team_management')
