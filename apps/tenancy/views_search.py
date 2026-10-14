from django.db.models import Q
from django.shortcuts import render
from django.views import View

from apps.tenancy.models import RoleLevel


class GlobalOmniSearchView(View):
    """
    Motor de Búsqueda Global en Tiempo Real (Ctrl+K OmniSearch vía HTMX).
    Aislamiento Multi-Tenant estricto y segregación granular RBAC.
    """
    def get(self, request):
        if not request.user.is_authenticated or not hasattr(request, 'organization') or not request.organization:
            return render(request, 'tenancy/omnisearch_results.html', {'results_empty': True, 'query': ''})

        query = request.GET.get('q', '').strip()
        org = request.organization
        role_level = getattr(request, 'role_level', 0)
        membership = getattr(request, 'membership', None)

        if len(query) < 2:
            return render(request, 'tenancy/omnisearch_results.html', {
                'query': query,
                'too_short': True,
            })

        accounts = []
        quotes = []
        work_orders = []
        inventory_items = []
        documents = []
        tickets = []

        # 1. CRM: Clientes y Cotizaciones (Exclusivo Nivel 80+)
        can_view_crm = (role_level >= RoleLevel.OPERATIONS_COORD) or (
            membership.has_module_access('crm', effective_role_level=role_level) if membership else False
        )
        if can_view_crm:
            try:
                from apps.crm.models import Account, Quote
                accounts = list(
                    Account.objects.for_org(org).filter(
                        Q(code__icontains=query) |
                        Q(commercial_name__icontains=query) |
                        Q(legal_name__icontains=query) |
                        Q(tax_id__icontains=query)
                    )[:5]
                )
                quotes = list(
                    Quote.objects.for_org(org).select_related('account').filter(
                        Q(number__icontains=query) |
                        Q(title__icontains=query) |
                        Q(account__commercial_name__icontains=query)
                    )[:5]
                )
            except Exception:
                pass

        # 2. Operaciones: Órdenes de Trabajo (Nivel 20 solo asignadas, 50+ todas)
        try:
            from apps.operations.models import WorkOrder
            wo_qs = WorkOrder.objects.for_org(org).select_related('assigned_crew', 'assigned_engineer')
            if role_level <= RoleLevel.TECHNICIAN:
                wo_qs = wo_qs.filter(
                    Q(assigned_crew__members=request.user) |
                    Q(assigned_crew__leader=request.user) |
                    Q(created_by=request.user)
                )
            work_orders = list(
                wo_qs.filter(
                    Q(number__icontains=query) |
                    Q(title__icontains=query) |
                    Q(site_address__icontains=query)
                )[:6]
            )
        except Exception:
            pass

        # 3. Inventario & Materiales (Exclusivo Nivel 50+)
        can_view_inv = role_level >= RoleLevel.ENGINEER
        if can_view_inv:
            try:
                from apps.inventory.models import InventoryItem
                inventory_items = list(
                    InventoryItem.objects.for_org(org).filter(
                        Q(code__icontains=query) |
                        Q(name__icontains=query) |
                        Q(category__icontains=query)
                    )[:6]
                )
            except Exception:
                pass

        # 4. Repositorio Documental ISO (Filtrado por min_role_level_view de cada carpeta)
        try:
            from apps.repository.models import CorporateDocument
            documents = list(
                CorporateDocument.objects.for_org(org).select_related('folder').filter(
                    folder__min_role_level_view__lte=role_level
                ).filter(
                    Q(code__icontains=query) |
                    Q(title__icontains=query) |
                    Q(latest_filename__icontains=query)
                )[:6]
            )
        except Exception:
            pass

        # 5. Mesa de Ayuda / Tickets SLA (Nivel 20 solo propios, 50+ todos)
        try:
            from apps.tickets.models import SupportTicket
            tck_qs = SupportTicket.objects.for_org(org)
            if role_level <= RoleLevel.TECHNICIAN:
                tck_qs = tck_qs.filter(
                    Q(reported_by=request.user) | Q(assigned_to=request.user)
                )
            tickets = list(
                tck_qs.filter(
                    Q(number__icontains=query) |
                    Q(title__icontains=query) |
                    Q(description__icontains=query)
                )[:6]
            )
        except Exception:
            pass

        total_results = (
            len(accounts) + len(quotes) + len(work_orders) +
            len(inventory_items) + len(documents) + len(tickets)
        )

        return render(request, 'tenancy/omnisearch_results.html', {
            'query': query,
            'accounts': accounts,
            'quotes': quotes,
            'work_orders': work_orders,
            'inventory_items': inventory_items,
            'documents': documents,
            'tickets': tickets,
            'total_results': total_results,
        })
