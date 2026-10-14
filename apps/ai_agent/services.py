import hashlib
import secrets
import time
from decimal import Decimal
from django.core.exceptions import ValidationError, PermissionDenied
from django.db.models import F, Sum, Q
from django.utils import timezone

from apps.tenancy.models import RoleLevel
from .models import McpAccessToken, McpAuditLog

# Definición de herramientas MCP soportadas y sus umbrales RBAC
MCP_TOOLS_SPEC = {
    'query_workorders': {
        'name': 'query_workorders',
        'title': 'Órdenes de Trabajo Activas & Cuadrillas',
        'description': 'Consulta estado de OTs en curso, avance de obra, cuadrillas y riesgos técnicos.',
        'min_role_level': RoleLevel.TECHNICIAN,  # 20
        'parameters': {
            'phase': {'type': 'string', 'description': 'Fase opcional (DIAGNOSIS, IN_PROGRESS, REVIEW, COMPLETED)'},
            'limit': {'type': 'integer', 'description': 'Límite de registros (máx 50)', 'default': 20},
        }
    },
    'query_inventory_stock': {
        'name': 'query_inventory_stock',
        'title': 'Existencias de Almacén & Alertas de Stock',
        'description': 'Consulta inventario de materiales por bodega y detecta existencias bajo mínimo crítico.',
        'min_role_level': RoleLevel.ENGINEER,  # 50
        'parameters': {
            'low_stock_only': {'type': 'boolean', 'description': 'Filtrar únicamente ítems en nivel de alerta'},
            'warehouse_code': {'type': 'string', 'description': 'Código de bodega específica (opcional)'},
        }
    },
    'query_sst_compliance': {
        'name': 'query_sst_compliance',
        'title': 'Auditoría SST Ley 618 MITRAB',
        'description': 'Verifica OTs bloqueadas por seguridad, checklists obligatorios y permisos laborales.',
        'min_role_level': RoleLevel.SST_OFFICER,  # 70
        'parameters': {
            'days_back': {'type': 'integer', 'description': 'Ventana de días para evaluación (default 30)', 'default': 30},
        }
    },
    'query_sla_tickets': {
        'name': 'query_sla_tickets',
        'title': 'Tickets de Soporte Operativo & SLA',
        'description': 'Métricas de incidentes de flota/equipos y semáforo de vencimiento de compromisos SLA.',
        'min_role_level': RoleLevel.SST_OFFICER,  # 70
        'parameters': {
            'priority': {'type': 'string', 'description': 'Filtrar por prioridad (CRITICAL, HIGH, NORMAL, LOW)'},
            'status': {'type': 'string', 'description': 'Filtrar por estado (OPEN, IN_PROGRESS, RESOLVED, CLOSED)'},
        }
    },
    'query_financial_summary': {
        'name': 'query_financial_summary',
        'title': 'Resumen Financiero Ejecutivo & Tesorería',
        'description': 'Saldos consolidados de cuentas bancarias, arqueos de cajas chicas y volumen de cotizaciones.',
        'min_role_level': RoleLevel.OPERATIONS_COORD,  # 80
        'parameters': {
            'include_quotes': {'type': 'boolean', 'description': 'Incluir pipeline de cotizaciones abiertas', 'default': True},
        }
    },
}

ALL_TOOL_NAMES = list(MCP_TOOLS_SPEC.keys())


