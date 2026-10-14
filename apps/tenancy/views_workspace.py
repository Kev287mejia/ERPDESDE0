from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from apps.tenancy.models import Organization, OrganizationMembership


@login_required
def workspace_dashboard_view(request):
    """
    Vista principal del Espacio de Trabajo Operativo (ERP App Shell).
    Verifica que el usuario posea un contexto de organización activo.
    Si no posee ninguna organización, lo redirige al flujo de Onboarding.
    """
    if not getattr(request, 'organization', None):
        return redirect('onboarding_wizard')

    org = request.organization
    country = org.country
    role_level = getattr(request, 'role_level', 0)

    # Datos demostrativos de alta densidad técnica para el workspace operativo
    metrics = {
        'active_work_orders': 18,
        'crews_in_field': 6,
        'sst_compliance_rate': '99.4%',
        'pending_approvals': 4 if role_level >= 50 else 0,
        'total_billed_mtd': f"{country.primary_currency_symbol} 342,850.00",
        'usd_equivalent': "$ 9,340.00",
    }

    # Órdenes de trabajo recientes de ejemplo con formato estricto tabular-nums
    sample_work_orders = [
        {
            'code': 'OT-2026-0041',
            'title': 'Mantenimiento preventivo subestación Managua Norte',
            'client': 'Distribuidora del Norte S.A.',
            'crew_leader': 'Carlos Mendoza (Ing. Supervisor)',
            'status': 'EN EJECUCIÓN',
            'status_class': 'bg-blue-50 text-blue-700 border-blue-200',
            'priority': 'ALTA',
            'priority_class': 'bg-rose-50 text-rose-700 border-rose-200',
            'sst_cleared': True,
            'budget': f"{country.primary_currency_symbol} 45,200.00",
            'date': '2026-10-14',
        },
        {
            'code': 'OT-2026-0040',
            'title': 'Instalación canalización de fibra óptica km 12.5 Masaya',
            'client': 'Telecomunicaciones de Occidente',
            'crew_leader': 'Marcos Blandón (Técnico N2)',
            'status': 'EN EJECUCIÓN',
            'status_class': 'bg-blue-50 text-blue-700 border-blue-200',
            'priority': 'MEDIA',
            'priority_class': 'bg-amber-50 text-amber-700 border-amber-200',
            'sst_cleared': True,
            'budget': f"{country.primary_currency_symbol} 18,750.00",
            'date': '2026-10-13',
        },
        {
            'code': 'OT-2026-0039',
            'title': 'Inspección termográfica transformadores patio 138kV',
            'client': 'Parque Industrial Tipitapa',
            'crew_leader': 'Elena Morales (Oficial SST)',
            'status': 'POR APROBAR',
            'status_class': 'bg-purple-50 text-purple-700 border-purple-200',
            'priority': 'ALTA',
            'priority_class': 'bg-rose-50 text-rose-700 border-rose-200',
            'sst_cleared': False,
            'budget': f"{country.primary_currency_symbol} 12,000.00",
            'date': '2026-10-12',
        },
        {
            'code': 'OT-2026-0038',
            'title': 'Reemplazo tablero distribución seccionador A3',
            'client': 'Consorcio Agroindustrial Chinandega',
            'crew_leader': 'Roberto Ruiz (Ing. Residente)',
            'status': 'COMPLETADO',
            'status_class': 'bg-emerald-50 text-emerald-700 border-emerald-200',
            'priority': 'BAJA',
            'priority_class': 'bg-slate-100 text-slate-700 border-slate-300',
            'sst_cleared': True,
            'budget': f"{country.primary_currency_symbol} 28,400.00",
            'date': '2026-10-10',
        },
    ]

    # Lista de organizaciones a las que pertenece el usuario para el switcher
    user_memberships = OrganizationMembership.objects.select_related(
        'organization', 'organization__country'
    ).filter(
        user=request.user,
        is_active=True,
        organization__is_active=True
    )

    return render(request, 'dashboard/index.html', {
        'page_title': 'Consola de Operaciones & Despacho',
        'metrics': metrics,
        'sample_work_orders': sample_work_orders,
        'user_memberships': user_memberships,
    })


@login_required
def switch_organization_view(request, org_id):
    """
    Cambia la organización activa en la sesión del usuario previa validación de membresía.
    """
    membership = get_object_or_404(
        OrganizationMembership,
        user=request.user,
        organization_id=org_id,
        is_active=True,
        organization__is_active=True
    )
    request.session['active_org_id'] = str(membership.organization.id)
    messages.info(
        request,
        f"Espacio de trabajo cambiado a: {membership.organization.name}"
    )
    return redirect('workspace_dashboard')
