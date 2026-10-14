from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.tenancy.models import TenantScopedModel, RoleLevel


class SafetyChecklist(TenantScopedModel):
    """
    Inspección / Lista de Chequeo Pre-Operacional en Campo.
    Control de seguridad industrial de campo obligatorio antes de maniobras en sitio.
    """
    class WorkType(models.TextChoices):
        ELECTRICAL = 'ELECTRICAL', 'Riesgo Eléctrico / Media y Baja Tensión'
        HEIGHTS = 'HEIGHTS', 'Trabajo en Alturas (> 1.80m)'
        CONFINED = 'CONFINED', 'Espacios Confinados'
        HOT_WORK = 'HOT_WORK', 'Trabajo en Caliente / Soldadura'
        GENERAL = 'GENERAL', 'Mantenimiento General Mecánico/Civil'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendiente de Validación SST'
        APPROVED = 'APPROVED', 'Aprobado y Liberado'
        REJECTED = 'REJECTED', 'Rechazado / Detención de Labor'

    number = models.CharField(
        max_length=25,
        db_index=True,
        verbose_name="Folio de Checklist",
        help_text="ej: CHK-2026-0001",
    )
    work_order = models.ForeignKey(
        'operations.WorkOrder',
        on_delete=models.CASCADE,
        related_name='safety_checklists',
        verbose_name="Orden de Trabajo",
    )
    crew = models.ForeignKey(
        'operations.Crew',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='safety_checklists',
        verbose_name="Cuadrilla de Campo",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='submitted_checklists',
        verbose_name="Reportado Por (Técnico / Líder)",
    )
    work_type = models.CharField(
        max_length=30,
        choices=WorkType.choices,
        default=WorkType.GENERAL,
        verbose_name="Tipo de Riesgo Operativo",
    )

    # 5 Verificaciones Técnicas Obligatorias
    epp_verified = models.BooleanField(
        default=False,
        verbose_name="Verificación de EPP completo por integrante de cuadrilla",
    )
    loto_verified = models.BooleanField(
        default=False,
        verbose_name="Aislamiento de energía / Bloqueo y Etiquetado (LOTO) aplicado",
    )
    tools_inspected = models.BooleanField(
        default=False,
        verbose_name="Herramientas y equipos de medición en buen estado",
    )
    area_signaled = models.BooleanField(
        default=False,
        verbose_name="Área de trabajo delimitada, limpia y señalizada",
    )
    risk_briefing_done = models.BooleanField(
        default=False,
        verbose_name="Charla pre-operacional de 5 minutos impartida en sitio",
    )

    hazard_notes = models.TextField(
        blank=True,
        verbose_name="Condiciones Inseguras o Hallazgos Detectados",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name="Estado de Dictamen SST",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_checklists',
        verbose_name="Oficial SST Validador",
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha y Hora de Validación SST",
    )
    review_comments = models.TextField(
        blank=True,
        verbose_name="Observaciones / Dictamen de Seguridad",
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Checklist Pre-Operacional"
        verbose_name_plural = "Checklists Pre-Operacionales"
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'number'],
                name='unique_safety_checklist_number_per_tenant'
            )
        ]

    def __str__(self) -> str:
        return f"{self.number} · {self.work_order.number} · {self.get_work_type_display()} [{self.get_status_display()}]"

    def all_checks_passed(self) -> bool:
        """Retorna True si todas las 5 verificaciones críticas fueron marcadas como cumplidas."""
        return all([
            self.epp_verified,
            self.loto_verified,
            self.tools_inspected,
            self.area_signaled,
            self.risk_briefing_done,
        ])

    def save(self, *args, **kwargs):
        if self.work_order_id and not self.organization_id:
            self.organization_id = self.work_order.organization_id

        if not self.number and self.organization_id:
            year = timezone.now().year
            count = SafetyChecklist.objects.filter(
                organization_id=self.organization_id,
                number__startswith=f"CHK-{year}-"
            ).count() + 1
            candidate = f"CHK-{year}-{count:04d}"
            while SafetyChecklist.objects.filter(organization_id=self.organization_id, number=candidate).exists():
                count += 1
                candidate = f"CHK-{year}-{count:04d}"
            self.number = candidate

        super().save(*args, **kwargs)