def generate_mcp_token(
    organization,
    name: str,
    scoped_role_level: int,
    allowed_tools: list[str],
    created_by=None,
    expires_at=None
) -> tuple[McpAccessToken, str]:
    """
    Genera un token secreto para agente MCP en formato 'etn_mcp_<hex32>'.
    Almacena únicamente el hash SHA-256 en base de datos.
    Retorna la tupla (McpAccessToken, raw_secret_token). El secreto solo existe aquí una única vez.
    """
    clean_name = (name or '').strip()
    if not clean_name:
        raise ValidationError("El token requiere un nombre descriptivo para trazabilidad.")

    # Validar que las herramientas sean reconocidas
    valid_tools = [t for t in (allowed_tools or []) if t in MCP_TOOLS_SPEC]
    if not valid_tools:
        valid_tools = ALL_TOOL_NAMES.copy()

    # Si se especifica created_by, el token no puede superar su rol jerárquico
    creator_level = getattr(created_by, 'role_level', None)
    if creator_level is not None and scoped_role_level > creator_level:
        scoped_role_level = creator_level

    # Generación de secreto criptográfico
    raw_secret = f"etn_mcp_{secrets.token_hex(16)}"
    prefix = f"{raw_secret[:12]}..."
    token_hash = hashlib.sha256(raw_secret.encode('utf-8')).hexdigest()

    token_obj = McpAccessToken.objects.create(
        organization=organization,
        name=clean_name,
        token_prefix=prefix,
        token_hash=token_hash,
        scoped_role_level=scoped_role_level,
        allowed_tools=valid_tools,
        is_active=True,
        expires_at=expires_at,
        created_by=created_by,
    )

    return token_obj, raw_secret


def authenticate_mcp_token(raw_token: str) -> McpAccessToken | None:
    """
    Valida un token secreto recibido por cabecera HTTP.
    Calcula el hash SHA-256 y verifica estado activo y expiración.
    """
    if not raw_token:
        return None

    clean_raw = raw_token.strip()
    # Permitir prefijos tipo 'Bearer '
    if clean_raw.lower().startswith('bearer '):
        clean_raw = clean_raw[7:].strip()

    token_hash = hashlib.sha256(clean_raw.encode('utf-8')).hexdigest()
    try:
        token_obj = McpAccessToken.objects.select_related('organization').get(token_hash=token_hash)
        if token_obj.is_usable:
            return token_obj
        return None
    except McpAccessToken.DoesNotExist:
        return None


