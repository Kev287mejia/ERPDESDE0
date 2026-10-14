from apps.tenancy.models import OrganizationMembership, RoleLevel


def tenancy_context(request):
    """
    Context Processor Multi-Tenant, RBAC Jerárquico y Simulador de Rol.
    Expone variables de contexto seguras y reactivas para todos los templates del ERP.
    """
    user = getattr(request, 'user', None)
    organization = getattr(request, 'organization', None)
    membership = getattr(request, 'membership', None)
    role_level = getattr(request, 'role_level', 0)
    real_role_level = getattr(request, 'real_role_level', role_level)
    is_simulating_role = getattr(request, 'is_simulating_role', False)

    # Identificación del país de operación
    current_country = getattr(organization, 'country', None) if organization else None

    # Etiqueta del rol activo (mostrando el rol simulado si la simulación está activa)
    if role_level in RoleLevel.values:
        current_role_label = RoleLevel(role_level).label
    elif membership:
        current_role_label = membership.get_role_level_display()
    elif user and user.is_authenticated and user.is_superuser:
        current_role_label = "SUPERADMIN PLATAFORMA"
    else:
        current_role_label = "SIN ASIGNAR"

    # Membresías activas del usuario (para el switcher de organización)
    user_memberships = []
    if user and user.is_authenticated:
        user_memberships = list(
            OrganizationMembership.objects
            .select_related('organization', 'organization__country')
            .filter(
                user=user,
                is_active=True,
                organization__is_active=True
            )
            .order_by('-role_level', 'organization__name')
        )

    # Matriz booleana de navegación calculada en tiempo real
    # Nota clave: se pasa effective_role_level=role_level para que la barra lateral y los accesos
    # reaccionen inmediatamente cuando el Owner simula otro rol operativo.
    nav_access = {
        'can_view_crm': membership.has_module_access('crm', effective_role_level=role_level) if membership else False,
        'can_manage_crm': (role_level >= RoleLevel.COMMERCIAL_MGR) if membership else False,
        'can_view_billing': membership.has_module_access('billing', effective_role_level=role_level) if membership else False,
        'can_manage_billing': (role_level >= RoleLevel.COMMERCIAL_MGR) if membership else False,
        'can_view_purchasing': membership.has_module_access('purchasing', effective_role_level=role_level) if membership else False,
        'can_pay_suppliers': (role_level >= RoleLevel.COMMERCIAL_MGR) if membership else False,
        'can_view_operations': membership.has_module_access('operations', effective_role_level=role_level) if membership else False,
        'can_view_sst': membership.has_module_access('sst', effective_role_level=role_level) if membership else False,
        'can_view_inventory': membership.has_module_access('inventory', effective_role_level=role_level) if membership else False,
        'can_view_finance': membership.has_module_access('finance', effective_role_level=role_level) if membership else False,
        'can_view_tech': membership.has_module_access('tech', effective_role_level=role_level) if membership else False,
        'can_view_marketing': membership.has_module_access('marketing', effective_role_level=role_level) if membership else False,
        'can_view_repository': membership.has_module_access('repository', effective_role_level=role_level) if membership else False,
        'can_view_tickets': membership.has_module_access('tickets', effective_role_level=role_level) if membership else False,
        'can_view_ai_mcp': membership.has_module_access('ai_agent', effective_role_level=role_level) if membership else False,
        'can_manage_org': role_level >= RoleLevel.OWNER_ADMIN,
        'can_approve_sst': role_level >= RoleLevel.SST_OFFICER,
        'can_plan_crews': role_level >= RoleLevel.OPERATIONS_COORD,
        'can_view_financials': (role_level >= RoleLevel.OPERATIONS_COORD) if membership else False,
        'is_field_tech_only': role_level == RoleLevel.TECHNICIAN,
    }

    return {
        'current_org': organization,
        'current_country': current_country,
        'current_membership': membership,
        'current_role_level': role_level,
        'real_role_level': real_role_level,
        'is_simulating_role': is_simulating_role,
        'current_role_label': current_role_label,
        'user_memberships': user_memberships,
        'nav_access': nav_access,
        'RoleLevel': RoleLevel,
        'role_choices': RoleLevel.choices,
        'role_choices_desc': sorted(RoleLevel.choices, key=lambda x: x[0], reverse=True),
    }
