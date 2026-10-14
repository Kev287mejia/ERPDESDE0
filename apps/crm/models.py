from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from apps.tenancy.models import TenantScopedModel


class Account(TenantScopedModel):
    """
    Entidad Única de Cliente / Empresa (Directorio Central B2B).
    Unifica prospectos, clientes corporativos y entidades estatales bajo un solo modelo
    aislado por organización (TenantScopedModel).
    """
    class AccountType(models.TextChoices):
        CORPORATE = 'CORPORATE', 'Empresa Privada'
        GOVERNMENT = 'GOVERNMENT', 'Institución Estatal'
        INDIVIDUAL = 'INDIVIDUAL', 'Persona Natural'

    class LifecycleStage(models.TextChoices):
        PROSPECT = 'PROSPECT', 'Prospecto Comercial'
        ACTIVE = 'ACTIVE', 'Cliente Activo'
        INACTIVE = 'INACTIVE', 'Inactivo'

    code = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="Código de Cuenta",
        help_text="Identificador único (ej: CLI-0001)",
    )
    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
        default=AccountType.CORPORATE,
        verbose_name="Tipo de Cuenta",
    )
    lifecycle_stage = models.CharField(
        max_length=20,
        choices=LifecycleStage.choices,
        default=LifecycleStage.PROSPECT,
        db_index=True,
        verbose_name="Etapa Comercial",
    )
    commercial_name = models.CharField(
        max_length=150,
        db_index=True,
        verbose_name="Nombre Comercial",
        help_text="Nombre de marca o fantasía conocido en el mercado",
    )
    legal_name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Razón Social",
        help_text="Nombre legal inscrito ante el Registro Mercantil",
    )
    tax_id = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        verbose_name="Identificador Tributario (RUC / NIT)",
        help_text="RUC en Nicaragua u homólogo regional",
    )
    email = models.EmailField(
        blank=True,
        verbose_name="Correo de Facturación / Contacto",
    )
    phone = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Teléfono Corporativo",
    )
    address = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Dirección Física",
    )
    city = models.CharField(
        max_length=100,
        default='Managua',
        verbose_name="Ciudad / Departamento",
    )
    default_currency = models.CharField(
        max_length=3,
        default='NIO',
        verbose_name="Moneda Habitual",
        help_text="Moneda de cotización preferida (ej: NIO, USD)",
    )
    payment_terms_days = models.PositiveIntegerField(
        default=0,
        verbose_name="Términos de Crédito (Días)",
        help_text="0=Contado, 15=Crédito 15 días, 30=Crédito 30 días, etc.",
    )
    is_tax_exempt = models.BooleanField(
        default=False,
        verbose_name="Exento de IVA",
        help_text="Habilitar si el cliente posee constancia de exención de la DGI",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_accounts',
        verbose_name="Ejecutivo Comercial Responsable",
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Cliente / Cuenta"
        verbose_name_plural = "Directorio de Clientes (Accounts)"
        ordering = ['commercial_name']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'code'],
                name='unique_account_code_per_tenant',
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} · {self.commercial_name}"

    def clean(self):
        super().clean()
        if self.tax_id and hasattr(self, 'organization') and self.organization:
            country = getattr(self.organization, 'country', None)
            if country and not country.validate_tax_id(self.tax_id):
                raise ValidationError({
                    'tax_id': (
                        f"El formato del {country.tax_id_label} no es válido para {country.name}. "
                        "Verifique la sintaxis ante la DGI."
                    )
                })

    def save(self, *args, **kwargs):
        if not self.code and self.organization_id:
            # Autogenerar correlativo secuencial aislado por tenant: CLI-0001
            last_account = Account.objects.filter(
                organization_id=self.organization_id
            ).order_by('-created_at').first()

            count = Account.objects.filter(organization_id=self.organization_id).count() + 1
            candidate = f"CLI-{count:04d}"
            # Asegurar no colisión
            while Account.objects.filter(organization_id=self.organization_id, code=candidate).exists():
                count += 1
                candidate = f"CLI-{count:04d}"
            self.code = candidate

        super().save(*args, **kwargs)


class AccountContact(TenantScopedModel):
    """
    Puntos de contacto específicos (técnicos, compras, gerencia) vinculados a la Cuenta.
    """
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='contacts',
        verbose_name="Cuenta / Empresa",
    )
    full_name = models.CharField(
        max_length=150,
        verbose_name="Nombre Completo",
    )
    job_title = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Cargo / Posición",
        help_text="ej: Jefe de Mantenimiento, Gerente de Operaciones",
    )
    email = models.EmailField(
        blank=True,
        verbose_name="Correo Directo",
    )
    phone = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Teléfono / Celular",
    )
    is_primary = models.BooleanField(
        default=False,
        verbose_name="Contacto Principal",
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Contacto de Cuenta"
        verbose_name_plural = "Contactos de Cuenta"
        ordering = ['-is_primary', 'full_name']

    def __str__(self) -> str:
        return f"{self.full_name} ({self.account.commercial_name})"

    def save(self, *args, **kwargs):
        if self.account_id and not self.organization_id:
            self.organization_id = self.account.organization_id
        if self.is_primary and self.account_id:
            # Desmarcar otros contactos principales de esta cuenta
            AccountContact.objects.filter(
                account_id=self.account_id,
                is_primary=True
            ).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)


