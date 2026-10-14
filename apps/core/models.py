import re
import uuid
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models


class TimeStampedModel(models.Model):
    """
    Modelo base abstracto con identificador UUIDv4 y estampas de tiempo.
    Garantiza trazabilidad y universalidad en llaves primarias sin colisiones.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Identificador único universal (UUIDv4)"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="Fecha de Creación"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Última Actualización"
    )

    class Meta:
        abstract = True
        ordering = ['-created_at']


class CountryConfig(TimeStampedModel):
    """
    Configuración fiscal, monetaria y regional por país.
    Regla arquitectónica: NUNCA hardcodear monedas, impuestos o formatos en la lógica.
    Todo se resuelve dinámicamente consultando este modelo.
    """
    code = models.CharField(
        max_length=2,
        unique=True,
        db_index=True,
        verbose_name="Código ISO Alpha-2",
        help_text="Código ISO de dos letras (ej: NI, CR, HN, SV, GT, PA)"
    )
    name = models.CharField(
        max_length=100,
        verbose_name="Nombre del País"
    )
    flag_emoji = models.CharField(
        max_length=10,
        verbose_name="Bandera (Emoji)",
        help_text="Emoji oficial de la bandera (ej: 🇳🇮)"
    )
    is_active = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Operación Habilitada",
        help_text="Define si el ERP permite registrar y operar organizaciones en este país"
    )

    # Moneda Primaria (Moneda de curso legal / contable local)
    primary_currency_code = models.CharField(
        max_length=3,
        verbose_name="Código Moneda Primaria",
        help_text="Código ISO 4217 (ej: NIO, CRC, HNL, USD, GTQ, PAB)"
    )
    primary_currency_symbol = models.CharField(
        max_length=10,
        verbose_name="Símbolo Moneda Primaria",
        help_text="Símbolo visual local (ej: C$, ₡, L, $, Q, B/.)"
    )

    # Moneda Secundaria (Típicamente USD para Centroamérica)
    secondary_currency_code = models.CharField(
        max_length=3,
        default='USD',
        verbose_name="Código Moneda Secundaria",
        help_text="Código ISO 4217 (ej: USD)"
    )
    secondary_currency_symbol = models.CharField(
        max_length=10,
        default='$',
        verbose_name="Símbolo Moneda Secundaria",
        help_text="Símbolo visual secundario (ej: $)"
    )

    # Identificación Fiscal Corporativa (RUC, RTN, NIT, CIF)
    tax_id_label = models.CharField(
        max_length=50,
        verbose_name="Etiqueta ID Fiscal",
        help_text="Nombre local del identificador fiscal (ej: RUC, RTN, NIT, Cédula Jurídica)"
    )
    tax_id_regex = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Regex Validador ID Fiscal",
        help_text="Expresión regular para validar el identificador fiscal corporativo"
    )

    # Identificación Personal (Cédula de Identidad, DUI, DPI)
    personal_id_label = models.CharField(
        max_length=50,
        verbose_name="Etiqueta ID Personal",
        help_text="Nombre local del documento personal (ej: Cédula de Identidad, DUI, DPI)"
    )
    personal_id_regex = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Regex Validador ID Personal",
        help_text="Expresión regular para validar el documento de identidad personal"
    )

    # Impuestos Predeterminados (IVA, ISV, ITBMS)
    default_tax_name = models.CharField(
        max_length=20,
        default='IVA',
        verbose_name="Nombre Impuesto Predeterminado",
        help_text="Nombre oficial del impuesto al valor agregado (ej: IVA, ISV, ITBMS)"
    )
    default_tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('15.00'),
        verbose_name="Tasa de Impuesto Predeterminada (%)",
        help_text="Tasa porcentual estándar (ej: 15.00 para 15%)"
    )

    # Zona Horaria IANA
    timezone = models.CharField(
        max_length=64,
        default='America/Managua',
        verbose_name="Zona Horaria",
        help_text="Identificador de zona horaria IANA (ej: America/Managua, America/Costa_Rica)"
    )

    class Meta:
        verbose_name = "Configuración de País"
        verbose_name_plural = "Configuraciones de Países"
        ordering = ['name']

    def __str__(self) -> str:
        status = "ACTIVO" if self.is_active else "INACTIVO"
        return f"{self.flag_emoji} {self.name} ({self.code}) - [{status}]"

    def clean(self):
        super().clean()
        if self.code:
            self.code = self.code.upper().strip()
        if self.primary_currency_code:
            self.primary_currency_code = self.primary_currency_code.upper().strip()
        if self.secondary_currency_code:
            self.secondary_currency_code = self.secondary_currency_code.upper().strip()

    def validate_tax_id(self, tax_id: str) -> bool:
        """Valida si el tax_id cumple con el regex configurado para el país."""
        if not self.tax_id_regex:
            return True
        return bool(re.match(self.tax_id_regex, tax_id.strip()))

    def validate_personal_id(self, personal_id: str) -> bool:
        """Valida si el personal_id cumple con el regex configurado para el país."""
        if not self.personal_id_regex:
            return True
        return bool(re.match(self.personal_id_regex, personal_id.strip()))
