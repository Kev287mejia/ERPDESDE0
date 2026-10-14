from functools import wraps
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from apps.tenancy.models import RoleLevel


def render_403_rbac(request, required_module=None, min_role_level=None, reason=None):
    """
    Renderiza la vista de acceso denegado por jerarquía RBAC con HTTP 403.
    Provee el contexto de auditoría sobre el nivel del usuario vs. nivel requerido.
    """
    role_level = getattr(request, 'role_level', 0)
    real_role_level = getattr(request, 'real_role_level', role_level)
    is_simulating_role = getattr(request, 'is_simulating_role', False)

    current_role_label = "SIN ASIGNAR"
    if role_level in RoleLevel.values:
        current_role_label = RoleLevel(role_level).label

    required_role_label = "AUTORIZACIÓN GENERAL"
    if min_role_level and min_role_level in RoleLevel.values:
        required_role_label = RoleLevel(min_role_level).label

    context = {
        'current_role_level': role_level,
        'real_role_level': real_role_level,
        'current_role_label': current_role_label,
        'required_role_level': min_role_level,
        'required_role_label': required_role_label,
        'required_module': required_module,
        'is_simulating_role': is_simulating_role,
        'reason': reason or "Su nivel de autoridad actual no posee los privilegios requeridos para este recurso.",
    }
    return render(request, 'tenancy/403_rbac.html', context, status=403)


class TenantRequiredMixin(LoginRequiredMixin):
    """
    Guardián que asegura que el usuario posea una organización y membresía activas.
    Si no posee una organización resuelta, lo redirige al flujo de Onboarding.
    """
    def check_tenant_requirements(self, request):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not getattr(request, 'organization', None) or not getattr(request, 'membership', None):
            return redirect('tenancy:onboarding')

        if not request.organization.is_active or not request.membership.is_active:
            return render_403_rbac(
                request,
                reason="La organización o su membresía operativa se encuentran suspendidas o inactivas."
            )
        return None

    def dispatch(self, request, *args, **kwargs):
        tenant_error = self.check_tenant_requirements(request)
        if tenant_error:
            return tenant_error
        return super().dispatch(request, *args, **kwargs)


class ModuleAccessRequiredMixin(TenantRequiredMixin):
    """
    Guardián que verifica:
    1. Que el módulo solicitado esté contratado y activo en la organización.
    2. Que el usuario tenga acceso efectivo al módulo considerando su role_level activo.
    3. Que el role_level sea igual o superior a 'min_role_level'.
    """
    required_module = None
    min_role_level = RoleLevel.OBSERVER

    def dispatch(self, request, *args, **kwargs):
        # 1. Validar requisitos de Tenancy antes de ejecutar el handler de la vista
        tenant_error = self.check_tenant_requirements(request)
        if tenant_error:
            return tenant_error

        # 2. Validar que el módulo esté definido
        if not self.required_module:
            raise ValueError("ModuleAccessRequiredMixin requiere que 'required_module' esté especificado.")

        membership = request.membership
        role_level = getattr(request, 'role_level', 0)

        # 3. Validar acceso efectivo al módulo
        has_access = membership.has_module_access(
            self.required_module,
            effective_role_level=role_level
        )

        if not has_access or role_level < self.min_role_level:
            return render_403_rbac(
                request,
                required_module=self.required_module,
                min_role_level=self.min_role_level,
                reason=(
                    f"El módulo '{self.required_module.upper()}' no está habilitado para su nivel de autoridad "
                    f"o no está suscrito por la organización."
                )
            )

        return super().dispatch(request, *args, **kwargs)


class RoleLevelRequiredMixin(TenantRequiredMixin):
    """
    Guardián estricto que verifica que el role_level activo del usuario sea
    mayor o igual a 'min_role_level'.
    """
    min_role_level = RoleLevel.OWNER_ADMIN

    def dispatch(self, request, *args, **kwargs):
        tenant_error = self.check_tenant_requirements(request)
        if tenant_error:
            return tenant_error

        role_level = getattr(request, 'role_level', 0)

        if role_level < self.min_role_level:
            return render_403_rbac(
                request,
                min_role_level=self.min_role_level,
                reason=(
                    f"Esta acción requiere un nivel jerárquico mínimo de {self.min_role_level} "
                    f"({RoleLevel(self.min_role_level).label if self.min_role_level in RoleLevel.values else ''})."
                )
            )

        return super().dispatch(request, *args, **kwargs)


def tenant_required(view_func):
    """Decorador FBV para exigir contexto de organización activa."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts_auth:login')
        if not getattr(request, 'organization', None) or not getattr(request, 'membership', None):
            return redirect('tenancy:onboarding')
        if not request.organization.is_active or not request.membership.is_active:
            return render_403_rbac(request, reason="Organización o membresía inactiva.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def role_level_required(min_level):
    """Decorador FBV para exigir nivel jerárquico mínimo."""
    def decorator(view_func):
        @wraps(view_func)
        @tenant_required
        def _wrapped_view(request, *args, **kwargs):
            role_level = getattr(request, 'role_level', 0)
            if role_level < min_level:
                return render_403_rbac(request, min_role_level=min_level)
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