class Opportunity(TenantScopedModel):
    """
    Oportunidad comercial para el Tablero Kanban de ventas e ingeniería.
    """
    class Stage(models.TextChoices):
        NEW = 'NEW', 'Nueva'
        QUALIFIED = 'QUALIFIED', 'Calificada'
        PROPOSAL = 'PROPOSAL', 'Propuesta / Cotización'
        NEGOTIATION = 'NEGOTIATION', 'Negociación'
        WON = 'WON', 'Ganada'
        LOST = 'LOST', 'Perdida'

    code = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="Código Oportunidad",
        help_text="ej: OP-2026-0001",
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='opportunities',
        verbose_name="Cliente / Cuenta",
    )
    title = models.CharField(
        max_length=200,
        verbose_name="Título del Proyecto / Oportunidad",
        help_text="ej: Mantenimiento Preventivo Subestación Tipitapa",
    )
    stage = models.CharField(
        max_length=20,
        choices=Stage.choices,
        default=Stage.NEW,
        db_index=True,
        verbose_name="Etapa Kanban",
    )
    currency = models.CharField(
        max_length=3,
        default='NIO',
        verbose_name="Moneda Estimada",
    )
    estimated_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Monto Estimado",
    )
    expected_close_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha Estimada de Cierre",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_opportunities',
        verbose_name="Responsable Comercial",
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Oportunidad Comercial"
        verbose_name_plural = "Oportunidades (Pipeline Kanban)"
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'code'],
                name='unique_opportunity_code_per_tenant',
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} · {self.title}"

    def save(self, *args, **kwargs):
        if self.account_id and not self.organization_id:
            self.organization_id = self.account.organization_id

        if not self.code and self.organization_id:
            year = timezone.now().year
            count = Opportunity.objects.filter(
                organization_id=self.organization_id,
                created_at__year=year
            ).count() + 1
            candidate = f"OP-{year}-{count:04d}"
            while Opportunity.objects.filter(organization_id=self.organization_id, code=candidate).exists():
                count += 1
                candidate = f"OP-{year}-{count:04d}"
            self.code = candidate

        super().save(*args, **kwargs)


