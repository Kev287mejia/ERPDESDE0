import json
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView

from apps.tenancy.models import RoleLevel
from apps.tenancy.permissions import ModuleAccessRequiredMixin, render_403_rbac
from .forms import McpAccessTokenCreateForm
from .models import McpAccessToken, McpAuditLog
from .services import (
    MCP_TOOLS_SPEC,
    authenticate_mcp_token,
    execute_mcp_tool,
    generate_mcp_token,
)


@method_decorator(csrf_exempt, name='dispatch')
class McpApiExecuteView(View):
    """
    Endpoint Criptográfico JSON-RPC / REST para el Servidor MCP.
    Soporta autenticación mediante 'Authorization: Bearer <token>' o 'X-MCP-Token'.
    Compatible con la especificación de Claude Desktop y LLMs industriales.
    """
    def post(self, request):
        auth_header = (
            request.headers.get('Authorization')
            or request.META.get('HTTP_AUTHORIZATION')
            or request.headers.get('X-MCP-Token')
            or request.META.get('HTTP_X_MCP_TOKEN')
        )

        token_obj = authenticate_mcp_token(auth_header)
        if not token_obj:
            return JsonResponse({
                'status': 'DENIED',
                'error': 'UNAUTHORIZED',
                'message': 'Token MCP inválido, revocado o expirado. Verifique la cabecera Authorization.'
            }, status=401)

        # Parsear Payload
        try:
            body = json.loads(request.body.decode('utf-8')) if request.body else {}
        except Exception:
            return JsonResponse({
                'status': 'ERROR',
                'error': 'INVALID_JSON',
                'message': 'El cuerpo de la solicitud no es un JSON válido.'
            }, status=400)

        # Extraer herramienta y argumentos (soporta REST simple y JSON-RPC tools/call)
        is_jsonrpc = False
        jsonrpc_id = None
        if body.get('jsonrpc') == '2.0':
            is_jsonrpc = True
            jsonrpc_id = body.get('id')
            method = body.get('method', '')
            if method == 'tools/list':
                # Retornar catálogo de herramientas permitidas para este token
                tools_list = []
                for t_name in token_obj.allowed_tools:
                    spec = MCP_TOOLS_SPEC.get(t_name)
                    if spec:
                        tools_list.append({
                            'name': spec['name'],
                            'description': spec['description'],
                            'inputSchema': {
                                'type': 'object',
                                'properties': spec['parameters']
                            }
                        })
                return JsonResponse({
                    'jsonrpc': '2.0',
                    'id': jsonrpc_id,
                    'result': {'tools': tools_list}
                })

            elif method in ['tools/call', 'tool_call']:
                call_params = body.get('params', {})
                tool_name = call_params.get('name') or call_params.get('tool')
                tool_args = call_params.get('arguments') or call_params.get('params') or {}
            else:
                tool_name = body.get('tool') or method
                tool_args = body.get('params', {})
        else:
            tool_name = body.get('tool') or body.get('name')
            tool_args = body.get('params') or body.get('arguments') or {}

        if not tool_name:
            return JsonResponse({
                'status': 'ERROR',
                'error': 'MISSING_TOOL_NAME',
                'message': "Se requiere especificar el parámetro 'tool' o 'name'."
            }, status=400)

        ip_address = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR')

        # Ejecución Segura
        result = execute_mcp_tool(
            organization=token_obj.organization,
            token_obj=token_obj,
            tool_name=tool_name,
            params=tool_args,
            ip_address=ip_address
        )

        http_status = 200
        if result.get('status') == 'DENIED':
            http_status = 403
        elif result.get('status') == 'ERROR':
            http_status = 400

        if is_jsonrpc:
            if result.get('status') == 'SUCCESS':
                return JsonResponse({
                    'jsonrpc': '2.0',
                    'id': jsonrpc_id,
                    'result': {
                        'content': [{'type': 'text', 'text': json.dumps(result.get('data', {}), ensure_ascii=False)}],
                        'isError': False
                    }
                }, status=http_status)
            else:
                return JsonResponse({
                    'jsonrpc': '2.0',
                    'id': jsonrpc_id,
                    'error': {
                        'code': -32000,
                        'message': result.get('message', 'Error en la llamada MCP'),
                        'data': result
                    }
                }, status=http_status)

        return JsonResponse(result, status=http_status)


