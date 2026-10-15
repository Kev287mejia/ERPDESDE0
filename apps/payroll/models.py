from decimal import Decimal
import hashlib
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.tenancy.models import TenantScopedModel


class EmployeeContract(TenantScopedModel):
    """
    Ficha Laboral y Contrato Individual de Trabajo MITRAB / INSS.
    Aislado por organización mediante TenantScopedModel.
    """
    class Department(models.TextChoices):
        MANAGEMENT = 'MANAGEMENT', 'Dirección y Administración'
        COMMERCIAL = 'COMMERCIAL', 'Comercial y Ventas'
        OPERATIONS = 'OPERATIONS', 'Ingeniería y Operaciones de Campo'
        SST = 'SST', 'Seguridad e Higiene MITRAB'
        LOGISTICS = 'LOGISTICS', 'Almacén y Logística'

    code = models.CharField(
        max_length=25,
        db_index=True,
        verbose_name="Código de Colaborador",
        help_text="ej: EMP-0001",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employment_contracts',
        verbose_name="Usuario del ERP",
        help_text="Vínculo con usuario del ERP para autoservicio de colillas",
    )
    full_name = models.CharField(
        max_length=150,
        verbose_name="Nombre Completo del Colaborador",
    )
    national_id = models.CharField(
        max_length=30,
        verbose_name="Cédula de Identidad",
        help_text="Cédula nicaragüense (ej: 001-150882-0003K)",
    )
    inss_number = models.CharField(
        max_length=30,
        verbose_name="N° Asegurado INSS",
        help_text="Número patronal / laboral de afiliación INSS (ej: 2458901-4)",
    )
    job_title = models.CharField(
        max_length=120,
        verbose_name="Cargo / Puesto Laboral",
        help_text="ej: Ingeniero Residente de Media Tensión",
    )
    department = models.CharField(
        max_length=20,
        choices=Department.choices,
        default=Department.OPERATIONS,
        verbose_name="Departamento / Área",
    )
    hire_date = models.DateField(
        default=timezone.now,
        verbose_name="Fecha de Contratación / Ingreso",
    )
    monthly_base_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Salario Básico Mensual (C$ NIO)",
    )
    bank_name = models.CharField(
        max_length=60,
        default='BAC Credomatic',
        verbose_name="Banco de Depósito de Nómina",
    )
    bank_account_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Número de Cuenta Bancaria",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Contrato Activo",
        help_text="Desmarcar al producirse liquidación o baja laboral",
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Contrato de Colaborador"
        verbose_name_plural = "Nómina de Contratos Laborales"
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'code'],
                name='unique_employee_code_per_tenant',
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} · {self.full_name} ({self.job_title})"

    def save(self, *args, **kwargs):
        if not self.code and self.organization_id:
            prefix = "EMP-"
            count = (
                EmployeeContract.objects.filter(
                    organization_id=self.organization_id,
                    code__startswith=prefix,
                ).count()
                + 1
            )
            candidate = f"{prefix}{count:04d}"
            while EmployeeContract.objects.filter(
                organization_id=self.organization_id, code=candidate
            ).exists():
                count += 1
                candidate = f"{prefix}{count:04d}"
            self.code = candidate

        super().save(*args, **kwargs)


