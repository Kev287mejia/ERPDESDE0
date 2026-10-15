from decimal import Decimal
from django.contrib import messages
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.payroll.forms import EmployeeContractForm, PayrollPeriodForm
from apps.payroll.models import EmployeeContract, PayrollPeriod, Payslip
from apps.payroll.services import (
    close_and_account_payroll_period,
    generate_and_calculate_period_payslips,
)
from apps.tenancy.models import RoleLevel
from apps.tenancy.permissions import ModuleAccessRequiredMixin, render_403_rbac


class PayrollDashboardView(ModuleAccessRequiredMixin, View):
    """
    Consola Maestra de Nómina, Planilla INSS/IR y Expedientes Laborales.
    Acceso restringido a Gerencia Comercial y Superior (RoleLevel.COMMERCIAL_MGR 85+).
    """
    required_module = 'payroll'
    min_role_level = RoleLevel.COMMERCIAL_MGR
    template_name = 'payroll/dashboard.html'

    def get(self, request, *args, **kwargs):
        org = request.organization

        contracts = EmployeeContract.objects.for_org(org).select_related('user').order_by('-is_active', 'code')
        periods = PayrollPeriod.objects.for_org(org).order_by('-start_date')

        # Métricas Consolidadas del Módulo de Nómina
        total_active_employees = contracts.filter(is_active=True).count()
        monthly_payroll_est = contracts.filter(is_active=True).aggregate(
            total=models.Sum('monthly_base_salary')
        )['total'] or Decimal('0.00')

        # Última planilla procesada
        latest_period = periods.first()
        closed_periods_count = periods.filter(status=PayrollPeriod.Status.CLOSED).count()

        context = {
            'organization': org,
            'contracts': contracts,
            'periods': periods,
            'total_active_employees': total_active_employees,
            'monthly_payroll_est': monthly_payroll_est,
            'latest_period': latest_period,
            'closed_periods_count': closed_periods_count,
            'contract_form': EmployeeContractForm(organization=org),
            'period_form': PayrollPeriodForm(),
        }
        return render(request, self.template_name, context)


class EmployeeContractCreateView(ModuleAccessRequiredMixin, View):
    """
    Alta de nuevo contrato laboral individual.
    """
    required_module = 'payroll'
    min_role_level = RoleLevel.COMMERCIAL_MGR

    def post(self, request, *args, **kwargs):
        org = request.organization
        form = EmployeeContractForm(request.POST, organization=org)
        if form.is_valid():
            contract = form.save(commit=False)
            contract.organization = org
            contract.save()
            messages.success(
                request,
                f"Contrato laboral {contract.code} para {contract.full_name} registrado exitosamente con salario C$ {contract.monthly_base_salary}."
            )
        else:
            errors_str = " · ".join([f"{f}: {err[0]}" for f, err in form.errors.items()])
            messages.error(request, f"Error al registrar contrato: {errors_str}")
        return redirect('payroll:dashboard')


class PayrollPeriodCreateView(ModuleAccessRequiredMixin, View):
    """
    Apertura de una nueva corrida de planilla (mensual o quincenal).
    """
    required_module = 'payroll'
    min_role_level = RoleLevel.COMMERCIAL_MGR

    def post(self, request, *args, **kwargs):
        org = request.organization
        form = PayrollPeriodForm(request.POST)
        if form.is_valid():
            period = form.save(commit=False)
            period.organization = org
            period.save()

            # Autogenerar y calcular colillas para todos los contratos activos
            generate_and_calculate_period_payslips(period)

            messages.success(
                request,
                f"Planilla {period.number} ({period.period_name}) creada exitosamente con {period.payslips.count()} colilla(s) generadas."
            )
            return redirect('payroll:period_detail', pk=period.pk)
        else:
            errors_str = " · ".join([f"{f}: {err[0]}" for f, err in form.errors.items()])
            messages.error(request, f"Error al abrir corrida de planilla: {errors_str}")
            return redirect('payroll:dashboard')


class PayrollPeriodDetailView(ModuleAccessRequiredMixin, View):
    """
    Sábana / Matriz Maestra de Nómina del Período.
    Visualiza el desglose exacto de salarios devengados, horas extras,
    INSS Laboral 7%, IR Ley 822 Art. 23, neto a pagar, cargas patronales y provisiones.
    """
    required_module = 'payroll'
    min_role_level = RoleLevel.COMMERCIAL_MGR
    template_name = 'payroll/period_detail.html'

    def get(self, request, pk, *args, **kwargs):
        org = request.organization
        period = get_object_or_404(PayrollPeriod.objects.for_org(org), pk=pk)
        payslips = period.payslips.select_related('contract').order_by('contract__code')

        context = {
            'organization': org,
            'period': period,
            'payslips': payslips,
        }
        return render(request, self.template_name, context)