class McpConsoleView(ModuleAccessRequiredMixin, TemplateView):
    """
    Consola Web Administrativa del Servidor MCP.
    Permite emitir tokens, revocarlos instantáneamente, auditar logs y probar herramientas en vivo.
    """
    template_name = 'ai_agent/console.html'
    required_module = 'ai_agent'
    min_role_level = RoleLevel.OPERATIONS_COORD

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        role_level = getattr(self.request, 'role_level', 0)

        tokens = McpAccessToken.objects.for_org(org).select_related('created_by').order_by('-created_at')
        audit_logs = McpAuditLog.objects.for_org(org).select_related('token').order_by('-created_at')[:40]

        total_calls = sum(t.total_calls for t in tokens)
        active_tokens = [t for t in tokens if t.is_usable]

        newly_created_token = self.request.session.pop('just_created_mcp_token', None)

        context.update({
            'tokens': tokens,
            'audit_logs': audit_logs,
            'total_calls': total_calls,
            'active_tokens_count': len(active_tokens),
            'tools_spec': MCP_TOOLS_SPEC,
            'token_form': McpAccessTokenCreateForm(max_role_level=role_level),
            'newly_created_token': newly_created_token,
            'can_create_token': role_level >= RoleLevel.OPERATIONS_COORD,
        })
        return context


class McpTokenCreateView(ModuleAccessRequiredMixin, View):
    """
    Emisión Criptográfica de un Nuevo Token MCP.
    """
    required_module = 'ai_agent'
    min_role_level = RoleLevel.OPERATIONS_COORD

    def post(self, request):
        role_level = getattr(request, 'role_level', 0)
        form = McpAccessTokenCreateForm(request.POST, max_role_level=role_level)

        if form.is_valid():
            name = form.cleaned_data['name']
            scoped_role = form.cleaned_data['scoped_role_level']
            allowed_tools = form.cleaned_data['allowed_tools']
            expires_at = form.get_expiration_datetime()

            token_obj, raw_secret = generate_mcp_token(
                organization=request.organization,
                name=name,
                scoped_role_level=scoped_role,
                allowed_tools=allowed_tools,
                created_by=request.user,
                expires_at=expires_at,
            )

            # Almacenar en sesión temporalmente para mostrarlo una única vez
            request.session['just_created_mcp_token'] = {
                'name': token_obj.name,
                'prefix': token_obj.token_prefix,
                'secret': raw_secret,
                'scoped_role': token_obj.get_scoped_role_level_display(),
            }
            messages.success(request, f"Token MCP para '{token_obj.name}' generado exitosamente.")
        else:
            messages.error(request, "Error al generar token. Verifique los campos requeridos.")

        return redirect('ai_agent:console')


class McpTokenToggleActiveView(ModuleAccessRequiredMixin, View):
    """
    Revocación instantánea en 1-clic o reactivación de un token MCP.
    """
    required_module = 'ai_agent'
    min_role_level = RoleLevel.OPERATIONS_COORD

    def post(self, request, pk):
        org = request.organization
        token = get_object_or_404(McpAccessToken.objects.for_org(org), pk=pk)
        token.is_active = not token.is_active
        token.save(update_fields=['is_active', 'updated_at'])

        state = "reactivado" if token.is_active else "revocado de inmediato"
        messages.success(request, f"El token '{token.name}' ha sido {state}.")
        return redirect('ai_agent:console')


class McpSimulatorExecuteView(ModuleAccessRequiredMixin, View):
    """
    Simulador Técnico en Vivo desde la Consola Web.
    Permite probar cualquier herramienta MCP en tiempo real con los datos vivos de la organización.
    """
    required_module = 'ai_agent'
    min_role_level = RoleLevel.OPERATIONS_COORD

    def post(self, request):
        tool_name = request.POST.get('tool_name')
        raw_params = request.POST.get('params', '{}')
        try:
            params = json.loads(raw_params) if raw_params else {}
        except Exception:
            params = {}

        # Usar el primer token activo de la organización o uno temporal con el rol del usuario
        org = request.organization
        token_obj = McpAccessToken.objects.for_org(org).filter(is_active=True).first()
        if not token_obj:
            # Crear un objeto temporal en memoria para la simulación
            token_obj = McpAccessToken(
                organization=org,
                name="Simulador Web",
                token_prefix="sim_web_000...",
                scoped_role_level=request.role_level,
                allowed_tools=list(MCP_TOOLS_SPEC.keys()),
                is_active=True,
            )

        ip = request.META.get('REMOTE_ADDR')
        result = execute_mcp_tool(
            organization=org,
            token_obj=token_obj,
            tool_name=tool_name,
            params=params,
            ip_address=ip
        )
        return JsonResponse(result)
