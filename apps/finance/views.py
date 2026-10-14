from decimal import Decimal
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView, DetailView

from apps.tenancy.models import RoleLevel
from apps.tenancy.permissions import ModuleAccessRequiredMixin, render_403_rbac
from apps.operations.models import WorkOrder
from apps.finance.models import (
    BankAccount,
    PettyCashFund,
    PettyCashExpense,
    PettyCashReplenishment,
    FinancialTransaction,
)
from apps.finance.forms import (
    BankAccountForm,
    PettyCashFundForm,
    PettyCashExpenseForm,
    PettyCashReplenishmentSubmitForm,
    PettyCashDisburseForm,
)
from apps.finance.services import (
    allocate_petty_cash_fund,
    record_petty_cash_expense,
    submit_petty_cash_replenishment,
    disburse_petty_cash_replenishment,
)


class FinanceDashboardView(ModuleAccessRequiredMixin, TemplateView):
    """
    Consola Principal de Tesorería, Cajas Chicas y Flujo de Fondos.
    Accesible a partir de Nivel ENGINEER (50).
    Confidencialidad Bancaria y Financiera:
    - Ingenieros Nivel 50 y Oficiales SST Nivel 70:
      Acceso exclusivo a la rendición y registro de gastos de sus propias Cajas Chicas en custodia.
      Las cuentas bancarias y saldos corporativos se ocultan completamente del HTML.
    - Coordinadores Nivel 80 y Owners Nivel 100:
      Visibilidad total de cuentas bancarias (BAC, Banpro, Lafise), auditoría global y desembolsos.
    """
    template_name = 'finance/dashboard.html'
    required_module = 'finance'
    min_role_level = RoleLevel.ENGINEER

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        user = self.request.user
        role_level = getattr(self.request, 'role_level', 0)
        can_view_bank_accounts = role_level >= RoleLevel.OPERATIONS_COORD

        # Filtrar fondos según rol
        if can_view_bank_accounts:
            funds = list(PettyCashFund.objects.for_org(org).select_related('custodian', 'linked_crew'))
            bank_accounts = list(BankAccount.objects.for_org(org))
            replenishments = list(
                PettyCashReplenishment.objects.for_org(org)
                .select_related('fund', 'submitted_by', 'approved_by', 'disbursed_from_bank')
                [:30]
            )
            transactions = list(
                FinancialTransaction.objects.for_org(org)
                .select_related('bank_account', 'petty_cash_fund', 'performed_by')
                [:40]
            )
            total_bank_nio = sum((b.current_balance for b in bank_accounts if b.currency == 'NIO'), Decimal('0.00'))
            total_bank_usd = sum((b.current_balance for b in bank_accounts if b.currency == 'USD'), Decimal('0.00'))
        else:
            funds = list(PettyCashFund.objects.for_org(org).filter(custodian=user).select_related('custodian', 'linked_crew'))
            bank_accounts = []
            replenishments = list(
                PettyCashReplenishment.objects.for_org(org)
                .filter(fund__custodian=user)
                .select_related('fund', 'submitted_by')
                [:15]
            )
            transactions = list(
                FinancialTransaction.objects.for_org(org)
                .filter(petty_cash_fund__custodian=user)
                .select_related('petty_cash_fund', 'performed_by')
                [:20]
            )
            total_bank_nio = Decimal('0.00')
            total_bank_usd = Decimal('0.00')

        total_petty_cash_balance = sum((f.current_balance for f in funds), Decimal('0.00'))
        total_pending_reimbursement = sum((f.spent_amount for f in funds), Decimal('0.00'))

        # Últimos gastos
        expenses_qs = PettyCashExpense.objects.for_org(org).select_related('fund', 'work_order', 'created_by')
        if not can_view_bank_accounts:
            expenses_qs = expenses_qs.filter(fund__custodian=user)
        recent_expenses = list(expenses_qs[:40])

        context.update({
            'funds': funds,
            'bank_accounts': bank_accounts,
            'replenishments': replenishments,
            'recent_expenses': recent_expenses,
            'transactions': transactions,
            'total_petty_cash_balance': total_petty_cash_balance,
            'total_pending_reimbursement': total_pending_reimbursement,
            'total_bank_nio': total_bank_nio,
            'total_bank_usd': total_bank_usd,
            'can_view_bank_accounts': can_view_bank_accounts,
            'can_manage_funds': role_level >= RoleLevel.OPERATIONS_COORD,
            'can_create_bank_account': role_level >= RoleLevel.OWNER_ADMIN,
            'bank_form': BankAccountForm(),
            'fund_form': PettyCashFundForm(organization=org),
            'expense_form': PettyCashExpenseForm(organization=org, user=user),
            'replenish_form': PettyCashReplenishmentSubmitForm(organization=org, user=user),
            'disburse_form': PettyCashDisburseForm(organization=org),
        })
        return context


