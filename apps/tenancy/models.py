from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from apps.core.models import TimeStampedModel
from apps.tenancy.constants import MODULE_THRESHOLD_MAP


class Organization(TimeStampedModel):
    """
    Representa el Tenant u Organización aislada en la plataforma SaaS.
    Cada cliente corporativo opera de manera aislada dentro de su organización.
    """
    class Currency(models.TextChoices):
        NIO = 'NIO', 'Córdoba Nicaragüense (C$)'
        USD = 'USD', 'Dólar Estadounidense ($)'

    class TaxRegime(models.TextChoices):
        GENERAL = 'GENERAL', 'Régimen General DGI (IR Anual + Retenciones)'
        SIMPLIFIED = 'SIMPLIFIED', 'Régimen Simplificado / Cuota Fija'
        SPECIAL = 'SPECIAL', 'Régimen Especial / Gran Contribuyente / Zona Franca'

    class Industry(models.TextChoices):
        SERVICES = 'SERVICES', 'Servicios Industriales & Mantenimiento Especializado'
        CONSTRUCTION = 'CONSTRUCTION', 'Construcción, Ingeniería & Obras Civiles'
        ENERGY_TELCO = 'ENERGY_TELCO', 'Energía, Redes Eléctricas & Telecomunicaciones'
        COMMERCE = 'COMMERCE', 'Comercio, Distribución & Suministros'
        MANUFACTURING = 'MANUFACTURING', 'Manufactura, Agroindustria & Procesamiento'
        TECHNOLOGY = 'TECHNOLOGY', 'Tecnología, Software & Servicios IT'
        MARKETING = 'MARKETING', 'Marketing Digital, Medios & Publicidad'
        OTHER = 'OTHER', 'Otros Giros Comerciales / Corporativo'

    class AccountingTemplate(models.TextChoices):
        NIIF_PYMES = 'NIIF_PYMES', 'Catálogo Estándar NIIF para PYMES (Nicaragua DGI)'
        SIMPLIFIED = 'SIMPLIFIED', 'Catálogo Simplificado de Servicios y Flujo de Fondos'
        BLANK = 'BLANK', 'Catálogo en Blanco (Configuración Manual)'

    name = models.CharField(
        max_length=150,
        verbose_name="Nombre Comercial",
        help_text="Nombre de marca o fantasía de la empresa (ej: Soluciones Industriales S.A.)"
    )
    legal_name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Razón Social",
        help_text="Nombre legal registrado ante las autoridades tributarias"
    )
    tax_id = models.CharField(
        max_length=50,
        db_index=True,
        verbose_name="Identificación Fiscal",
        help_text="Número de RUC, RTN, NIT o Cédula Jurídica según el país"
    )
    country = models.ForeignKey(
        'core.CountryConfig',
        on_delete=models.PROTECT,
        related_name='organizations',
        verbose_name="País de Operación Principal",
        help_text="Define la normativa fiscal, moneda y validaciones del Tenant"
    )
    currency = models.CharField(
        max_length=10,
        choices=Currency.choices,
        default=Currency.NIO,
        verbose_name="Moneda Principal Operativa",
        help_text="Moneda base para balances, cotizaciones y reportes"
    )
    tax_regime = models.CharField(
        max_length=30,
        choices=TaxRegime.choices,
        default=TaxRegime.GENERAL,
        verbose_name="Régimen Fiscal DGI",
        help_text="Régimen tributario de la empresa ante la DGI"
    )
    industry = models.CharField(
        max_length=40,
        choices=Industry.choices,
        default=Industry.SERVICES,
        verbose_name="Giro / Rubro Comercial",
        help_text="Sector o actividad económica principal"
    )
    accounting_template = models.CharField(
        max_length=30,
        choices=AccountingTemplate.choices,
        default=AccountingTemplate.NIIF_PYMES,
        verbose_name="Plan Contable Inicial",
        help_text="Plantilla de catálogo de cuentas y estructura financiera"
    )
    slug = models.SlugField(
        max_length=100,
        unique=True,
        db_index=True,
        verbose_name="Slug / Identificador URL",
        help_text="Identificador único en minúsculas y guiones para subdominios o URLs"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Organización Activa",
        help_text="Permite deshabilitar el acceso completo a la organización por mora o suspensión"
    )
    onboarding_completed = models.BooleanField(
        default=False,
        verbose_name="Onboarding Completado",
        help_text="Indica si la organización culminó su configuración inicial de datos y módulos"
    )
    enabled_modules = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Módulos Habilitados",
        help_text="Lista de códigos de módulos contratados (ej: ['crm', 'operations', 'sst', 'inventory'])"
    )

    class Meta:
        verbose_name = "Organización (Tenant)"
        verbose_name_plural = "Organizaciones (Tenants)"
        ordering = ['name']

    @property
    def currency_symbol(self) -> str:
        return 'C$' if self.currency == self.Currency.NIO else '$'

    def __str__(self) -> str:
        return f"{self.name} ({self.country.code})"

    def clean(self):
        super().clean()
        if self.tax_id and self.country_id:
            if hasattr(self, 'country') and not self.country.validate_tax_id(self.tax_id):
                raise ValidationError({
                    'tax_id': (
                        f"El formato del {self.country.tax_id_label} no es válido "
                        f"para {self.country.name}."
                    )
                })

    def is_module_enabled(self, module_code: str) -> bool:
        """Determina si un módulo específico está suscrito y habilitado para este Tenant."""
        if not self.is_active or not self.enabled_modules:
            return False
        return module_code.lower().strip() in [m.lower().strip() for m in self.enabled_modules]


