from decimal import Decimal, ROUND_HALF_UP
import hashlib
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.finance.models import AccountingAccount, JournalEntry, JournalEntryLine
from apps.payroll.models import EmployeeContract, PayrollPeriod, Payslip


def calculate_nicaragua_ir_monthly(net_taxable_monthly: Decimal) -> Decimal:
    """
    Cálculo del Impuesto sobre la Renta (IR) Salarial según la Tabla Progresiva
    Oficial del Artículo 23 de la Ley 822 de Concertación Tributaria de Nicaragua (DGI).
    Calcula sobre la expectativa de renta neta anualizada y deduce la alícuota mensual.
    """
    if net_taxable_monthly <= Decimal('0.00'):
        return Decimal('0.00')

    annual_expectation = net_taxable_monthly * Decimal('12.00')

    # Tramo 1: Hasta C$ 100,000.00 -> 0%
    if annual_expectation <= Decimal('100000.00'):
        annual_ir = Decimal('0.00')
    # Tramo 2: De C$ 100,000.01 hasta C$ 200,000.00 -> 15% sobre el exceso de 100,000
    elif annual_expectation <= Decimal('200000.00'):
        annual_ir = (annual_expectation - Decimal('100000.00')) * Decimal('0.15')
    # Tramo 3: De C$ 200,000.01 hasta C$ 350,000.00 -> C$ 15,000.00 + 20% sobre el exceso de 200,000
    elif annual_expectation <= Decimal('350000.00'):
        annual_ir = Decimal('15000.00') + (annual_expectation - Decimal('200000.00')) * Decimal('0.20')
    # Tramo 4: De C$ 350,000.01 hasta C$ 500,000.00 -> C$ 45,000.00 + 25% sobre el exceso de 350,000
    elif annual_expectation <= Decimal('500000.00'):
        annual_ir = Decimal('45000.00') + (annual_expectation - Decimal('350000.00')) * Decimal('0.25')
    # Tramo 5: Más de C$ 500,000.00 -> C$ 82,500.00 + 30% sobre el exceso de 500,000
    else:
        annual_ir = Decimal('82500.00') + (annual_expectation - Decimal('500000.00')) * Decimal('0.30')

    monthly_ir = (annual_ir / Decimal('12.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return max(Decimal('0.00'), monthly_ir)


def compute_payslip_figures(payslip: Payslip) -> Payslip:
    """
    Calcula los haberes devengados, deducciones laborales de ley (INSS 7%, IR Ley 822)
    y provisiones patronales MITRAB / INATEC para una colilla de pago individual.
    """
    period = payslip.period

    # 1. Ingresos Gravables y Brutos
    gross_taxable = (payslip.base_salary_earned + payslip.overtime_and_bonuses).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    payslip.gross_salary = (gross_taxable + payslip.non_taxable_allowances).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # 2. INSS Laboral (7.00% sobre ingresos gravables)
    payslip.inss_employee_amount = (gross_taxable * Decimal('0.07')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # 3. Base Neta Gravable para IR
    payslip.net_taxable_base = max(Decimal('0.00'), gross_taxable - payslip.inss_employee_amount)

    # 4. Retención IR Salarial (Art. 23 Ley 822)
    if period.frequency == PayrollPeriod.Frequency.BIWEEKLY:
        projected_monthly = payslip.net_taxable_base * Decimal('2.00')
        monthly_ir = calculate_nicaragua_ir_monthly(projected_monthly)
        payslip.ir_salary_tax_amount = (monthly_ir / Decimal('2.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    else:
        payslip.ir_salary_tax_amount = calculate_nicaragua_ir_monthly(payslip.net_taxable_base)

    # 5. Deducciones Totales y Salario Neto
    payslip.total_deductions = (
        payslip.inss_employee_amount + payslip.ir_salary_tax_amount + payslip.other_deductions
    ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    payslip.net_payable = (payslip.gross_salary - payslip.total_deductions).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # 6. Cargas Patronales de Ley
    emp_rate = (period.employer_inss_rate / Decimal('100.00'))
    payslip.inss_employer_amount = (gross_taxable * emp_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    ina_rate = (period.inatec_rate / Decimal('100.00'))
    payslip.inatec_amount = (gross_taxable * ina_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # 7. Provisiones Sociales MITRAB Ley 185 (1/12 por mes o 1/24 por quincena)
    divisor = Decimal('12.00') if period.frequency == PayrollPeriod.Frequency.MONTHLY else Decimal('24.00')
    provision_unit = (gross_taxable / divisor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    payslip.vacation_provision = provision_unit
    payslip.thirteenth_month_provision = provision_unit
    payslip.severance_provision = provision_unit

    payslip.save()
    return payslip


@transaction.atomic
def generate_and_calculate_period_payslips(period: PayrollPeriod) -> PayrollPeriod:
    """
    Genera o recalcula las colillas de todos los contratos activos del Tenant para el período.
    Actualiza los consolidados matemáticos en PayrollPeriod.
    """
    if period.status == PayrollPeriod.Status.CLOSED:
        raise ValidationError("No se puede recalcular una planilla que ya ha sido cerrada y sellada.")

    org = period.organization
    contracts = EmployeeContract.objects.filter(organization=org, is_active=True)

    for contract in contracts:
        if period.frequency == PayrollPeriod.Frequency.BIWEEKLY:
            base_earned = (contract.monthly_base_salary / Decimal('2.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            days_worked = Decimal('15.00')
        else:
            base_earned = contract.monthly_base_salary
            days_worked = Decimal('30.00')

        payslip, created = Payslip.objects.get_or_create(
            organization=org,
            period=period,
            contract=contract,
            defaults={
                'days_worked': days_worked,
                'base_salary_earned': base_earned,
            }
        )
        if not created and payslip.base_salary_earned == Decimal('0.00'):
            payslip.base_salary_earned = base_earned
            payslip.days_worked = days_worked

        compute_payslip_figures(payslip)

    # Consolidar Totales del Período
    payslips = Payslip.objects.filter(period=period)
    total_gross = sum((p.gross_salary for p in payslips), Decimal('0.00'))
    total_inss_emp = sum((p.inss_employee_amount for p in payslips), Decimal('0.00'))
    total_ir = sum((p.ir_salary_tax_amount for p in payslips), Decimal('0.00'))
    total_net = sum((p.net_payable for p in payslips), Decimal('0.00'))
    total_inss_empr = sum((p.inss_employer_amount for p in payslips), Decimal('0.00'))
    total_ina = sum((p.inatec_amount for p in payslips), Decimal('0.00'))
    total_prov = sum((p.vacation_provision + p.thirteenth_month_provision + p.severance_provision for p in payslips), Decimal('0.00'))
    total_cost = total_gross + total_inss_empr + total_ina + total_prov

    period.total_gross_salary = total_gross
    period.total_inss_employee = total_inss_emp
    period.total_ir_tax = total_ir
    period.total_net_salary = total_net
    period.total_inss_employer = total_inss_empr
    period.total_inatec = total_ina
    period.total_provisions = total_prov
    period.total_company_cost = total_cost
    period.save()

    return period


def ensure_payroll_accounting_accounts(organization):
    """
    Garantiza la existencia de las cuentas contables de nómina y cargas patronales.
    """
    payroll_accounts = [
        ('5201-01', 'Gastos Operativos - Sueldos y Salarios', AccountingAccount.AccountType.EXPENSE),
        ('5201-02', 'Gastos Operativos - Aporte Patronal INSS e INATEC', AccountingAccount.AccountType.EXPENSE),
        ('5201-03', 'Gastos Operativos - Provisiones Sociales MITRAB', AccountingAccount.AccountType.EXPENSE),
        ('2104-01', 'Sueldos y Salarios por Pagar', AccountingAccount.AccountType.LIABILITY),
        ('2104-02', 'Retenciones y Aportes INSS/INATEC por Pagar', AccountingAccount.AccountType.LIABILITY),
        ('2104-03', 'Retenciones IR Salarial por Enterar DGI', AccountingAccount.AccountType.LIABILITY),
        ('2104-04', 'Provisiones Laborales por Pagar (Vacaciones/Aguinaldo/Indemnización)', AccountingAccount.AccountType.LIABILITY),
        ('2104-05', 'Otras Deducciones por Pagar', AccountingAccount.AccountType.LIABILITY),
    ]
    acc_map = {}
    for code, name, acct_type in payroll_accounts:
        acc, _ = AccountingAccount.objects.get_or_create(
            organization=organization,
            code=code,
            defaults={'name': name, 'account_type': acct_type, 'is_active': True}
        )
        acc_map[code] = acc
    return acc_map


@transaction.atomic
def close_and_account_payroll_period(period: PayrollPeriod, user) -> PayrollPeriod:
    """
    Cierra la planilla con sello criptográfico SHA-256 e inyecta la Póliza Contable
    de partida doble cuadrada (Debe == Haber) en apps/finance.
    """
    if period.status == PayrollPeriod.Status.CLOSED:
        raise ValidationError(f"La planilla {period.number} ya se encuentra cerrada y sellada.")

    # 1. Asegurar cálculo actualizado de colillas y totales
    period = generate_and_calculate_period_payslips(period)
    org = period.organization

    # 2. Construir Póliza Contable de Nómina (Partida Doble Cuadrada)
    acc_map = ensure_payroll_accounting_accounts(org)

    journal_entry = JournalEntry.objects.create(
        organization=org,
        date=period.payment_date or timezone.now().date(),
        entry_type=JournalEntry.EntryType.ADJUSTMENT,
        concept=f"Póliza Contable de Nómina · {period.number} - {period.period_name}",
        reference=period.number,
        created_by=user,
    )

    # --- PARTIDAS DEL DEBE (Gastos Operativos = Costo Total Empresa) ---
    # a. Gasto de Sueldos y Salarios Devengados
    JournalEntryLine.objects.create(
        organization=org,
        entry=journal_entry,
        account=acc_map['5201-01'],
        concept=f"Masa Salarial Bruta Devengada · {period.number}",
        debit=period.total_gross_salary,
        credit=Decimal('0.00'),
    )
    # b. Gasto de Cargas Patronales (INSS Patronal + INATEC)
    JournalEntryLine.objects.create(
        organization=org,
        entry=journal_entry,
        account=acc_map['5201-02'],
        concept=f"Aporte Patronal INSS ({period.employer_inss_rate}%) e INATEC ({period.inatec_rate}%)",
        debit=period.total_inss_employer + period.total_inatec,
        credit=Decimal('0.00'),
    )
    # c. Gasto de Provisiones Sociales MITRAB
    JournalEntryLine.objects.create(
        organization=org,
        entry=journal_entry,
        account=acc_map['5201-03'],
        concept=f"Provisiones Laborales MITRAB (Vacaciones, Aguinaldo e Indemnización)",
        debit=period.total_provisions,
        credit=Decimal('0.00'),
    )

    # --- PARTIDAS DEL HABER (Pasivos de Nómina, Impuestos y Provisiones) ---
    # a. Sueldos Netos Líquidos por Pagar
    JournalEntryLine.objects.create(
        organization=org,
        entry=journal_entry,
        account=acc_map['2104-01'],
        concept=f"Sueldos Líquidos por Pagar a Colaboradores · {period.number}",
        debit=Decimal('0.00'),
        credit=period.total_net_salary,
    )
    # b. Retenciones y Aportes INSS e INATEC por Pagar
    total_inss_inatec_due = period.total_inss_employee + period.total_inss_employer + period.total_inatec
    JournalEntryLine.objects.create(
        organization=org,
        entry=journal_entry,
        account=acc_map['2104-02'],
        concept=f"Obligaciones Patronales y Laborales INSS e INATEC por Enterar",
        debit=Decimal('0.00'),
        credit=total_inss_inatec_due,
    )
    # c. Retención IR Salarial Ley 822 por Enterar DGI
    if period.total_ir_tax > Decimal('0.00'):
        JournalEntryLine.objects.create(
            organization=org,
            entry=journal_entry,
            account=acc_map['2104-03'],
            concept=f"Retención en la Fuente IR Salarial Ley 822 por Enterar DGI",
            debit=Decimal('0.00'),
            credit=period.total_ir_tax,
        )
    # d. Provisiones Laborales por Pagar (Pasivo Acumulado)
    JournalEntryLine.objects.create(
        organization=org,
        entry=journal_entry,
        account=acc_map['2104-04'],
        concept=f"Pasivo Acumulado por Prestaciones y Provisiones MITRAB",
        debit=Decimal('0.00'),
        credit=period.total_provisions,
    )
    # e. Otras Deducciones (si existieran)
    payslips = period.payslips.all()
    other_deductions_total = sum((p.other_deductions for p in payslips), Decimal('0.00'))
    if other_deductions_total > Decimal('0.00'):
        JournalEntryLine.objects.create(
            organization=org,
            entry=journal_entry,
            account=acc_map['2104-05'],
            concept=f"Otras Deducciones Aplicadas a Nómina",
            debit=Decimal('0.00'),
            credit=other_deductions_total,
        )

    # 3. Verificar Cuadre de Partida Doble
    journal_entry.verify_and_save_balance()
    period.journal_entry = journal_entry

    # 4. Generar Sello Criptográfico Inmutable SHA-256 y Sellar Periodo
    hash_payload = (
        f"{org.id}:{period.number}:{period.total_gross_salary}:{period.total_net_salary}:"
        f"{period.total_company_cost}:{timezone.now().isoformat()}"
    )
    period.audit_hash = hashlib.sha256(hash_payload.encode('utf-8')).hexdigest()
    period.status = PayrollPeriod.Status.CLOSED
    period.closed_by = user
    period.closed_at = timezone.now()
    period.save()

    return period