class BankAccountCreateView(ModuleAccessRequiredMixin, View):
    """Alta de Cuenta Bancaria. Exige Nivel 100 (Owner / Administrador General)."""
    required_module = 'finance'
    min_role_level = RoleLevel.OWNER_ADMIN

    @transaction.atomic
    def post(self, request):
        org = request.organization
        form = BankAccountForm(request.POST)
        if form.is_valid():
            bank = form.save(commit=False)
            bank.organization = org
            bank.save()
            messages.success(request, f"Cuenta bancaria {bank.get_bank_name_display()} ({bank.account_number}) registrada exitosamente.")
        else:
            messages.error(request, "Error al registrar cuenta bancaria. Verifique el número de cuenta y campos requeridos.")
        return redirect('finance:dashboard')


class PettyCashFundCreateView(ModuleAccessRequiredMixin, View):
    """Alta y Apertura de Caja Chica / Fondo Fijo. Exige Nivel 80 (Coordinador Operativo)."""
    required_module = 'finance'
    min_role_level = RoleLevel.OPERATIONS_COORD

    @transaction.atomic
    def post(self, request):
        org = request.organization
        form = PettyCashFundForm(request.POST, organization=org)
        if form.is_valid():
            fund = form.save(commit=False)
            fund.organization = org
            fund.current_balance = fund.allocated_amount
            fund.save()
            messages.success(
                request,
                f"Fondo Fijo {fund.code} ({fund.name}) creado con asignación inicial de C$ {fund.allocated_amount:,.2f}."
            )
        else:
            messages.error(request, "Error al registrar fondo de caja chica. Verifique los datos ingresados.")
        return redirect('finance:dashboard')


class PettyCashExpenseCreateView(ModuleAccessRequiredMixin, View):
    """
    Registro de Comprobante de Gasto Operativo en Frente de Obra.
    Accesible para Ingeniero Residente (Nivel 50) y superiores.
    """
    required_module = 'finance'
    min_role_level = RoleLevel.ENGINEER

    def post(self, request):
        org = request.organization
        user = request.user
        role_level = getattr(request, 'role_level', 0)

        # Verificación de autoridad: Ingeniero (< 80) no puede registrar gastos en cajas ajenas
        fund_id = request.POST.get('fund')
        if fund_id and role_level < RoleLevel.OPERATIONS_COORD:
            fund_obj = PettyCashFund.objects.filter(pk=fund_id, organization=org).first()
            if fund_obj and fund_obj.custodian_id != user.id:
                return render_403_rbac(request, "No tiene autorización para registrar gastos en una caja chica asignada a otro custodio.")

        form = PettyCashExpenseForm(request.POST, organization=org, user=user)

        if form.is_valid():
            fund = form.cleaned_data['fund']

            # Si es Ingeniero (< 80), verificar que sea el custodio asignado
            if role_level < RoleLevel.OPERATIONS_COORD and fund.custodian_id != user.id:
                return render_403_rbac(request, "No tiene autorización para registrar gastos en una caja chica asignada a otro custodio.")

            try:
                expense = record_petty_cash_expense(
                    organization=org,
                    fund=fund,
                    expense_category=form.cleaned_data['expense_category'],
                    vendor_name=form.cleaned_data['vendor_name'],
                    amount=form.cleaned_data['amount'],
                    description=form.cleaned_data['description'],
                    user=user,
                    work_order=form.cleaned_data.get('work_order'),
                    vendor_tax_id=form.cleaned_data.get('vendor_tax_id', ''),
                    invoice_number=form.cleaned_data.get('invoice_number', ''),
                    spent_at=form.cleaned_data.get('spent_at'),
                )
                messages.success(
                    request,
                    f"Gasto registrado: Folio {expense.voucher_number}. C$ {expense.amount:,.2f} descontados de {fund.name}."
                )
            except ValidationError as e:
                messages.error(request, f"Error financiero: {e.message if hasattr(e, 'message') else str(e)}")
        else:
            messages.error(request, "Error en los datos del comprobante de gasto. Verifique los montos y campos obligatorios.")

        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
        return redirect('finance:dashboard')