class PayrollPeriodRecalculateView(ModuleAccessRequiredMixin, View):
    """
    Recalcula todas las colillas del período en elaboración.
    """
    required_module = 'payroll'
    min_role_level = RoleLevel.COMMERCIAL_MGR

    def post(self, request, pk, *args, **kwargs):
        org = request.organization
        period = get_object_or_404(PayrollPeriod.objects.for_org(org), pk=pk)
        if period.status == PayrollPeriod.Status.CLOSED:
            messages.error(request, "No se puede recalcular una planilla cerrada y sellada.")
            return redirect('payroll:period_detail', pk=period.pk)

        generate_and_calculate_period_payslips(period)
        messages.success(request, f"Planilla {period.number} recalculada exitosamente.")
        return redirect('payroll:period_detail', pk=period.pk)


class PayrollPeriodCloseView(ModuleAccessRequiredMixin, View):
    """
    Aprobación, Sellado Criptográfico SHA-256 y Contabilización de la Planilla.
    Crea la Póliza Contable de partida doble en apps/finance.
    """
    required_module = 'payroll'
    min_role_level = RoleLevel.COMMERCIAL_MGR

    def post(self, request, pk, *args, **kwargs):
        org = request.organization
        period = get_object_or_404(PayrollPeriod.objects.for_org(org), pk=pk)

        try:
            close_and_account_payroll_period(period, request.user)
            messages.success(
                request,
                f"PLANILLA SELLADA Y CONTABILIZADA: La nómina {period.number} ha sido sellada con hash SHA-256 "
                f"({period.audit_hash[:16]}...) y su póliza contable ha sido registrada en el Libro Diario."
            )
        except Exception as e:
            messages.error(request, f"Error al cerrar la planilla: {str(e)}")

        return redirect('payroll:period_detail', pk=period.pk)


class MyPayslipsSelfServiceView(ModuleAccessRequiredMixin, View):
    """
    Portal de Autoservicio del Colaborador: Mis Colillas de Pago.
    Accesible para todos los colaboradores con membresía en la empresa (RoleLevel 20+).
    Muestra estrictamente las colillas correspondientes al usuario en sesión.
    """
    required_module = 'payroll'
    min_role_level = RoleLevel.TECHNICIAN
    template_name = 'payroll/my_payslips.html'

    def get(self, request, *args, **kwargs):
        org = request.organization
        contract = EmployeeContract.objects.for_org(org).filter(user=request.user, is_active=True).first()
        payslips = (
            Payslip.objects.for_org(org)
            .filter(contract__user=request.user)
            .select_related('period', 'contract')
            .order_by('-period__start_date')
        )

        context = {
            'organization': org,
            'contract': contract,
            'payslips': payslips,
        }
        return render(request, self.template_name, context)


class PayslipPrintView(ModuleAccessRequiredMixin, View):
    """
    Formato Imprimible Oficial de Colilla de Pago de Haberes y Deducciones de Ley.
    Confidencialidad salarial estricta: accesible si role_level >= 85 O si
    payslip.contract.user_id == request.user.id.
    """
    required_module = 'payroll'
    min_role_level = RoleLevel.TECHNICIAN
    template_name = 'payroll/payslip_print.html'

    def get(self, request, pk, *args, **kwargs):
        org = request.organization
        payslip = get_object_or_404(
            Payslip.objects.for_org(org).select_related('period', 'contract', 'contract__user'),
            pk=pk
        )

        user_is_manager = getattr(request, 'role_level', 0) >= RoleLevel.COMMERCIAL_MGR
        user_is_owner = (payslip.contract.user_id == request.user.id)

        if not (user_is_manager or user_is_owner):
            return render_403_rbac(
                request,
                reason="Confidencialidad salarial estricta: Solo puede visualizar o imprimir su propia colilla de pago."
            )

        context = {
            'organization': org,
            'payslip': payslip,
            'period': payslip.period,
            'contract': payslip.contract,
        }
        return render(request, self.template_name, context)
