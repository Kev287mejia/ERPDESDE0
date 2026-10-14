from django.views.generic import TemplateView
from apps.tenancy.models import RoleLevel
from apps.tenancy.permissions import ModuleAccessRequiredMixin


class TechDashboardView(ModuleAccessRequiredMixin, TemplateView):
    """
    Consola de Mando para MOD-TECH (Tecnología, Soporte IT & Activos Digitales).
    Accesible para roles técnicos (Nivel 20+) siempre que el Tenant tenga suscrito 'tech'.
    Diseñado bajo arquitectura 'All-Light Swiss Grid'.
    """
    template_name = 'tenancy/tech_dashboard.html'
    required_module = 'tech'
    min_role_level = RoleLevel.TECHNICIAN

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization

        # Datos operativos de activos IT y mesa de ayuda
        hardware_assets = [
            {'code': 'AST-001', 'type': 'Estación de Trabajo', 'model': 'Dell Precision 3660 Core i9', 'assigned_to': 'Ingeniería Residentes', 'status': 'OPERATIVO', 'warranty': '2028-12-31'},
            {'code': 'AST-002', 'type': 'Laptop de Campo', 'model': 'Lenovo ThinkPad T14s Gen 4', 'assigned_to': 'Supervisores de Cuadrilla', 'status': 'ASIGNADO', 'warranty': '2027-06-30'},
            {'code': 'AST-003', 'type': 'Infraestructura', 'model': 'Server Dell PowerEdge R650xs', 'assigned_to': 'Centro de Cómputo Principal', 'status': 'ACTIVO', 'warranty': '2029-01-15'},
            {'code': 'AST-004', 'type': 'Redes & Conectividad', 'model': 'Switch Cisco Catalyst 9200 48P', 'assigned_to': 'Rack Plantel Central', 'status': 'OPERATIVO', 'warranty': '2027-11-20'},
        ]

        active_tickets = [
            {'folio': 'TCK-2026-081', 'subject': 'Aprovisionamiento de Laptop para Ingeniero Residente', 'requester': 'Carlos Mendoza', 'priority': 'ALTA', 'status': 'EN CURSO', 'created_at': 'Hoy 08:30'},
            {'folio': 'TCK-2026-080', 'subject': 'Renovación de Certificados SSL y DNS Corporativo', 'requester': 'Área de TI', 'priority': 'CRÍTICA', 'status': 'EN REVISIÓN', 'created_at': 'Ayer 16:45'},
            {'folio': 'TCK-2026-079', 'subject': 'Configuración de VPN y Acceso Remoto para Campo', 'requester': 'Cuadrilla Linieros', 'priority': 'MEDIA', 'status': 'RESUELTO', 'created_at': '12 Oct'},
            {'folio': 'TCK-2026-078', 'subject': 'Licenciamiento AutoCAD y Software Eléctrico', 'requester': 'Ing. Residente Norte', 'priority': 'MEDIA', 'status': 'CERRADO', 'created_at': '10 Oct'},
        ]

        software_licenses = [
            {'name': 'Microsoft 365 Business Premium', 'assigned': 25, 'total': 30, 'renewal': '2027-03-31', 'vendor': 'Microsoft'},
            {'name': 'Autodesk AEC Collection', 'assigned': 6, 'total': 8, 'renewal': '2026-11-15', 'vendor': 'Autodesk'},
            {'name': 'GitHub Enterprise Cloud', 'assigned': 12, 'total': 15, 'renewal': '2027-01-01', 'vendor': 'GitHub Inc.'},
            {'name': 'AWS Cloud Infrastructure', 'assigned': 1, 'total': 1, 'renewal': 'Mensual', 'vendor': 'Amazon Web Services'},
        ]

        context.update({
            'hardware_assets': hardware_assets,
            'active_tickets': active_tickets,
            'software_licenses': software_licenses,
            'total_assets_count': len(hardware_assets),
            'open_tickets_count': len([t for t in active_tickets if t['status'] != 'RESUELTO' and t['status'] != 'CERRADO']),
            'total_licenses_assigned': sum(l['assigned'] for l in software_licenses),
            'system_uptime': '99.98%',
        })
        return context


class MarketingDashboardView(ModuleAccessRequiredMixin, TemplateView):
    """
    Consola de Mando para MOD-MKT (Marketing Digital, Campañas & Growth).
    Accesible para roles comerciales y de coordinación (Nivel 80+) con 'marketing' habilitado.
    Diseñado bajo arquitectura 'All-Light Swiss Grid'.
    """
    template_name = 'tenancy/marketing_dashboard.html'
    required_module = 'marketing'
    min_role_level = RoleLevel.OPERATIONS_COORD

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization

        campaigns = [
            {'name': 'Licitaciones Industriales Q4 2026', 'channel': 'Google Search Ads', 'budget': f"{org.currency_symbol} 120,000", 'spent': f"{org.currency_symbol} 45,800", 'clicks': 1420, 'leads': 38, 'status': 'ACTIVA'},
            {'name': 'Networking B2B Directores de Operaciones', 'channel': 'LinkedIn Sponsored', 'budget': 'USD 3,500', 'spent': 'USD 1,850', 'clicks': 680, 'leads': 24, 'status': 'ACTIVA'},
            {'name': 'Campaña Servicios de Subestaciones & MT', 'channel': 'Email & Eventos', 'budget': f"{org.currency_symbol} 60,000", 'spent': f"{org.currency_symbol} 58,200", 'clicks': 890, 'leads': 19, 'status': 'FINALIZADA'},
        ]

        inbound_leads = [
            {'company': 'Corporación Minera del Norte S.A.', 'contact': 'Ing. Roberto Somoza', 'email': 'rsomoza@mineranorte.com', 'channel': 'Google Search', 'interest': 'Mantenimiento Transformadores 138kV', 'status': 'CALIFICADO (SQL)', 'date': 'Hoy 09:15'},
            {'company': 'Distribuidora Agroindustrial Central', 'contact': 'Lic. Andrea Solís', 'email': 'asolis@agrocentral.com.ni', 'channel': 'LinkedIn Inbound', 'interest': 'Diseño Red Eléctrica Planta', 'status': 'CONTACTADO', 'date': 'Ayer 15:40'},
            {'company': 'Complejo Comercial Managua Plaza', 'contact': 'Arq. Manuel Gómez', 'email': 'mgomez@plazacentral.ni', 'channel': 'Sitio Web Directo', 'interest': 'Auditoría Energética & Alumbrado', 'status': 'NUEVO', 'date': '12 Oct'},
            {'company': 'Zona Franca Textil Las Américas', 'contact': 'Ing. Kevin Chen', 'email': 'kchen@textilamericas.com', 'channel': 'Google Ads', 'interest': 'Instalación de Subestación 500kVA', 'status': 'EN COTIZACIÓN', 'date': '11 Oct'},
        ]

        context.update({
            'campaigns': campaigns,
            'inbound_leads': inbound_leads,
            'total_monthly_leads': 81,
            'conversion_rate': '28.4%',
            'active_ad_spend': f"{org.currency_symbol} 110,650",
            'avg_cpl': f"{org.currency_symbol} 1,366",
        })
        return context
