"""
URL configuration for ERP SAS.
Admin exclusivo de SuperAdmin de la plataforma en 'platform-superadmin/'.
"""
from django.contrib import admin
from django.urls import include, path

from apps.core.views_pwa import PWAManifestView, PWAServiceWorkerView

urlpatterns = [
    # Infraestructura PWA Instalable de Campo
    path('manifest.json', PWAManifestView.as_view(), name='pwa_manifest'),
    path('service-worker.js', PWAServiceWorkerView.as_view(), name='pwa_service_worker'),

    # Interfaz administrativa exclusiva del SuperAdmin de la Plataforma
    path('platform-superadmin/', admin.site.urls),

    # Autenticación Corporativa
    path('auth/', include('apps.accounts_auth.urls')),

    # Espacio Operativo Multi-Tenant & Onboarding
    path('', include('apps.tenancy.urls')),

    # Radar de Alertas Proactivas y Agenda Corporativa
    path('', include('apps.core.urls')),

    # Módulo Comercial Unificado (CRM, Pipeline, Cotizador Bimonetario)
    path('crm/', include('apps.crm.urls')),

    # Módulo de Operaciones, Ingeniería y Órdenes de Trabajo (OT)
    path('operations/', include('apps.operations.urls')),

    # Módulo de Seguridad y Salud en el Trabajo (SST)
    path('sst/', include('apps.sst.urls')),

    # Módulo de Almacén, Bodegas y Kardex
    path('inventory/', include('apps.inventory.urls')),

    # Módulo de Finanzas, Tesorería y Fondos de Caja
    path('finance/', include('apps.finance.urls')),

    # Módulo de Facturación Fiscal DGI, Retenciones y Caja (Billing)
    path('billing/', include('apps.billing.urls')),

    # Módulo de Compras, Proveedores y Cuentas por Pagar (Purchasing)
    path('purchasing/', include('apps.purchasing.urls')),

    # Módulo de Repositorio Documental y Versionado ISO
    path('repository/', include('apps.repository.urls')),

    # Módulo de Mesa de Ayuda y Soporte SLA
    path('tickets/', include('apps.tickets.urls')),

    # Módulo de Servidor MCP, Agentes IA y Gobierno de Tokens
    path('mcp/', include('apps.ai_agent.urls')),
]