class RoleLevel(models.IntegerChoices):
    """
    Escala jerárquica estricta de autoridad RBAC.
    Garantiza que la lógica de aprobación y permisos siempre siga una progresión numérica.
    Previene inversiones o colisiones entre roles operativos.
    """
    OBSERVER = 10, 'Observador / Auditor'
    TECHNICIAN = 20, 'Técnico de Campo'
    ENGINEER = 50, 'Ingeniero Residente / Supervisor'
    SST_OFFICER = 70, 'Oficial SST (Seguridad y Salud)'
    OPERATIONS_COORD = 80, 'Coordinador Operativo'
    COMMERCIAL_MGR = 85, 'Gerente Comercial'
    OWNER_ADMIN = 100, 'Owner / Administrador General'


class OrganizationMembership(TimeStampedModel):
    """
    Vínculo entre un Usuario y una Organización con un nivel de rol jerárquico asignado.
    Un usuario puede pertenecer a múltiples organizaciones pero con roles independientes.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name="Usuario"
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name="Organización"
    )
    role_level = models.IntegerField(
        choices=RoleLevel.choices,
        default=RoleLevel.OBSERVER,
        verbose_name="Nivel de Rol Jerárquico",
        help_text="Nivel numérico de autoridad (10=Observador ... 100=Owner/Admin)"
    )
    job_title = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Cargo / Título Profesional",
        help_text="Título descriptivo del colaborador en la organización (ej: Líder de Cuadrilla)"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Membresía Activa",
        help_text="Permite revocar el acceso a este tenant específico sin eliminar al usuario"
    )
    is_default_org = models.BooleanField(
        default=False,
        verbose_name="Organización Predeterminada",
        help_text="Organización que se selecciona automáticamente al iniciar sesión"
    )

    class Meta:
        verbose_name = "Membresía en Organización"
        verbose_name_plural = "Membresías en Organizaciones"
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'organization'],
                name='unique_user_organization_membership'
            )
        ]
        ordering = ['-role_level', 'created_at']

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization.name} [{self.get_role_level_display()}]"

    def can_approve(self, required_level: int) -> bool:
        """
        Evalúa si la membresía posee el nivel de autoridad jerárquico mínimo requerido
        para autorizar un documento, gasto, cambio de estado u orden de trabajo.
        """
        if not self.is_active or not self.organization.is_active:
            return False
        return self.role_level >= required_level

    def has_module_access(self, module_code: str, effective_role_level: int = None) -> bool:
        """
        Evalúa si el usuario tiene acceso a un módulo específico dentro de esta organización.
        1. Verifica que la membresía y la organización estén activas.
        2. Verifica que la organización tenga el módulo habilitado en 'enabled_modules'.
        3. Si se especifica 'effective_role_level', evalúa la autoridad contra ese nivel
           (utilizado por el Simulador de Rol en tiempo real para auditorías operativas).
        4. El Administrador General (OWNER_ADMIN 100) posee acceso irrestricto a todos los módulos contratados.
        5. Roles operativos validan su nivel de autoridad contra los umbrales específicos:
           - 'crm': Nivel 80 (OPERATIONS_COORD) o superior.
           - 'operations': Nivel 20 (TECHNICIAN) o superior.
           - 'sst': Nivel 20 (TECHNICIAN) o superior (técnicos registran; oficiales aprueban).
           - 'inventory': Nivel 50 (ENGINEER) o superior.
        """
        if not self.is_active or not self.organization.is_active:
            return False

        if not self.organization.is_module_enabled(module_code):
            return False

        eval_role_level = self.role_level if effective_role_level is None else effective_role_level

        if eval_role_level >= RoleLevel.OWNER_ADMIN:
            return True

        min_required_role = MODULE_THRESHOLD_MAP.get(module_code.lower().strip())
        if min_required_role is None:
            return False

        return eval_role_level >= min_required_role


class TenantQuerySet(models.QuerySet):
    """
    QuerySet especializado para garantizar aislamiento multi-tenant en todas las consultas.
    """
    def for_org(self, organization):
        """
        Filtra el QuerySet por organización. Si organization es None o no tiene PK,
        retorna inmediatamente un conjunto vacío (none()) para evitar fugas de datos.
        """
        if not organization or not getattr(organization, 'pk', None):
            return self.none()
        return self.filter(organization=organization)


class TenantManager(models.Manager):
    """
    Manager base para todos los modelos multi-tenant.
    Provee el método .for_org(organization) de forma obligatoria y segura.
    """
    def get_queryset(self):
        return TenantQuerySet(self.model, using=self._db)

    def for_org(self, organization):
        """
        Retorna registros pertenecientes exclusivamente a la organización suministrada.
        Retorna .none() si organization es None o no es válida.
        """
        return self.get_queryset().for_org(organization)


class TenantScopedModel(TimeStampedModel):
    """
    Clase abstracta obligatoria para TODOS los modelos operativos del sistema.
    Garantiza:
    1. Aislamiento estricto por organización (Foreign Key a Organization).
    2. Indexación para alto rendimiento en consultas multi-tenant.
    3. Prevención de fugas de datos entre clientes mediante TenantManager.
    """
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        db_index=True,
        related_name="%(app_label)s_%(class)s_set",
        verbose_name="Organización / Tenant",
        help_text="Tenant propietario de este registro operativo"
    )

    objects = TenantManager()

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['organization', 'created_at']),
        ]

    def save(self, *args, **kwargs):
        if not self.organization_id:
            raise ValidationError("Todo modelo derivado de TenantScopedModel requiere una organización asignada.")
        super().save(*args, **kwargs)
