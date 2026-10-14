import logging
from apps.tenancy.models import OrganizationMembership, RoleLevel

logger = logging.getLogger('apps.tenancy')


class TenancyContextMiddleware:
    """
    Middleware de Contexto Multi-Tenant, Control de Acceso Jerárquico y Simulador de Rol.

    Responsabilidades:
    1. Resuelve 'request.organization' en cada ciclo de petición HTTP.
    2. Resuelve 'request.membership' con la relación específica del usuario y el Tenant.
    3. Expone 'request.role_level' como un entero para verificación rápida de permisos.
    4. Guarda siempre 'request.real_role_level' y 'request.is_simulating_role'.
    5. Permite a los usuarios OWNER_ADMIN (100) simular roles subordinados (85, 80, 70, 50, 20, 10)
       en tiempo real sin tener que cerrar sesión.
    6. Mantiene la sincronización de 'active_org_id' en la sesión del usuario.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Inicialización de valores predeterminados (para usuarios anónimos o sin tenant)
        request.organization = None
        request.membership = None
        request.role_level = 0
        request.real_role_level = 0
        request.is_simulating_role = False

        user = getattr(request, 'user', None)

        # 2. Solo resolver tenancy si el usuario está autenticado
        if user and user.is_authenticated:
            self._resolve_tenancy_context(request, user)

        # 3. Continuar la cadena de middleware / ejecución de la vista
        response = self.get_response(request)
        return response

    def _resolve_tenancy_context(self, request, user):
        """
        Resuelve la organización activa siguiendo la estrategia de precedencia:
        1. ID de organización guardado en sesión ('active_org_id').
        2. Membresía marcada como predeterminada (is_default_org=True).
        3. Membresía activa con mayor nivel de rol jerárquico.
        """
        session_org_id = request.session.get('active_org_id')

        # Consulta optimizada con select_related para evitar N+1 queries
        active_memberships = (
            OrganizationMembership.objects
            .select_related('organization', 'organization__country')
            .filter(
                user=user,
                is_active=True,
                organization__is_active=True
            )
        )

        resolved_membership = None

        # Prioridad 1: Sesión activa
        if session_org_id:
            resolved_membership = active_memberships.filter(
                organization_id=session_org_id
            ).first()

        # Prioridad 2: Membresía default del usuario
        if not resolved_membership:
            resolved_membership = active_memberships.filter(
                is_default_org=True
            ).first()

        # Prioridad 3: Fallback a la membresía de mayor jerarquía / más antigua
        if not resolved_membership:
            resolved_membership = active_memberships.order_by(
                '-role_level', 'created_at'
            ).first()

        # Si se encontró una membresía válida, inyectar el contexto en el request
        if resolved_membership:
            request.membership = resolved_membership
            request.organization = resolved_membership.organization
            request.real_role_level = resolved_membership.role_level
            request.role_level = resolved_membership.role_level
            request.is_simulating_role = False

            # Motor de Simulación de Rol en Tiempo Real (Exclusivo para OWNER_ADMIN 100)
            if resolved_membership.role_level == RoleLevel.OWNER_ADMIN:
                simulated_level = request.session.get('simulated_role_level')
                if simulated_level is not None:
                    try:
                        sim_level_int = int(simulated_level)
                        if sim_level_int in RoleLevel.values and sim_level_int != RoleLevel.OWNER_ADMIN:
                            request.role_level = sim_level_int
                            request.is_simulating_role = True
                        elif sim_level_int == RoleLevel.OWNER_ADMIN:
                            request.session.pop('simulated_role_level', None)
                    except (ValueError, TypeError):
                        request.session.pop('simulated_role_level', None)

            # Sincronizar la sesión si es necesario
            org_id_str = str(request.organization.id)
            if session_org_id != org_id_str:
                request.session['active_org_id'] = org_id_str
        else:
            # Si el usuario no tiene ninguna membresía activa válida, limpiar residuo de sesión
            if session_org_id:
                request.session.pop('active_org_id', None)
            request.session.pop('simulated_role_level', None)