class Quote(TenantScopedModel):
    """
    Cotización Formal Bimonetaria (NIO Córdobas / USD Dólares).
    Documento técnico-comercial estructurado con cálculo preciso de impuestos DGI.
    Al ser aprobada, activa el cliente y sienta las bases para emitir Órdenes de Trabajo (OT).
    """
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Borrador'
        SENT = 'SENT', 'Enviada al Cliente'
        APPROVED = 'APPROVED', 'Aprobada (Lista para OT)'
        REJECTED = 'REJECTED', 'Rechazada'
        EXPIRED = 'EXPIRED', 'Vencida'

    number = models.CharField(
        max_length=25,
        db_index=True,
        verbose_name="Folio de Cotización",
        help_text="ej: COT-2026-0001",
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='quotes',
        verbose_name="Cliente / Cuenta",
    )
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quotes',
        verbose_name="Oportunidad Vinculada",
    )
    title = models.CharField(
        max_length=200,
        verbose_name="Alcance / Referencia del Proyecto",
        help_text="ej: Suministro e Instalación de Tablero de Transferencia",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name="Estado de la Cotización",
    )

    # Parámetros Monetarios Dinámicos desde CountryConfig
    currency_code = models.CharField(
        max_length=3,
        default='NIO',
        verbose_name="Código Moneda",
        help_text="Moneda de emisión (ej: NIO, USD)",
    )
    currency_symbol = models.CharField(
        max_length=10,
        default='C$',
        verbose_name="Símbolo Moneda",
        help_text="Símbolo (ej: C$, $)",
    )
    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal('36.6243'),
        verbose_name="Tipo de Cambio Oficial (NIO/USD)",
        help_text="Tasa de cambio referencial aplicada para equivalencia",
    )

    # Parámetros Tributarios Dinámicos
    tax_name = models.CharField(
        max_length=20,
        default='IVA',
        verbose_name="Nombre Impuesto",
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('15.00'),
        verbose_name="Tasa de Impuesto (%)",
    )
    apply_tax = models.BooleanField(
        default=True,
        verbose_name="Aplica Impuesto",
        help_text="Si está activo y el cliente no es exento, se liquida el impuesto correspondiente",
    )

    # Fechas
    valid_until = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha Límite de Validez",
    )

    # Cuadro de Liquidación Financiera
    subtotal = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Subtotal Bruto",
    )
    discount_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Descuento Total",
    )
    tax_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Monto de Impuesto",
    )
    grand_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total General",
    )

    notes = models.TextField(
        blank=True,
        verbose_name="Términos Comerciales, Garantía y Observaciones",
        help_text="Plazo de entrega, forma de pago y garantías del contratista",
    )

    # Trazabilidad y Aprobación
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_quotes',
        verbose_name="Elaborado Por",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_quotes',
        verbose_name="Aprobado Por",
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de Aprobación",
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Cotización"
        verbose_name_plural = "Cotizaciones Formales"
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'number'],
                name='unique_quote_number_per_tenant',
            )
        ]

    def __str__(self) -> str:
        return f"{self.number} · {self.account.commercial_name} ({self.currency_symbol} {self.grand_total:,.2f})"

    def recalculate_totals(self):
        """
        Calcula con precisión Decimal estricta las sumas de partidas:
        1. Subtotal de ítems brutos.
        2. Descuentos porcentuales por línea.
        3. Base imponible neta.
        4. Impuesto (IVA) si apply_tax es True y la cuenta no está exenta.
        5. Total General = Base Imponible + Impuesto.
        """
        items = list(self.items.all())
        subtotal = Decimal('0.00')
        discount_total = Decimal('0.00')

        for item in items:
            gross = (item.quantity * item.unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            disc = (gross * (item.discount_percent / Decimal('100.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            subtotal += gross
            discount_total += disc

        taxable_base = subtotal - discount_total
        if taxable_base < Decimal('0.00'):
            taxable_base = Decimal('0.00')

        is_exempt = getattr(self.account, 'is_tax_exempt', False) if self.account_id else False

        if self.apply_tax and not is_exempt:
            tax_total = (taxable_base * (self.tax_rate / Decimal('100.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            tax_total = Decimal('0.00')

        grand_total = taxable_base + tax_total

        self.subtotal = subtotal
        self.discount_total = discount_total
        self.tax_total = tax_total
        self.grand_total = grand_total

        Quote.objects.filter(pk=self.pk).update(
            subtotal=self.subtotal,
            discount_total=self.discount_total,
            tax_total=self.tax_total,
            grand_total=self.grand_total,
            updated_at=timezone.now(),
        )

    def save(self, *args, **kwargs):
        if self.account_id and not self.organization_id:
            self.organization_id = self.account.organization_id

        if not self.number and self.organization_id:
            year = timezone.now().year
            count = Quote.objects.filter(
                organization_id=self.organization_id,
                created_at__year=year
            ).count() + 1
            candidate = f"COT-{year}-{count:04d}"
            while Quote.objects.filter(organization_id=self.organization_id, number=candidate).exists():
                count += 1
                candidate = f"COT-{year}-{count:04d}"
            self.number = candidate

        super().save(*args, **kwargs)


class QuoteItem(TenantScopedModel):
    """
    Partidas y líneas de desglose de la Cotización.
    Clasificadas en Servicios técnicos, Materiales y Equipamiento.
    """
    class ItemType(models.TextChoices):
        SERVICE = 'SERVICE', 'Servicio / Mano de Obra Técnica'
        MATERIAL = 'MATERIAL', 'Material / Suministro'
        EQUIPMENT = 'EQUIPMENT', 'Uso de Equipo / Maquinaria'

    quote = models.ForeignKey(
        Quote,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Cotización",
    )
    item_type = models.CharField(
        max_length=20,
        choices=ItemType.choices,
        default=ItemType.SERVICE,
        verbose_name="Tipo de Partida",
    )
    code = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Código Ítem",
        help_text="ej: SRV-ING-01, MAT-CAB-04",
    )
    description = models.CharField(
        max_length=255,
        verbose_name="Descripción de la Partida",
    )
    unit = models.CharField(
        max_length=20,
        default='UND',
        verbose_name="Unidad de Medida",
        help_text="ej: UND, HRS, MTS, GLB",
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('1.00'),
        verbose_name="Cantidad",
    )
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Precio Unitario",
    )
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Descuento (%)",
    )
    line_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total de Línea",
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Partida de Cotización"
        verbose_name_plural = "Partidas de Cotización"
        ordering = ['created_at']

    def __str__(self) -> str:
        return f"{self.quote.number} · {self.description} ({self.line_total})"

    def save(self, *args, **kwargs):
        if self.quote_id and not self.organization_id:
            self.organization_id = self.quote.organization_id

        # Cálculo automático de total de línea
        gross = (self.quantity * self.unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        discount = (gross * (self.discount_percent / Decimal('100.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.line_total = (gross - discount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        super().save(*args, **kwargs)
        self.quote.recalculate_totals()

    def delete(self, *args, **kwargs):
        quote = self.quote
        super().delete(*args, **kwargs)
        quote.recalculate_totals()
