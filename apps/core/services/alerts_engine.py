import datetime
from decimal import Decimal
from django.urls import reverse
from django.utils import timezone

from apps.tenancy.models import RoleLevel


def get_active_alerts_for_user(organization, user, role_level: int) -> dict:
    """
    Motor Central de Detección de Alertas Proactivas Multi-Giro en Tiempo Real.
    Escanea inventarios FEFO, seguridad laboral SST, mesas de ayuda operativas
    y compromisos fiscales/cartera CxC/CxP.

    REGLAS DE SEGURIDAD Y CONFIDENCIALIDAD RBAC:
    - role_level >= 50: Acceso a alertas de inventario (lotes caducados FEFO, stock bajo),
      OTs de alto riesgo sin liberación SST y tickets con SLA vencido.
    - role_level == 20: Técnicos de campo solo reciben alertas de sus propias dotaciones EPP.
    - role_level >= 70: Oficiales SST ven todas las dotaciones EPP vencidas en la empresa.
    - role_level >= 80: Acceso EXCLUSIVO a alertas financieras de Cartera CxC en mora y
      cuentas por pagar a proveedores (CxP DGI). Roles < 80 reciben 0 alertas financieras.
    """
    now = timezone.now()
    today = now.date()
    alerts = []

    # =========================================================================
    # 1. ALERTAS DE ALMACÉN Y LOTES SANITARIOS FEFO (role_level >= 50)
    # =========================================================================
    if role_level >= RoleLevel.ENGINEER and organization.is_module_enabled('inventory'):
        from apps.inventory.models import InventoryBatch, InventoryItem

        # 1.1 Lotes Sanitarios Caducados en Bodega (CRITICAL)
        expired_batches = (
            InventoryBatch.objects.for_org(organization)
            .filter(
                quantity_available__gt=Decimal('0.00'),
                expiration_date__lt=today,
            )
            .select_related('item', 'warehouse')
            .order_by('expiration_date')
        )

        for batch in expired_batches:
            try:
                target_url = reverse('inventory:item_detail', kwargs={'pk': batch.item.pk})
            except Exception:
                target_url = '/inventory/'

            alerts.append({
                'code': 'BATCH_EXPIRED',
                'category': 'INVENTORY_FEFO',
                'severity': 'CRITICAL',
                'title': f"Lote Caducado en Bodega: {batch.batch_number}",
                'detail': (
                    f"El lote de {batch.item.name} ({batch.item.sku}) en {batch.warehouse.name} "
                    f"venció el {batch.expiration_date.strftime('%d/%m/%Y')}. "
                    f"Saldo bloqueado para venta: {batch.quantity_available:g} {batch.item.unit}."
                ),
                'target_url': target_url,
                'metric_mono': f"{batch.quantity_available:g} {batch.item.unit} VENCIDOS",
            })

        # 1.2 Lotes Próximos a Vencer en <= 90 días (HIGH)
        warning_batches = (
            InventoryBatch.objects.for_org(organization)
            .filter(
                quantity_available__gt=Decimal('0.00'),
                expiration_date__gte=today,
                expiration_date__lte=today + datetime.timedelta(days=90),
            )
            .select_related('item', 'warehouse')
            .order_by('expiration_date')
        )

        for batch in warning_batches:
            days_left = (batch.expiration_date - today).days
            try:
                target_url = reverse('inventory:item_detail', kwargs={'pk': batch.item.pk})
            except Exception:
                target_url = '/inventory/'

            alerts.append({
                'code': 'BATCH_EXPIRING_SOON',
                'category': 'INVENTORY_FEFO',
                'severity': 'HIGH',
                'title': f"Lote Próximo a Vencer (FEFO): {batch.batch_number}",
                'detail': (
                    f"Lote de {batch.item.name} en {batch.warehouse.name} vence en {days_left} días "
                    f"({batch.expiration_date.strftime('%d/%m/%Y')}). Priorizar rotación en mostrador/OT."
                ),
                'target_url': target_url,
                'metric_mono': f"{days_left} DÍAS RESTANTES",
            })

        # 1.3 Ítems con Stock en o por debajo del Mínimo de Seguridad (HIGH)
        active_items = (
            InventoryItem.objects.for_org(organization)
            .filter(is_active=True)
            .prefetch_related('balances')
        )

        for item in active_items:
            stock = item.total_stock()
            if stock <= item.min_stock_level:
                try:
                    target_url = reverse('inventory:item_detail', kwargs={'pk': item.pk})
                except Exception:
                    target_url = '/inventory/'

                alerts.append({
                    'code': 'LOW_STOCK',
                    'category': 'INVENTORY_FEFO',
                    'severity': 'HIGH',
                    'title': f"Stock Bajo Punto de Reorden: {item.sku}",
                    'detail': (
                        f"{item.name} tiene una existencia actual de {stock:g} {item.unit}, "
                        f"inferior o igual al stock mínimo configurado ({item.min_stock_level:g} {item.unit})."
                    ),
                    'target_url': target_url,
                    'metric_mono': f"{stock:g} / {item.min_stock_level:g} {item.unit}",
                })

    # =========================================================================
    # 2. SEGURIDAD INDUSTRIAL SST Y OPERACIONES
    # =========================================================================
    # 2.1 Órdenes de Trabajo de Alto Riesgo Bloqueadas por SST (role_level >= 50)
    if role_level >= RoleLevel.ENGINEER and organization.is_module_enabled('operations'):
        from apps.operations.models import WorkOrder

        locked_wos = (
            WorkOrder.objects.for_org(organization)
            .filter(is_high_risk=True, sst_cleared=False)
            .exclude(phase__in=[WorkOrder.Phase.COMPLETED, WorkOrder.Phase.CANCELLED])
            .order_by('-created_at')
        )

        for wo in locked_wos:
            try:
                target_url = reverse('operations:workorder_detail', kwargs={'pk': wo.pk})
            except Exception:
                target_url = '/operations/'

            alerts.append({
                'code': 'HIGH_RISK_OT_LOCKED',
                'category': 'OPERATIONS_SST',
                'severity': 'CRITICAL',
                'title': f"OT de Alto Riesgo Sin Liberación SST: {wo.number}",
                'detail': (
                    f"{wo.title} en {wo.site_address or 'Sitio de Obra'}. "
                    f"Trabajo clasificado como crítico sin validación de las 5 reglas de oro / EPP."
                ),
                'target_url': target_url,
                'metric_mono': "SST PENDIENTE",
            })

    # 2.2 Dotación EPP Vencida (MITRAB): Técnicos (20) ven solo su dotación, SST (70+) ven todas
    if organization.is_module_enabled('sst'):
        from apps.sst.models import EPPDelivery

        epp_qs = (
            EPPDelivery.objects.for_org(organization)
            .filter(
                expiration_date__lte=today,
                status__in=[EPPDelivery.Status.ACTIVE, EPPDelivery.Status.EXPIRED],
            )
            .select_related('collaborator')
            .order_by('expiration_date')
        )

        if role_level < RoleLevel.SST_OFFICER:
            epp_qs = epp_qs.filter(collaborator=user)

        for epp in epp_qs:
            try:
                target_url = reverse('sst:epp_list')
            except Exception:
                target_url = '/sst/'

            worker_name = epp.collaborator.get_full_name() or epp.collaborator.email
            alerts.append({
                'code': 'EPP_EXPIRED',
                'category': 'OPERATIONS_SST',
                'severity': 'HIGH',
                'title': f"Dotación EPP Vencida: {epp.code}",
                'detail': (
                    f"{epp.item_name} asignado a {worker_name} venció el "
                    f"{epp.expiration_date.strftime('%d/%m/%Y')}. Requiere renovación y canje inmediato."
                ),
                'target_url': target_url,
                'metric_mono': "RENOVAR EPP",
            })

    # 2.3 Tickets con Compromiso SLA Vencido (role_level >= 50)
    if role_level >= RoleLevel.ENGINEER and organization.is_module_enabled('tickets'):
        from apps.tickets.models import SupportTicket

        breached_tickets = (
            SupportTicket.objects.for_org(organization)
            .filter(
                status__in=[SupportTicket.Status.OPEN, SupportTicket.Status.IN_PROGRESS],
                sla_due_at__lt=now,
            )
            .order_by('sla_due_at')
        )

        for ticket in breached_tickets:
            try:
                target_url = reverse('tickets:ticket_detail', kwargs={'pk': ticket.pk})
            except Exception:
                target_url = '/tickets/'

            alerts.append({
                'code': 'TICKET_SLA_BREACHED',
                'category': 'OPERATIONS_SST',
                'severity': 'CRITICAL',
                'title': f"SLA Excedido en Ticket: {ticket.number}",
                'detail': (
                    f"{ticket.title} excedió su ventana máxima de atención el "
                    f"{ticket.sla_due_at.strftime('%d/%m/%Y %H:%M')}."
                ),
                'target_url': target_url,
                'metric_mono': "SLA VENCIDO",
            })

    # =========================================================================
    # 3. ALERTAS FINANCIERAS, CARTERA CxC Y DGI (ESTRICTAMENTE role_level >= 80)
    # =========================================================================
    if role_level >= RoleLevel.OPERATIONS_COORD:
        # 3.1 Facturas en Mora de Cartera CxC (CRITICAL)
        if organization.is_module_enabled('billing'):
            from apps.billing.models import Invoice

            overdue_invoices = (
                Invoice.objects.for_org(organization)
                .filter(
                    status__in=[Invoice.Status.ISSUED, Invoice.Status.PARTIAL],
                    balance_due__gt=Decimal('0.00'),
                    due_date__lt=today,
                )
                .select_related('account')
                .order_by('due_date')
            )

            for inv in overdue_invoices:
                days_overdue = (today - inv.due_date).days
                client_name = inv.account.commercial_name if inv.account else 'Cliente'
                try:
                    target_url = reverse('billing:invoice_detail', kwargs={'pk': inv.pk})
                except Exception:
                    target_url = '/billing/'

                alerts.append({
                    'code': 'INVOICE_OVERDUE',
                    'category': 'FINANCE_DGI',
                    'severity': 'CRITICAL',
                    'title': f"Factura en Mora de Cartera: {inv.number}",
                    'detail': (
                        f"{client_name} mantiene un saldo vencido de {inv.currency_symbol} {inv.balance_due:,.2f} "
                        f"con {days_overdue} días de retraso fiscal (venció el {inv.due_date.strftime('%d/%m/%Y')})."
                    ),
                    'target_url': target_url,
                    'metric_mono': f"{inv.currency_symbol} {inv.balance_due:,.2f} MORA",
                })

        # 3.2 Órdenes de Compra con Pago a Proveedor Próximo o Vencido (HIGH)
        if organization.is_module_enabled('purchasing'):
            from apps.purchasing.models import PurchaseOrder

            due_purchases = (
                PurchaseOrder.objects.for_org(organization)
                .filter(
                    status__in=[PurchaseOrder.Status.RECEIVED, PurchaseOrder.Status.PARTIAL_PAID],
                    balance_due__gt=Decimal('0.00'),
                    due_date__lte=today + datetime.timedelta(days=5),
                )
                .select_related('supplier')
                .order_by('due_date')
            )

            for po in due_purchases:
                days_diff = (po.due_date - today).days if po.due_date else 0
                if days_diff > 0:
                    due_str = f"vence en {days_diff} días"
                elif days_diff == 0:
                    due_str = "vence hoy"
                else:
                    due_str = f"vencida hace {abs(days_diff)} días"

                supp_name = po.supplier.commercial_name if po.supplier else 'Proveedor'
                try:
                    target_url = reverse('purchasing:order_detail', kwargs={'pk': po.pk})
                except Exception:
                    target_url = '/purchasing/'

                alerts.append({
                    'code': 'PURCHASE_PAYABLE_DUE',
                    'category': 'FINANCE_DGI',
                    'severity': 'HIGH',
                    'title': f"Pago a Proveedor CxP: {po.number}",
                    'detail': (
                        f"Factura {po.supplier_invoice_number or po.number} de {supp_name}. "
                        f"Saldo pendiente: {po.currency_symbol} {po.balance_due:,.2f} ({due_str})."
                    ),
                    'target_url': target_url,
                    'metric_mono': f"{po.currency_symbol} {po.balance_due:,.2f} CxP",
                })

    # =========================================================================
    # 4. ORDENAMIENTO POR SEVERIDAD Y COMPUTACIÓN DE MÉTRICAS
    # =========================================================================
    severity_order = {'CRITICAL': 0, 'HIGH': 1, 'NORMAL': 2}
    alerts.sort(key=lambda a: (severity_order.get(a['severity'], 3), a['code']))

    counts = {
        'total': len(alerts),
        'critical': sum(1 for a in alerts if a['severity'] == 'CRITICAL'),
        'high': sum(1 for a in alerts if a['severity'] == 'HIGH'),
        'by_category': {
            'INVENTORY_FEFO': sum(1 for a in alerts if a['category'] == 'INVENTORY_FEFO'),
            'OPERATIONS_SST': sum(1 for a in alerts if a['category'] == 'OPERATIONS_SST'),
            'FINANCE_DGI': sum(1 for a in alerts if a['category'] == 'FINANCE_DGI'),
        }
    }

    return {
        'alerts': alerts,
        'counts': counts,
    }
