import datetime
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.tenancy.models import TenantScopedModel


class Invoice(TenantScopedModel):
    """
    Factura Fiscal Oficial DGI / Cuenta por Cobrar (CxC).
    Implementa la normativa tributaria de Nicaragua (Ley 822) con soporte
    bimonetario (NIO/USD), IVA 15% y retenciones en la fuente (IR e IMI).
    """
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Borrador'
        ISSUED = 'ISSUED', 'Emitida / Pendiente de Cobro'
        PARTIAL = 'PARTIAL', 'Cobro Parcial'
        PAID = 'PAID', 'Cancelada / Pagada'
        VOID = 'VOID', 'Anulada'

    class PaymentCondition(models.TextChoices):
        CASH = 'CASH', 'Contado'
        CREDIT_15 = 'CREDIT_15', 'Crédito 15 Días'
        CREDIT_30 = 'CREDIT_30', 'Crédito 30 Días'

    number = models.CharField(
        max_length=25,
        db_index=True,
        verbose_name="Folio de Factura",
        help_text="Número oficial consecutivo (ej: FAC-2026-0001)"
    )
    account = models.ForeignKey(
        'crm.Account',
        on_delete=models.PROTECT,
        related_name='invoices',
        verbose_name="Cliente / Cuenta"
    )
    source_quote = models.ForeignKey(
        'crm.Quote',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices',
        verbose_name="Cotización de Origen"
    )
    source_work_order = models.ForeignKey(
        'operations.WorkOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices',
        verbose_name="Orden de Trabajo de Origen"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name="Estado de Factura"
    )
    payment_condition = models.CharField(
        max_length=20,
        choices=PaymentCondition.choices,
        default=PaymentCondition.CASH,
        verbose_name="Condición de Pago"
    )
    issue_date = models.DateField(
        default=timezone.now,
        verbose_name="Fecha de Emisión"
    )
    due_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de Vencimiento"
    )
    currency_code = models.CharField(
        max_length=3,
        default='NIO',
        verbose_name="Moneda de Facturación"
    )
    currency_symbol = models.CharField(
        max_length=10,
        default='C$',
        verbose_name="Símbolo Monetario"
    )
    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal('36.6243'),
        verbose_name="Tipo de Cambio Oficial (BCN)",
        help_text="Tasa oficial BCN NIO/USD"
    )
    apply_tax = models.BooleanField(
        default=True,
        verbose_name="Aplicar Impuesto al Valor Agregado"
    )
    tax_name = models.CharField(
        max_length=20,
        default='IVA',
        verbose_name="Nombre del Impuesto"
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('15.00'),
        verbose_name="Tasa de IVA (%)"
    )

    # Retenciones Fiscales de Ley Nicaragua (Ley 822 DGI & Alcaldía)
    ir_retention_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Retención IR DGI (%)",
        help_text="0%, 1% (Bienes), 2% (Servicios), 10% (Profesionales)"
    )
    imi_retention_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Retención Alcaldía IMI (%)",
        help_text="0% o 1% Retención Municipal Alcaldía (IMI)"
    )
    retention_certificate_number = models.CharField(
        max_length=60,
        blank=True,
        verbose_name="N° Constancia de Retención del Cliente",
        help_text="Identificador legal de la constancia emitida por el agente retenedor"
    )

    # Totales Financieros y Saldos de Cartera
    subtotal = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Subtotal Partidas Bruto"
    )
    discount_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Descuentos Comerciales"
    )
    tax_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total IVA Trasladado"
    )
    gross_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Facturado (Bruto)"
    )
    ir_retention_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Monto Retención IR"
    )
    imi_retention_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Monto Retención IMI"
    )
    net_receivable = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Neto a Cobrar en Caja"
    )
    amount_paid = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Recaudado (Abonos)"
    )
    balance_due = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Saldo Pendiente de Cobro"
    )

    notes = models.TextField(
        blank=True,
        verbose_name="Términos y Observaciones de Facturación"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_invoices',
        verbose_name="Facturador Responsable"
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Factura Fiscal"
        verbose_name_plural = "Facturas Fiscales (CxC)"
        ordering = ['-issue_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'number'],
                name='unique_invoice_number_per_tenant'
            )
        ]

    def __str__(self) -> str:
        return f"{self.number} · {self.account.commercial_name} ({self.currency_symbol} {self.net_receivable:,.2f})"

    @property
    def taxable_base(self) -> Decimal:
        """Base imponible gravable (Subtotal menos Descuentos)."""
        base = self.subtotal - self.discount_total
        return max(Decimal('0.00'), base)

    @property
    def total_retentions(self) -> Decimal:
        """Suma de retenciones en la fuente aplicadas por el cliente."""
        return self.ir_retention_amount + self.imi_retention_amount

    def recalculate_totals(self):
        """
        Calcula con precisión Decimal estricta bajo Ley 822 de Concertación Tributaria:
        1. Subtotal bruto y descuentos por partida.
        2. Base Imponible Gravable = Subtotal - Descuentos.
        3. IVA 15% sobre Base Imponible (si aplica y la cuenta no está exenta).
        4. Total Facturado (Gross Total) = Base Imponible + IVA.
        5. Retención IR e IMI calculadas EXCLUSIVAMENTE sobre la Base Imponible Gravable.
        6. Total Retenciones = IR + IMI.
        7. Neto a Cobrar = Total Facturado - Total Retenciones.
        8. Saldo Pendiente = Neto a Cobrar - Monto Recaudado.
        9. Transición de estado a PAID o PARTIAL.
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

        gross_total = taxable_base + tax_total

        ir_retention_amount = (taxable_base * (self.ir_retention_rate / Decimal('100.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        imi_retention_amount = (taxable_base * (self.imi_retention_rate / Decimal('100.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_retentions = ir_retention_amount + imi_retention_amount

        net_receivable = gross_total - total_retentions
        balance_due = net_receivable - self.amount_paid
        # Tolerancia técnica de centavos por redondeo de tipo de cambio oficial BCN
        if Decimal('0.00') < balance_due <= Decimal('0.05') and self.amount_paid > Decimal('0.00'):
            balance_due = Decimal('0.00')
        elif balance_due < Decimal('0.00'):
            balance_due = Decimal('0.00')

        self.subtotal = subtotal
        self.discount_total = discount_total
        self.tax_total = tax_total
        self.gross_total = gross_total
        self.ir_retention_amount = ir_retention_amount
        self.imi_retention_amount = imi_retention_amount
        self.net_receivable = net_receivable
        self.balance_due = balance_due

        # Transiciones de estado automático
        if self.status != self.Status.VOID and self.status != self.Status.DRAFT:
            if self.balance_due == Decimal('0.00') and self.amount_paid > Decimal('0.00'):
                self.status = self.Status.PAID
            elif Decimal('0.00') < self.amount_paid < self.net_receivable:
                self.status = self.Status.PARTIAL
            elif self.amount_paid == Decimal('0.00'):
                self.status = self.Status.ISSUED

    def save(self, *args, **kwargs):
        # Resolver fecha de vencimiento según la condición de pago
        if not self.due_date and self.issue_date:
            if self.payment_condition == self.PaymentCondition.CREDIT_15:
                self.due_date = self.issue_date + datetime.timedelta(days=15)
            elif self.payment_condition == self.PaymentCondition.CREDIT_30:
                self.due_date = self.issue_date + datetime.timedelta(days=30)
            else:
                self.due_date = self.issue_date

        # Asignar organización si no está seteada pero se tiene account
        if self.account_id and not self.organization_id:
            self.organization_id = self.account.organization_id

        # Generador de folio consecutivo fiscal
        if not self.number and self.organization_id:
            year = self.issue_date.year if self.issue_date else timezone.now().year
            prefix = f"FAC-{year}-"
            count = Invoice.objects.filter(
                organization_id=self.organization_id,
                number__startswith=prefix
            ).count() + 1
            candidate = f"{prefix}{count:04d}"
            while Invoice.objects.filter(organization_id=self.organization_id, number=candidate).exists():
                count += 1
                candidate = f"{prefix}{count:04d}"
            self.number = candidate

        super().save(*args, **kwargs)


class InvoiceItem(TenantScopedModel):
    """
    Partida o renglón técnico de la Factura Fiscal.
    """
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Factura"
    )
    item_type = models.CharField(
        max_length=20,
        default='SERVICE',
        verbose_name="Tipo de Partida"
    )
    code = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Código de Producto / Servicio"
    )
    description = models.CharField(
        max_length=255,
        verbose_name="Descripción de la Partida"
    )
    unit = models.CharField(
        max_length=20,
        default='UND',
        verbose_name="Unidad de Medida"
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('1.00'),
        verbose_name="Cantidad"
    )
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Precio Unitario"
    )
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Descuento (%)"
    )
    line_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Partida"
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Partida de Factura"
        verbose_name_plural = "Partidas de Factura"
        ordering = ['created_at']

    def __str__(self) -> str:
        return f"{self.invoice.number} · {self.description} ({self.quantity} {self.unit})"

    def save(self, *args, **kwargs):
        if self.invoice_id and not self.organization_id:
            self.organization_id = self.invoice.organization_id

        gross = (self.quantity * self.unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        disc = (gross * (self.discount_percent / Decimal('100.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.line_total = gross - disc

        super().save(*args, **kwargs)


class PaymentReceipt(TenantScopedModel):
    """
    Recibo Oficial de Caja (ROC) Bimonetario.
    Documento inmutable de trazabilidad fiscal y control de tesorería.
    Permite pagos en Córdobas (NIO) o Dólares (USD) con conversión automática.
    """
    class PaymentMethod(models.TextChoices):
        TRANSFER_BAC = 'TRANSFER_BAC', 'Transferencia BAC Credomatic'
        TRANSFER_LAFISE = 'TRANSFER_LAFISE', 'Transferencia Bancentro LAFISE'
        TRANSFER_BANPRO = 'TRANSFER_BANPRO', 'Transferencia BANPRO'
        TRANSFER_FICOHSA = 'TRANSFER_FICOHSA', 'Transferencia FICOHSA / BDF'
        CHECK = 'CHECK', 'Cheque Certificado'
        CASH = 'CASH', 'Efectivo en Caja'

    number = models.CharField(
        max_length=25,
        db_index=True,
        verbose_name="N° Recibo Oficial de Caja (ROC)",
        help_text="Consecutivo oficial (ej: ROC-2026-0001)"
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.PROTECT,
        related_name='payments',
        verbose_name="Factura Liquidada"
    )
    payment_date = models.DateField(
        default=timezone.now,
        verbose_name="Fecha de Recaudación"
    )
    payment_method = models.CharField(
        max_length=30,
        choices=PaymentMethod.choices,
        default=PaymentMethod.TRANSFER_BAC,
        verbose_name="Método de Pago"
    )
    reference_number = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="Referencia Bancaria / N° Cheque",
        help_text="ej: TRF-BAC-992014"
    )
    currency_paid = models.CharField(
        max_length=3,
        default='NIO',
        verbose_name="Moneda de Pago",
        help_text="Moneda en la que pagó el cliente (NIO o USD)"
    )
    amount_in_payment_currency = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Monto Recaudado en Moneda de Pago",
        help_text="Monto entregado en la moneda de pago"
    )
    exchange_rate_applied = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal('36.6243'),
        verbose_name="Tipo de Cambio Aplicado"
    )
    amount_applied_to_invoice = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Monto Acreditado a la Factura",
        help_text="Monto acreditado en la moneda de la factura"
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_receipts',
        verbose_name="Cajero / Receptor"
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Concepto / Observaciones del Recibo"
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Recibo Oficial de Caja"
        verbose_name_plural = "Recibos Oficiales de Caja (ROC)"
        ordering = ['-payment_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'number'],
                name='unique_payment_receipt_number_per_tenant'
            )
        ]

    def __str__(self) -> str:
        return f"{self.number} · {self.currency_paid} {self.amount_in_payment_currency:,.2f} -> {self.invoice.number}"

    def clean(self):
        super().clean()
        # Regla de Inmutabilidad Estricta
        if not self._state.adding and self.pk:
            raise ValidationError("Un Recibo Oficial de Caja (ROC) emitido es inmutable conforme a la normativa fiscal y no puede ser modificado.")

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk:
            raise ValidationError("Un Recibo Oficial de Caja (ROC) emitido es inmutable conforme a la normativa fiscal y no puede ser modificado.")

        if self.invoice_id and not self.organization_id:
            self.organization_id = self.invoice.organization_id

        # Cálculo automático de conversión bimonetaria
        if not self.amount_applied_to_invoice or self.amount_applied_to_invoice <= Decimal('0.00'):
            if self.currency_paid == self.invoice.currency_code:
                self.amount_applied_to_invoice = self.amount_in_payment_currency
            elif self.currency_paid == 'USD' and self.invoice.currency_code == 'NIO':
                self.amount_applied_to_invoice = (
                    self.amount_in_payment_currency * self.exchange_rate_applied
                ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            elif self.currency_paid == 'NIO' and self.invoice.currency_code == 'USD':
                self.amount_applied_to_invoice = (
                    self.amount_in_payment_currency / self.exchange_rate_applied
                ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Generador de folio consecutivo ROC
        if not self.number and self.organization_id:
            year = self.payment_date.year if self.payment_date else timezone.now().year
            prefix = f"ROC-{year}-"
            count = PaymentReceipt.objects.filter(
                organization_id=self.organization_id,
                number__startswith=prefix
            ).count() + 1
            candidate = f"{prefix}{count:04d}"
            while PaymentReceipt.objects.filter(organization_id=self.organization_id, number=candidate).exists():
                count += 1
                candidate = f"{prefix}{count:04d}"
            self.number = candidate

        super().save(*args, **kwargs)

        # Sincronizar saldo y estado en la factura correspondiente
        total_paid = (
            self.invoice.payments.aggregate(t=models.Sum('amount_applied_to_invoice'))['t']
            or Decimal('0.00')
        )
        self.invoice.amount_paid = total_paid
        self.invoice.recalculate_totals()
        Invoice.objects.filter(pk=self.invoice.pk).update(
            amount_paid=self.invoice.amount_paid,
            balance_due=self.invoice.balance_due,
            status=self.invoice.status,
            updated_at=timezone.now(),
        )

    def delete(self, *args, **kwargs):
        raise ValidationError("Un Recibo Oficial de Caja (ROC) emitido no puede ser eliminado por razones de auditoría y trazabilidad fiscal.")