class PettyCashReplenishSubmitView(ModuleAccessRequiredMixin, View):
    """
    Arqueo y Envío de Solicitud de Reposición de Fondo Fijo.
    Accesible para el Custodio (Nivel 50+).
    """
    required_module = 'finance'
    min_role_level = RoleLevel.ENGINEER

    def post(self, request):
        org = request.organization
        user = request.user
        role_level = getattr(request, 'role_level', 0)

        # Verificación de autoridad: Ingeniero (< 80) no puede solicitar reposición de cajas ajenas
        fund_id = request.POST.get('fund')
        if fund_id and role_level < RoleLevel.OPERATIONS_COORD:
            fund_obj = PettyCashFund.objects.filter(pk=fund_id, organization=org).first()
            if fund_obj and fund_obj.custodian_id != user.id:
                return render_403_rbac(request, "Solo el custodio responsable de la caja chica puede solicitar su reposición.")

        form = PettyCashReplenishmentSubmitForm(request.POST, organization=org, user=user)

        if form.is_valid():
            fund = form.cleaned_data['fund']
            if role_level < RoleLevel.OPERATIONS_COORD and fund.custodian_id != user.id:
                return render_403_rbac(request, "Solo el custodio responsable de la caja chica puede solicitar su reposición.")

            try:
                rep = submit_petty_cash_replenishment(
                    organization=org,
                    fund=fund,
                    notes=form.cleaned_data.get('notes', ''),
                    user=user,
                )
                messages.success(
                    request,
                    f"Arqueo y solicitud de reposición {rep.code} generada exitosamente por C$ {rep.total_expenses_amount:,.2f}."
                )
            except ValidationError as e:
                messages.error(request, f"Error en arqueo: {e.message if hasattr(e, 'message') else str(e)}")
        else:
            messages.error(request, "Seleccione una caja chica válida para rendir cuentas.")

        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
        return redirect('finance:dashboard')


class PettyCashDisburseView(ModuleAccessRequiredMixin, View):
    """
    Aprobación y Desembolso Bancario de Reposición.
    Exige Nivel 80 (Coordinador Operativo) o Nivel 100 (Owner).
    """
    required_module = 'finance'
    min_role_level = RoleLevel.OPERATIONS_COORD

    def post(self, request):
        org = request.organization
        user = request.user
        form = PettyCashDisburseForm(request.POST, organization=org)

        if form.is_valid():
            bank_account = form.cleaned_data['bank_account']
            replenishment_id = form.cleaned_data['replenishment_id']
            replenishment = get_object_or_404(PettyCashReplenishment, pk=replenishment_id, organization=org)

            try:
                trx = disburse_petty_cash_replenishment(
                    organization=org,
                    replenishment=replenishment,
                    bank_account=bank_account,
                    user=user,
                )
                messages.success(
                    request,
                    f"Reposición {replenishment.code} desembolsada exitosamente desde {bank_account.bank_name}. "
                    f"Saldo restaurado en {replenishment.fund.name} (Folio Transacción: {trx.number})."
                )
            except ValidationError as e:
                messages.error(request, f"Error en desembolso bancario: {e.message if hasattr(e, 'message') else str(e)}")
        else:
            messages.error(request, "Datos de desembolso inválidos. Seleccione la cuenta bancaria de débito.")

        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
        return redirect('finance:dashboard')


class PettyCashFundDetailView(ModuleAccessRequiredMixin, DetailView):
    """
    Detalle, Arqueo Físico y Trazabilidad de una Caja Chica individual.
    """
    model = PettyCashFund
    template_name = 'finance/fund_detail.html'
    context_object_name = 'fund'
    required_module = 'finance'
    min_role_level = RoleLevel.ENGINEER

    def get_queryset(self):
        org = self.request.organization
        user = self.request.user
        role_level = getattr(self.request, 'role_level', 0)
        qs = PettyCashFund.objects.for_org(org)
        if role_level < RoleLevel.OPERATIONS_COORD:
            qs = qs.filter(custodian=user)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        fund = self.object
        org = self.request.organization
        role_level = getattr(self.request, 'role_level', 0)

        unreplenished_expenses = list(
            fund.expenses.filter(is_replenished=False)
            .select_related('work_order', 'created_by')
        )
        replenished_expenses = list(
            fund.expenses.filter(is_replenished=True)
            .select_related('work_order', 'replenishment')
            [:30]
        )
        total_pending = sum((e.amount for e in unreplenished_expenses), Decimal('0.00'))

        active_work_orders = list(
            WorkOrder.objects.for_org(org).filter(
                phase__in=[WorkOrder.Phase.IN_PROGRESS, WorkOrder.Phase.SCHEDULED]
            ).only('id', 'number', 'title')[:30]
        )

        context.update({
            'unreplenished_expenses': unreplenished_expenses,
            'replenished_expenses': replenished_expenses,
            'total_pending': total_pending,
            'active_work_orders': active_work_orders,
            'can_disburse': role_level >= RoleLevel.OPERATIONS_COORD,
            'disburse_form': PettyCashDisburseForm(organization=org),
        })
        return context
