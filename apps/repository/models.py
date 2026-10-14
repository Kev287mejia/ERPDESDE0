import hashlib
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.tenancy.models import TenantScopedModel, RoleLevel


class RepositoryFolder(TenantScopedModel):
    """
    Carpeta Corporativa Jerárquica con Control de Acceso RBAC.
    Permite restringir la visibilidad (min_role_level_view) y la publicación (min_role_level_upload).
    """
    class Department(models.TextChoices):
        ENGINEERING = 'ENGINEERING', 'Ingeniería y Operaciones'
        SST = 'SST', 'Seguridad e Higiene MITRAB'
        COMMERCIAL = 'COMMERCIAL', 'Comercial y Contratos'
        FINANCE_LEGAL = 'FINANCE_LEGAL', 'Fiscal DGI y Legal'

    code = models.CharField(
        max_length=25,
        db_index=True,
        verbose_name="Código de Carpeta",
        help_text="Identificador único (ej: FLD-ING-01)"
    )
    name = models.CharField(
        max_length=150,
        verbose_name="Nombre de Carpeta"
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subfolders',
        verbose_name="Carpeta Superior"
    )
    department = models.CharField(
        max_length=30,
        choices=Department.choices,
        default=Department.ENGINEERING,
        verbose_name="Departamento Responsable"
    )
    min_role_level_view = models.IntegerField(
        choices=RoleLevel.choices,
        default=RoleLevel.TECHNICIAN,
        help_text="Nivel mínimo requerido para consultar documentos de esta carpeta"
    )
    min_role_level_upload = models.IntegerField(
        choices=RoleLevel.choices,
        default=RoleLevel.ENGINEER,
        help_text="Nivel mínimo requerido para subir o versionar documentos"
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Carpeta de Repositorio"
        verbose_name_plural = "Carpetas de Repositorio"
        ordering = ['code', 'name']

    def __str__(self):
        return f"{self.code} · {self.name}"

    def save(self, *args, **kwargs):
        if not self.code and self.organization_id:
            dept_map = {
                self.Department.ENGINEERING: 'FLD-ING',
                self.Department.SST: 'FLD-SST',
                self.Department.COMMERCIAL: 'FLD-COM',
                self.Department.FINANCE_LEGAL: 'FLD-FIN',
            }
            prefix = dept_map.get(self.department, 'FLD-GEN')
            count = RepositoryFolder.objects.filter(
                organization_id=self.organization_id,
                department=self.department
            ).count() + 1
            candidate = f"{prefix}-{count:02d}"
            while RepositoryFolder.objects.filter(organization_id=self.organization_id, code=candidate).exists():
                count += 1
                candidate = f"{prefix}-{count:02d}"
            self.code = candidate

        super().save(*args, **kwargs)


class CorporateDocument(TenantScopedModel):
    """
    Ficha Maestra del Documento Técnico / Institucional.
    Centraliza el estado vigente, la versión actual y la vinculación a OTs operativas.
    """
    class DocumentType(models.TextChoices):
        CAD_PLAN = 'CAD_PLAN', 'Plano Técnico / Diagrama'
        PROTOCOL = 'PROTOCOL', 'Procedimiento / Protocolo SST'
        CONTRACT = 'CONTRACT', 'Contrato / Licitación'
        TAX_LEGAL = 'TAX_LEGAL', 'Constancia Fiscal DGI / Legal'
        REPORT = 'REPORT', 'Informe de Ingeniería'

    code = models.CharField(
        max_length=25,
        db_index=True,
        verbose_name="Código de Documento",
        help_text="Folio institucional (ej: DOC-2026-0001)"
    )
    folder = models.ForeignKey(
        RepositoryFolder,
        on_delete=models.CASCADE,
        related_name='documents',
        verbose_name="Carpeta Contenedora"
    )
    work_order = models.ForeignKey(
        'operations.WorkOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='repository_documents',
        verbose_name="Orden de Trabajo Relacionada"
    )
    title = models.CharField(
        max_length=200,
        verbose_name="Título del Documento"
    )
    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        default=DocumentType.CAD_PLAN,
        verbose_name="Tipo de Documento"
    )
    current_version_number = models.PositiveIntegerField(
        default=1,
        verbose_name="Versión Vigente"
    )
    latest_filename = models.CharField(
        max_length=255,
        verbose_name="Nombre de Archivo Vigente"
    )
    latest_checksum = models.CharField(
        max_length=64,
        editable=False,
        verbose_name="Checksum SHA-256 Vigente"
    )
    is_locked = models.BooleanField(
        default=False,
        help_text="Bloqueo administrativo contra nuevas versiones"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_corporate_documents',
        verbose_name="Creado Por"
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Documento Corporativo"
        verbose_name_plural = "Documentos Corporativos"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.code} · {self.title} (v{self.current_version_number})"

    def save(self, *args, **kwargs):
        if self.folder_id and not self.organization_id:
            self.organization_id = self.folder.organization_id

        if not self.code and self.organization_id:
            year = timezone.now().year
            count = CorporateDocument.objects.filter(
                organization_id=self.organization_id,
                created_at__year=year
            ).count() + 1
            candidate = f"DOC-{year}-{count:04d}"
            while CorporateDocument.objects.filter(organization_id=self.organization_id, code=candidate).exists():
                count += 1
                candidate = f"DOC-{year}-{count:04d}"
            self.code = candidate

        super().save(*args, **kwargs)


class DocumentVersion(TenantScopedModel):
    """
    Historial Inmutable de Versiones de un Documento.
    Garantiza trazabilidad ISO con estampa de tiempo, autor, log de cambios y sello SHA-256.
    """
    document = models.ForeignKey(
        CorporateDocument,
        on_delete=models.CASCADE,
        related_name='versions',
        verbose_name="Documento Base"
    )
    version_number = models.PositiveIntegerField(
        verbose_name="Número de Versión"
    )
    filename = models.CharField(
        max_length=255,
        verbose_name="Nombre de Archivo"
    )
    file_size_kb = models.PositiveIntegerField(
        default=120,
        verbose_name="Tamaño (KB)"
    )
    content_summary_or_payload = models.TextField(
        blank=True,
        help_text="Contenido técnico/metadatos o referencia de almacenamiento para cálculo SHA-256"
    )
    checksum_sha256 = models.CharField(
        max_length=64,
        editable=False,
        verbose_name="Sello SHA-256"
    )
    change_log = models.TextField(
        verbose_name="Notas de Cambio de la Revisión"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_document_versions',
        verbose_name="Publicado Por"
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Versión de Documento"
        verbose_name_plural = "Versiones de Documentos"
        ordering = ['-version_number']
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'version_number'],
                name='unique_document_version_number'
            )
        ]

    def __str__(self):
        return f"{self.document.code} v{self.version_number} ({self.filename})"

    def clean(self):
        super().clean()
        if self.pk and not self._state.adding:
            raise ValidationError("Las versiones documentales son estrictamente inmutables.")

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise ValidationError("Las versiones documentales son estrictamente inmutables y no admiten actualización.")
        if self.document_id and not self.organization_id:
            self.organization_id = self.document.organization_id
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las versiones documentales son estrictamente inmutables y no pueden eliminarse.")
