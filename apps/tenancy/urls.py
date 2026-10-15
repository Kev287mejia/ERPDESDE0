from django.urls import path
from apps.tenancy import views_modules, views_onboarding, views_saas_hq, views_search, views_team

app_name = 'tenancy'

urlpatterns = [
    # Espacio de Trabajo Principal (Dashboard Operativo)
    path('', views_onboarding.DashboardWorkspaceView.as_view(), name='dashboard'),

    # Flujo de Onboarding Multi-País
    path('onboarding/', views_onboarding.OnboardingWizardView.as_view(), name='onboarding'),
    path('onboarding/validate-ruc/', views_onboarding.validate_ruc_htmx, name='validate_ruc_htmx'),

    # Conmutador de Organizaciones Activas
    path('switch-org/<uuid:org_id>/', views_onboarding.SwitchOrganizationView.as_view(), name='switch_org'),
    path('switch-org/', views_onboarding.SwitchOrganizationView.as_view(), name='switch_org_post'),

    # Simulador de Rol Jerárquico en Tiempo Real (Exclusivo Owner 100)
    path('settings/simulate-role/', views_team.SimulateRoleView.as_view(), name='simulate_role'),

    # Gobierno Corporativo, Nómina y Módulos en Caliente
    path('settings/team/', views_team.TeamListView.as_view(), name='team_management'),
    path('settings/team/create/', views_team.TeamCreateMemberView.as_view(), name='team_create'),
    path('settings/team/<uuid:membership_id>/update/', views_team.MemberRoleUpdateView.as_view(), name='member_update'),
    path('settings/modules/', views_team.OrganizationModulesUpdateView.as_view(), name='update_modules'),
    path('settings/apply-preset/', views_team.ApplyBusinessProfilePresetView.as_view(), name='apply_preset'),
    path('settings/apply-business-preset/', views_team.ApplyBusinessProfilePresetView.as_view(), name='apply_business_preset'),
    path('settings/switch-vertical/', views_team.SwitchBusinessVerticalView.as_view(), name='switch_vertical'),

    # Subsistemas Dinámicos Opcionales
    path('tech/', views_modules.TechDashboardView.as_view(), name='tech_dashboard'),
    path('marketing/', views_modules.MarketingDashboardView.as_view(), name='marketing_dashboard'),

    # Motor de Búsqueda Global en Tiempo Real (Ctrl+K OmniSearch)
    path('search/omnisearch/', views_search.GlobalOmniSearchView.as_view(), name='omnisearch'),

    # Controles de Escenario Demo / Sandbox (Exclusivo Owner 100)
    path('settings/sandbox/load/', views_onboarding.LoadSandboxDataView.as_view(), name='sandbox_load'),
    path('settings/sandbox/reset/', views_onboarding.ResetSandboxDataView.as_view(), name='sandbox_reset'),

    # Consola Ejecutiva de Monetización SaaS HQ (Exclusivo Owner 100)
    path('saas-hq/', views_saas_hq.SaasHQDashboardView.as_view(), name='saas_hq'),
    path('saas-hq/switch-plan/', views_saas_hq.SaasSwitchPlanView.as_view(), name='saas_switch_plan'),
    path('saas-hq/update-status/', views_saas_hq.SaasUpdateStatusView.as_view(), name='saas_update_status'),
    path('saas-hq/generate-invoice/', views_saas_hq.SaasGenerateInvoiceView.as_view(), name='saas_generate_invoice'),
]