def execute_mcp_tool(
    organization,
    token_obj: McpAccessToken,
    tool_name: str,
    params: dict = None,
    ip_address: str = None
) -> dict:
    """
    Ejecuta una herramienta del servidor MCP en el contexto del Tenant.
    Aplica verificación estricta de lista blanca y autorización jerárquica RBAC.
    Registra el evento de auditoría inmutable en McpAuditLog.
    """
    start_time = time.monotonic()
    params = params or {}

    # 1. Verificar si la herramienta existe
    tool_spec = MCP_TOOLS_SPEC.get(tool_name)
    if not tool_spec:
        duration_ms = max(1, int((time.monotonic() - start_time) * 1000))
        McpAuditLog.objects.create(
            organization=organization,
            token=token_obj,
            tool_name=tool_name,
            request_payload=params,
            response_status=McpAuditLog.ResponseStatus.ERROR,
            execution_ms=duration_ms,
            ip_address=ip_address,
            error_message="Herramienta MCP desconocida o no soportada."
        )
        return {
            'status': 'ERROR',
            'error': 'TOOL_NOT_FOUND',
            'message': f"La herramienta '{tool_name}' no existe en el catálogo MCP."
        }

    # 2. Verificar si está permitida en este token específico
    if tool_name not in (token_obj.allowed_tools or []):
        duration_ms = max(1, int((time.monotonic() - start_time) * 1000))
        McpAuditLog.objects.create(
            organization=organization,
            token=token_obj,
            tool_name=tool_name,
            request_payload=params,
            response_status=McpAuditLog.ResponseStatus.DENIED,
            execution_ms=duration_ms,
            ip_address=ip_address,
            error_message=f"La herramienta '{tool_name}' no está habilitada en la lista blanca de este token."
        )
        return {
            'status': 'DENIED',
            'error': 'TOOL_NOT_ALLOWED',
            'message': f"Este token no tiene permiso para invocar '{tool_name}'."
        }

    # 3. Validación de Autoridad Jerárquica RBAC
    required_level = tool_spec['min_role_level']
    if token_obj.scoped_role_level < required_level:
        duration_ms = max(1, int((time.monotonic() - start_time) * 1000))
        reason = (
            f"Acceso denegado por RBAC: '{tool_name}' requiere nivel jerárquico {required_level}+ "
            f"pero el token posee autorización hasta nivel {token_obj.scoped_role_level}."
        )
        McpAuditLog.objects.create(
            organization=organization,
            token=token_obj,
            tool_name=tool_name,
            request_payload=params,
            response_status=McpAuditLog.ResponseStatus.DENIED,
            execution_ms=duration_ms,
            ip_address=ip_address,
            error_message=reason
        )
        return {
            'status': 'DENIED',
            'error': 'RBAC_INSUFFICIENT_LEVEL',
            'required_role_level': required_level,
            'token_role_level': token_obj.scoped_role_level,
            'message': reason
        }

    # 4. Ejecución Concreta de Herramientas Operativas
    try:
        data = {}
        if tool_name == 'query_workorders':
            from apps.operations.models import WorkOrder
            limit = min(50, max(1, int(params.get('limit', 20))))
            qs = WorkOrder.objects.for_org(organization).select_related(
                'assigned_crew', 'assigned_engineer', 'account'
            )
            phase = params.get('phase')
            if phase:
                qs = qs.filter(phase=phase)
            else:
                qs = qs.exclude(phase=WorkOrder.Phase.COMPLETED)

            results = []
            for wo in qs[:limit]:
                results.append({
                    'code': wo.code,
                    'title': wo.title,
                    'phase': wo.phase,
                    'priority': wo.priority,
                    'account_name': wo.account.commercial_name if wo.account else None,
                    'crew_name': wo.assigned_crew.name if wo.assigned_crew else None,
                    'engineer_name': wo.assigned_engineer.get_full_name() if wo.assigned_engineer else None,
                    'is_high_risk': wo.is_high_risk,
                    'sst_cleared': wo.sst_cleared,
                })
            data = {'total_count': len(results), 'work_orders': results}

        elif tool_name == 'query_inventory_stock':
            from apps.inventory.models import InventoryItem
            low_stock_only = bool(params.get('low_stock_only', False))
            items_qs = InventoryItem.objects.for_org(organization).prefetch_related('balances__warehouse')

            items_list = []
            for item in items_qs:
                total_stock = sum(b.quantity for b in item.balances.all())
                is_low = total_stock <= item.min_stock_alert
                if low_stock_only and not is_low:
                    continue
                items_list.append({
                    'code': item.code,
                    'name': item.name,
                    'unit': item.unit,
                    'total_stock': float(total_stock),
                    'min_stock_alert': float(item.min_stock_alert),
                    'is_low_stock': is_low,
                })
            data = {'total_items': len(items_list), 'items': items_list}

        elif tool_name == 'query_sst_compliance':
            from apps.operations.models import WorkOrder
            from apps.sst.models import SafetyChecklist, LeaveRequest

            high_risk_open = WorkOrder.objects.for_org(organization).filter(
                is_high_risk=True
            ).exclude(phase=WorkOrder.Phase.COMPLETED).count()

            blocked_by_sst = WorkOrder.objects.for_org(organization).filter(
                sst_cleared=False
            ).exclude(phase=WorkOrder.Phase.COMPLETED).count()

            recent_checklists = SafetyChecklist.objects.for_org(organization).count()
            pending_leaves = LeaveRequest.objects.for_org(organization).filter(
                status='PENDING'
            ).count()

            data = {
                'high_risk_open_orders': high_risk_open,
                'orders_blocked_missing_sst': blocked_by_sst,
                'total_safety_checklists_filed': recent_checklists,
                'pending_leave_requests_mitrab': pending_leaves,
                'compliance_status': 'REQUIRES_ATTENTION' if blocked_by_sst > 0 else 'COMPLIANT'
            }

        elif tool_name == 'query_sla_tickets':
            from apps.tickets.models import SupportTicket
            qs = SupportTicket.objects.for_org(organization)
            priority = params.get('priority')
            status = params.get('status')
            if priority:
                qs = qs.filter(priority=priority)
            if status:
                qs = qs.filter(status=status)

            all_t = list(qs)
            open_t = [t for t in all_t if t.status in [SupportTicket.Status.OPEN, SupportTicket.Status.IN_PROGRESS]]
            critical_t = [t for t in open_t if t.priority == SupportTicket.Priority.CRITICAL]
            breached_t = [t for t in open_t if t.sla_status == 'BREACHED']

            tickets_summary = []
            for t in open_t[:10]:
                tickets_summary.append({
                    'number': t.number,
                    'title': t.title,
                    'priority': t.priority,
                    'status': t.status,
                    'sla_hours': t.sla_hours,
                    'sla_status': t.sla_status,
                    'reported_by': t.reported_by.get_full_name() if t.reported_by else t.reported_by.email,
                })

            data = {
                'total_open': len(open_t),
                'critical_in_progress': len(critical_t),
                'sla_breached': len(breached_t),
                'urgent_tickets': tickets_summary
            }

        elif tool_name == 'query_financial_summary':
            from apps.finance.models import BankAccount, PettyCashFund
            from apps.crm.models import Quote

            bank_accounts = list(BankAccount.objects.for_org(organization).values('account_number', 'bank_name', 'currency', 'current_balance'))
            funds = list(PettyCashFund.objects.for_org(organization).values('code', 'name', 'allocated_amount', 'current_balance'))
            open_quotes = Quote.objects.for_org(organization).filter(status__in=['DRAFT', 'SENT'])
            quotes_total = open_quotes.aggregate(total=Sum('grand_total'))['total'] or Decimal('0.00')

            data = {
                'bank_accounts': [
                    {
                        'account_number': b['account_number'],
                        'bank_name': b['bank_name'],
                        'currency': b['currency'],
                        'current_balance': float(b['current_balance'])
                    } for b in bank_accounts
                ],
                'petty_cash_funds': [
                    {
                        'code': f['code'],
                        'name': f['name'],
                        'allocated_amount': float(f['allocated_amount']),
                        'current_balance': float(f['current_balance'])
                    } for f in funds
                ],
                'open_quotes_count': open_quotes.count(),
                'open_quotes_pipeline_total': float(quotes_total),
            }

        duration_ms = max(1, int((time.monotonic() - start_time) * 1000))

        # Registrar auditoría exitosa
        McpAuditLog.objects.create(
            organization=organization,
            token=token_obj,
            tool_name=tool_name,
            request_payload=params,
            response_status=McpAuditLog.ResponseStatus.SUCCESS,
            execution_ms=duration_ms,
            ip_address=ip_address,
        )

        # Actualizar telemetría del token
        McpAccessToken.objects.filter(pk=token_obj.pk).update(
            last_used_at=timezone.now(),
            total_calls=F('total_calls') + 1
        )

        return {
            'status': 'SUCCESS',
            'tool': tool_name,
            'execution_ms': duration_ms,
            'data': data
        }

    except Exception as e:
        duration_ms = max(1, int((time.monotonic() - start_time) * 1000))
        err_msg = str(e)
        McpAuditLog.objects.create(
            organization=organization,
            token=token_obj,
            tool_name=tool_name,
            request_payload=params,
            response_status=McpAuditLog.ResponseStatus.ERROR,
            execution_ms=duration_ms,
            ip_address=ip_address,
            error_message=err_msg
        )
        return {
            'status': 'ERROR',
            'error': 'EXECUTION_EXCEPTION',
            'message': err_msg
        }
