from django.urls import path
from . import views

app_name = 'ai_agent'

urlpatterns = [
    # Endpoint Oficial JSON-RPC / REST para clientes MCP y LLMs
    path('v1/execute/', views.McpApiExecuteView.as_view(), name='api_execute'),
    path('execute/', views.McpApiExecuteView.as_view(), name='mcp_execute'),

    # Consola Web Administrativa y Gestión de Tokens
    path('console/', views.McpConsoleView.as_view(), name='console'),
    path('tokens/create/', views.McpTokenCreateView.as_view(), name='token_create'),
    path('tokens/<uuid:pk>/toggle/', views.McpTokenToggleActiveView.as_view(), name='token_toggle'),
    path('simulator/execute/', views.McpSimulatorExecuteView.as_view(), name='simulator_execute'),
]
