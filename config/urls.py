"""
URL configuration for ERP SAS.
Admin exclusivo de SuperAdmin de la plataforma en 'platform-superadmin/'.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Interfaz administrativa exclusiva del SuperAdmin de la Plataforma
    path('platform-superadmin/', admin.site.urls),

    # Autenticación Corporativa
    path('auth/', include('apps.accounts_auth.urls')),

    # Espacio Operativo Multi-Tenant & Onboarding
    path('', include('apps.tenancy.urls')),

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
]