class PayrollPeriod(TenantScopedModel):
    """
    Corrida / Planilla General del Período de Pago.
    Incluye consolidación de cargas patronales, retenciones de ley,
    sello criptográfico SHA-256 e integración con la póliza contable de partida doble.
    """
    class Frequency(models.TextChoices):
        MONTHLY = 'MONTHLY', 'Mensual (30 Días)'
        BIWEEKLY = 'BIWEEKLY', 'Quincenal (15 Días)'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'En Elaboración / Abierta'
        CLOSED = 'CLOSED', 'Aprobada, Sellada y Contabilizada'

    number = models.CharField(
        max_length=25,
        db_index=True,
        verbose_name="Número de Planilla",
        help_text="ej: NOM-2026-0001",
    )
    period_name = models.CharField(
        max_length=100,
        verbose_name="Nombre Descriptivo del Período",
        help_text="ej: Planilla Mensual Octubre 2026",
    )
    frequency = models.CharField(
        max_length=20,
        choices=Frequency.choices,
        default=Frequency.MONTHLY,
        verbose_name="Frecuencia de Pago",
    )
    start_date = models.DateField(
        verbose_name="Fecha Inicio de Período",
    )
    end_date = models.DateField(
        verbose_name="Fecha Fin de Período",
    )
    payment_date = models.DateField(
        verbose_name="Fecha de Pago Efectivo",
    )
    employer_inss_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('22.50'),
        verbose_name="Tasa INSS Patronal (%)",
        help_text="22.50% (>= 50 empleados) o 21.50% (< 50 empleados)",
    )
    inatec_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('2.00'),
        verbose_name="Tasa INATEC Patronal (%)",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name="Estado de Planilla",
    )

    # Totales Consolidados de Nómina (C$ NIO)
    total_gross_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Masa Salarial Bruta Total",
    )
    total_inss_employee = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Retenciones INSS Laboral (7%)",
    )
    total_ir_tax = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Retenciones IR Salarial (Ley 822)",
    )
    total_net_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Sueldos Netos por Pagar",
    )
    total_inss_employer = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Aporte INSS Patronal",
    )
    total_inatec = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Aporte INATEC Patronal",
    )
    total_provisions = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Provisiones Sociales MITRAB",
    )
    total_company_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Costo Total Empresa / Póliza de Nómina",
    )

    audit_hash = models.CharField(
        max_length=64,
        blank=True,
        editable=False,
        verbose_name="Sello Criptográfico SHA-256",
        help_text="Sello inmutable generado al cerrar la corrida de nómina",
    )
    journal_entry = models.ForeignKey(
        'finance.JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_periods',
        verbose_name="Póliza Contable de Nómina",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closed_payroll_periods',
        verbose_name="Aprobada y Sellada Por",
    )
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha y Hora de Cierre",
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Planilla de Pago"
        verbose_name_plural = "Planillas de Pago (Corridas)"
        ordering = ['-start_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'number'],
                name='unique_payroll_number_per_tenant',
            )
        ]

    def __str__(self) -> str:
        return f"{self.number} · {self.period_name} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        if self.pk:
            orig = PayrollPeriod.objects.filter(pk=self.pk).values('status', 'audit_hash').first()
            if orig and orig['status'] == self.Status.CLOSED and orig['audit_hash']:
                raise ValidationError(
                    f"INMUTABILIDAD: La planilla {self.number} ya fue sellada con SHA-256 y contabilizada. "
                    "Prohibida cualquier alteración de sus datos."
                )

    def delete(self, *args, **kwargs):
        if self.status == self.Status.CLOSED and self.audit_hash:
            raise ValidationError(
                f"PROTECCIÓN DE AUDITORÍA: La planilla {self.number} se encuentra sellada y contabilizada con hash SHA-256. "
                "Está prohibida su eliminación."
            )
        super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        self.clean()
        if not self.number and self.organization_id:
            year = self.start_date.year if self.start_date else timezone.now().year
            prefix = f"NOM-{year}-"
            count = (
                PayrollPeriod.objects.filter(
                    organization_id=self.organization_id,
                    number__startswith=prefix,
                ).count()
                + 1
            )
            candidate = f"{prefix}{count:04d}"
            while PayrollPeriod.objects.filter(
                organization_id=self.organization_id, number=candidate
            ).exists():
                count += 1
                candidate = f"{prefix}{count:04d}"
            self.number = candidate

        super().save(*args, **kwargs)


