from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.tenancy.models import TenantScopedModel


class SupportTicket(TenantScopedModel):
    """
    Ticket de Incidente Interno / Requerimiento Operativo y de Campo.
    Controla prioridades, tiempos de respuesta (SLA) y vinculación a Órdenes de Trabajo.
    """
    class Category(models.TextChoices):
        VEHICLE_FLEET = 'VEHICLE_FLEET', 'Falla en Vehículo / Flota de Cuadrilla'
        TOOL_EQUIPMENT = 'TOOL_EQUIPMENT', 'Avería de Equipo de Medición / Herramienta'
        IT_SYSTEM = 'IT_SYSTEM', 'Soporte de Sistema / Accesos'
        SST_INCIDENT = 'SST_INCIDENT', 'Incidente / Condición Insegura SST'
        ADMIN_REQ = 'ADMIN_REQ', 'Requerimiento Administrativo / Viáticos'

    class Priority(models.TextChoices):
        LOW = 'LOW', 'Baja (SLA 72h)'
        NORMAL = 'NORMAL', 'Normal (SLA 24h)'
        HIGH = 'HIGH', 'Alta (SLA 12h)'
        CRITICAL = 'CRITICAL', 'Crítica / Emergencia (SLA 4h)'

    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Abierto'
        IN_PROGRESS = 'IN_PROGRESS', 'En Atención'
        RESOLVED = 'RESOLVED', 'Resuelto'
        CLOSED = 'CLOSED', 'Cerrado'

    number = models.CharField(
        max_length=25,
        db_index=True,
        verbose_name="Número de Ticket",
        help_text="Folio de mesa de ayuda (ej: TCK-2026-0001)"
    )
    title = models.CharField(
        max_length=200,
        verbose_name="Título / Asunto del Requerimiento"
    )
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.TOOL_EQUIPMENT,
        verbose_name="Categoría"
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.NORMAL,
        verbose_name="Prioridad y Nivel de Servicio"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        verbose_name="Estado de Atención"
    )
    related_work_order = models.ForeignKey(
        'operations.WorkOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_tickets',
        verbose_name="Orden de Trabajo Vinculada"
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='reported_tickets',
        verbose_name="Reportado Por"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tickets',
        verbose_name="Especialista Asignado"
    )
    description = models.TextField(
        verbose_name="Descripción Detallada del Incidente"
    )
    sla_hours = models.PositiveIntegerField(
        default=24,
        verbose_name="Compromiso SLA (Horas)"
    )
    sla_due_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Vencimiento de SLA"
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha y Hora de Resolución"
    )
    resolution_summary = models.TextField(
        blank=True,
        verbose_name="Dictamen de Resolución / Solución Aplicada"
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Ticket de Soporte"
        verbose_name_plural = "Tickets de Soporte"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.number} · {self.title} ({self.get_status_display()})"

    @property
    def sla_status(self) -> str:
        """
        Retorna el semáforo técnico de SLA:
        - 'COMPLETED': Si el ticket ya fue resuelto o cerrado.
        - 'BREACHED': Si se excedió la fecha límite sla_due_at.
        - 'ON_TIME': Si se encuentra dentro del plazo garantizado.
        """
        if self.status in [self.Status.RESOLVED, self.Status.CLOSED]:
            return 'COMPLETED'
        if self.sla_due_at and timezone.now() > self.sla_due_at:
            return 'BREACHED'
        return 'ON_TIME'

    def save(self, *args, **kwargs):
        # Mapeo estricto de SLA según prioridad
        sla_map = {
            self.Priority.CRITICAL: 4,
            self.Priority.HIGH: 12,
            self.Priority.NORMAL: 24,
            self.Priority.LOW: 72,
        }
        self.sla_hours = sla_map.get(self.priority, 24)

        if not self.sla_due_at:
            self.sla_due_at = timezone.now() + timedelta(hours=self.sla_hours)

        if self.status in [self.Status.RESOLVED, self.Status.CLOSED] and not self.resolved_at:
            self.resolved_at = timezone.now()

        if not self.number and self.organization_id:
            year = timezone.now().year
            count = SupportTicket.objects.filter(
                organization_id=self.organization_id,
                created_at__year=year
            ).count() + 1
            candidate = f"TCK-{year}-{count:04d}"
            while SupportTicket.objects.filter(organization_id=self.organization_id, number=candidate).exists():
                count += 1
                candidate = f"TCK-{year}-{count:04d}"
            self.number = candidate

        super().save(*args, **kwargs)


class TicketComment(TenantScopedModel):
    """
    Bitácora Cronológica de Seguimiento y Colaboración del Ticket.
    """
    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name='comments',
        verbose_name="Ticket"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name="Autor del Comentario"
    )
    message = models.TextField(
        verbose_name="Comentario / Nota Técnica"
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Comentario de Ticket"
        verbose_name_plural = "Comentarios de Tickets"
        ordering = ['created_at']

    def __str__(self):
        return f"{self.ticket.number} · Comentario de {self.author.get_full_name() or self.author.email}"

    def save(self, *args, **kwargs):
        if self.ticket_id and not self.organization_id:
            self.organization_id = self.ticket.organization_id
        super().save(*args, **kwargs)
