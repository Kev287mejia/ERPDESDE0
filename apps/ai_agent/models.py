from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.tenancy.models import TenantScopedModel, RoleLevel


class McpAccessToken(TenantScopedModel):
    """
    Credencial Criptográfica Revocable para Agentes de Inteligencia Artificial (MCP).
    Almacena únicamente el hash SHA-256 del token secreto generado.
    Define un límite jerárquico de autoridad (scoped_role_level) y una lista blanca de herramientas.
    """
    name = models.CharField(
        max_length=150,
        verbose_name="Nombre del Cliente / Agente IA",
        help_text="Identificador descriptivo (ej: 'Claude Desktop - Dirección Operativa')"
    )
    token_prefix = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="Prefijo Visible del Token",
        help_text="Primeros 12 caracteres visibles para auditoría técnica (ej: etn_mcp_9a8f...)"
    )
    token_hash = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name="Hash SHA-256",
        help_text="Sello criptográfico del token completo. El secreto nunca se almacena en plano."
    )
    scoped_role_level = models.IntegerField(
        choices=RoleLevel.choices,
        default=RoleLevel.OPERATIONS_COORD,
        verbose_name="Nivel de Autoridad Máxima",
        help_text="Techo de permisos RBAC asignado a este token para consultas al ERP."
    )
    allowed_tools = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Herramientas Habilitadas",
        help_text="Lista de herramientas autorizadas (ej: ['query_workorders', 'query_inventory_stock'])"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Token Activo",
        help_text="Permite la revocación instantánea en 1-clic ante sospecha de filtración."
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de Expiración",
        help_text="Caducidad automática opcional para sesiones temporales."
    )
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Última Invocación"
    )
    total_calls = models.PositiveIntegerField(
        default=0,
        verbose_name="Total de Llamadas Registradas"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_mcp_tokens',
        verbose_name="Creado Por"
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Token de Acceso MCP"
        verbose_name_plural = "Tokens de Acceso MCP"
        ordering = ['-created_at']

    def __str__(self):
        status_str = "ACTIVO" if self.is_active else "REVOCADO"
        return f"{self.name} [{self.token_prefix}] ({status_str})"

    @property
    def is_expired(self) -> bool:
        if self.expires_at and timezone.now() > self.expires_at:
            return True
        return False

    @property
    def is_usable(self) -> bool:
        return self.is_active and not self.is_expired


class McpAuditLog(TenantScopedModel):
    """
    Registro Inmutable de Telemetría y Auditoría de Llamadas al Servidor MCP.
    Garantiza trazabilidad de cada consulta ejecutada por agentes LLM en la organización.
    """
    class ResponseStatus(models.TextChoices):
        SUCCESS = 'SUCCESS', 'Exitoso'
        DENIED = 'DENIED', 'Denegado por RBAC'
        ERROR = 'ERROR', 'Error de Ejecución'

    token = models.ForeignKey(
        McpAccessToken,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name="Token Utilizado"
    )
    tool_name = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name="Herramienta MCP Invocada"
    )
    request_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Parámetros de Solicitud"
    )
    response_status = models.CharField(
        max_length=20,
        choices=ResponseStatus.choices,
        default=ResponseStatus.SUCCESS,
        verbose_name="Estado de Respuesta"
    )
    execution_ms = models.PositiveIntegerField(
        default=0,
        verbose_name="Tiempo de Ejecución (ms)"
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name="Dirección IP de Origen"
    )
    error_message = models.TextField(
        blank=True,
        verbose_name="Detalle de Error / Razón de Rechazo"
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Registro de Auditoría MCP"
        verbose_name_plural = "Registros de Auditoría MCP"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.tool_name} [{self.response_status}] - {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}"

    def clean(self):
        super().clean()
        if self.pk and not self._state.adding:
            raise ValidationError("Los registros de auditoría MCP son estrictamente inmutables.")

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise ValidationError("Los registros de auditoría MCP son estrictamente inmutables y no admiten modificaciones.")
        if self.token_id and not self.organization_id:
            self.organization_id = self.token.organization_id
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los registros de auditoría MCP son inmutables y no pueden ser eliminados individualmente.")