class Payslip(TenantScopedModel):
    """
    Colilla Individual de Pago y Provisiones MITRAB.
    Inmutable una vez que el período de nómina ha sido cerrado.
    """
    number = models.CharField(
        max_length=25,
        db_index=True,
        verbose_name="Folio de Colilla",
        help_text="ej: COL-2026-0001",
    )
    period = models.ForeignKey(
        PayrollPeriod,
        on_delete=models.CASCADE,
        related_name='payslips',
        verbose_name="Planilla / Período",
    )
    contract = models.ForeignKey(
        EmployeeContract,
        on_delete=models.PROTECT,
        related_name='payslips',
        verbose_name="Contrato del Colaborador",
    )
    days_worked = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('30.00'),
        verbose_name="Días Laborados en el Período",
    )
    base_salary_earned = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Salario Base Devengado",
    )
    overtime_and_bonuses = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Horas Extras, Comisiones e Incentivos Gravables",
    )
    non_taxable_allowances = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Viáticos / Aguinaldo No Gravable",
    )
    gross_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Ingresos Brutos Devengados",
    )

    # Deducciones de Ley al Trabajador (C$ NIO)
    inss_employee_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Deducción INSS Laboral (7%)",
    )
    net_taxable_base = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Base Imponible Neta Gravable para IR",
    )
    ir_salary_tax_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Retención IR Salarial (Art. 23 Ley 822)",
    )
    other_deductions = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Otras Deducciones (Préstamos, Anticipos, Embargos)",
    )
    total_deductions = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total Deducciones Aplicadas",
    )
    net_payable = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Neto a Recibir por el Colaborador",
    )

    # Cargas Patronales y Provisiones MITRAB (Informativas en Colilla / Imputables en Póliza)
    inss_employer_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Aporte INSS Patronal",
    )
    inatec_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Aporte INATEC Patronal (2%)",
    )
    vacation_provision = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Provisión Vacaciones Ley 185 (1/12)",
    )
    thirteenth_month_provision = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Provisión Décimo Tercer Mes / Aguinaldo (1/12)",
    )
    severance_provision = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Provisión Indemnización por Antigüedad Ley 185 (1/12)",
    )

    class Meta(TenantScopedModel.Meta):
        verbose_name = "Colilla de Pago"
        verbose_name_plural = "Colillas de Pago"
        ordering = ['period', 'contract__code']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'number'],
                name='unique_payslip_number_per_tenant',
            ),
            models.UniqueConstraint(
                fields=['period', 'contract'],
                name='unique_payslip_per_contract_period',
            )
        ]

    def __str__(self) -> str:
        return f"{self.number} · {self.contract.full_name} ({self.period.number}) [Neto: C$ {self.net_payable}]"

    def clean(self):
        super().clean()
        if self.period_id:
            orig_period = PayrollPeriod.objects.filter(pk=self.period_id).values('status', 'audit_hash').first()
            if orig_period and orig_period['status'] == PayrollPeriod.Status.CLOSED and orig_period['audit_hash']:
                raise ValidationError(
                    f"INMUTABILIDAD: La colilla {self.number} pertenece a la planilla sellada {self.period.number}. "
                    "No se permite su modificación ni alteración."
                )

    def delete(self, *args, **kwargs):
        if self.period_id:
            orig_period = PayrollPeriod.objects.filter(pk=self.period_id).values('status', 'audit_hash').first()
            if orig_period and orig_period['status'] == PayrollPeriod.Status.CLOSED and orig_period['audit_hash']:
                raise ValidationError(
                    f"INMUTABILIDAD: La colilla {self.number} pertenece a la planilla sellada {self.period.number}. "
                    "Está prohibida su eliminación."
                )
        super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        self.clean()
        if not self.number and self.organization_id:
            year = self.period.start_date.year if self.period and self.period.start_date else timezone.now().year
            prefix = f"COL-{year}-"
            count = (
                Payslip.objects.filter(
                    organization_id=self.organization_id,
                    number__startswith=prefix,
                ).count()
                + 1
            )
            candidate = f"{prefix}{count:04d}"
            while Payslip.objects.filter(
                organization_id=self.organization_id, number=candidate
            ).exists():
                count += 1
                candidate = f"{prefix}{count:04d}"
            self.number = candidate

        super().save(*args, **kwargs)