class EPPDelivery(TenantScopedModel):
    """
    Registro de Entrega de Equipos de Protección Personal y Dotación (Normativa MITRAB).
    Control individualizado de entrega, vigencia y confirmación de recepción.
    """
    class Category(models.TextChoices):
        HEAD = 'HEAD', 'Protección Craneal (Casco Dieléctrico)'
        EYES = 'EYES', 'Protección Visual / Facial'
        HANDS = 'HANDS', 'Protección de Manos (Guantes)'
        FEET = 'FEET', 'Calzado de Seguridad / Dieléctrico'
        FALL = 'FALL', 'Protección contra Caídas (Arnés / Eslinga)'
        UNIFORM = 'UNIFORM', 'Dotación / Ropa de Trabajo Ignífuga'

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Vigente en Uso'
        EXPIRED = 'EXPIRED', 'Vencido / Requiere Cambio'
        REPLACED = 'REPLACED', 'Reemplazado por Deterioro'

    code = models.CharField(
        max_length=25,
        db_index=True,
        verbose_name="Código de Entrega EPP",
        help_text="ej: EPP-2026-0001",
    )
    collaborator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='epp_deliveries',
        verbose_name="Colaborador Receptor",
    )
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.HEAD,
        verbose_name="Categoría de Protección",
    )
    item_name = models.CharField(
        max_length=150,
        verbose_name="Nombre / Especificación del EPP",
        help_text="ej: Casco Dieléctrico Clase E 20kV con Barbiquejo",
    )
    serial_or_batch = models.CharField(
        max_length=60,
        blank=True,
        verbose_name="Lote / Número de Serie",
        help_text="ej: LOTE-3M-9941",
    )
    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name="Cantidad Entregada",
    )
    delivery_date = models.DateField(
        verbose_name="Fecha de Entrega",
    )
    expiration_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de Vencimiento / Renovación",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name="Estado de Vigencia",
    )
    acknowledged_by_worker = models.BooleanField(
        default=False,
        verbose_name="Recepción Confirmada por Colaborador",
    )
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_epps',
        verbose_name="Entregado Por (Oficial SST)",
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Entrega de EPP / Dotación"
        verbose_name_plural = "Entregas de EPP y Dotación"
        ordering = ['-delivery_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'code'],
                name='unique_epp_delivery_code_per_tenant'
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} · {self.collaborator.full_name or self.collaborator.email} · {self.item_name}"

    def is_expired(self) -> bool:
        """Determina si la dotación sobrepasó su fecha límite de vida útil."""
        if self.expiration_date:
            return self.expiration_date < timezone.now().date()
        return False

    def save(self, *args, **kwargs):
        if not self.code and self.organization_id:
            year = timezone.now().year
            count = EPPDelivery.objects.filter(
                organization_id=self.organization_id,
                code__startswith=f"EPP-{year}-"
            ).count() + 1
            candidate = f"EPP-{year}-{count:04d}"
            while EPPDelivery.objects.filter(organization_id=self.organization_id, code=candidate).exists():
                count += 1
                candidate = f"EPP-{year}-{count:04d}"
            self.code = candidate

        super().save(*args, **kwargs)


class LeaveRequest(TenantScopedModel):
    """
    Solicitud Formal de Permiso Laboral / Ausencia Justificada.
    Gobernanza con regla estricta anti-inversión de mando.
    """
    class LeaveType(models.TextChoices):
        MEDICAL = 'MEDICAL', 'Subsidio / Reposo Médico INSS'
        VACATION = 'VACATION', 'Vacaciones Descansadas'
        PERSONAL = 'PERSONAL', 'Permiso Personal'
        CALAMITY = 'CALAMITY', 'Calamidad Doméstica'
        TRAINING = 'TRAINING', 'Capacitación / Certificación Técnica'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendiente de Autorización'
        APPROVED = 'APPROVED', 'Autorizado'
        REJECTED = 'REJECTED', 'Rechazado'

    number = models.CharField(
        max_length=25,
        db_index=True,
        verbose_name="Folio de Solicitud",
        help_text="ej: PER-2026-0001",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='leave_requests',
        verbose_name="Colaborador Solicitante",
    )
    requester_role_level = models.IntegerField(
        help_text="Snapshot del nivel jerárquico del solicitante al momento de crear la solicitud",
        verbose_name="Nivel Jerárquico Solicitante",
    )
    leave_type = models.CharField(
        max_length=30,
        choices=LeaveType.choices,
        default=LeaveType.PERSONAL,
        verbose_name="Tipo de Permiso",
    )
    start_date = models.DateField(
        verbose_name="Fecha de Inicio",
    )
    end_date = models.DateField(
        verbose_name="Fecha de Conclusión",
    )
    days_requested = models.PositiveIntegerField(
        default=1,
        verbose_name="Total de Días Solicitados",
    )
    reason = models.TextField(
        verbose_name="Motivo y Justificación",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name="Estado de la Solicitud",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_leaves',
        verbose_name="Autorizador / Resolutor",
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de Dictamen",
    )
    resolution_notes = models.TextField(
        blank=True,
        verbose_name="Notas de Dictamen / Razón de Rechazo",
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Solicitud de Permiso Laboral"
        verbose_name_plural = "Solicitudes de Permiso Laboral"
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'number'],
                name='unique_leave_request_number_per_tenant'
            )
        ]

    def __str__(self) -> str:
        return f"{self.number} · {self.requester.full_name or self.requester.email} · {self.get_leave_type_display()} [{self.get_status_display()}]"

    def can_be_reviewed_by(self, user, reviewer_role_level: int) -> tuple[bool, str]:
        """
        Regla Estricta Anti-Inversión de Mando en Permisos Laborales:
        1. Ningún colaborador puede aprobar su propia solicitud (salvo si es superadmin/owner explícito).
        2. Mínimo Nivel 70 (SST_OFFICER).
        3. El autorizador DEBE tener nivel jerárquico ESTRICTAMENTE MAYOR al solicitante
           (approver_level > requester_level), con excepción de OWNER_ADMIN (100).
        """
        if self.requester_id == user.id and reviewer_role_level < RoleLevel.OWNER_ADMIN:
            return False, "Ningún colaborador puede autorizar o rechazar su propia solicitud de permiso."

        if reviewer_role_level < RoleLevel.SST_OFFICER:
            return False, "Se requiere autoridad mínima de Oficial SST (Nivel 70) para resolver permisos laborales."

        if reviewer_role_level < RoleLevel.OWNER_ADMIN and reviewer_role_level <= self.requester_role_level:
            return False, "Jerarquía insuficiente: no puede autorizar o rechazar solicitudes de un rol igual o superior al suyo."

        return True, "Autorizado"

    def save(self, *args, **kwargs):
        if not self.number and self.organization_id:
            year = timezone.now().year
            count = LeaveRequest.objects.filter(
                organization_id=self.organization_id,
                number__startswith=f"PER-{year}-"
            ).count() + 1
            candidate = f"PER-{year}-{count:04d}"
            while LeaveRequest.objects.filter(organization_id=self.organization_id, number=candidate).exists():
                count += 1
                candidate = f"PER-{year}-{count:04d}"
            self.number = candidate

        super().save(*args, **kwargs)
