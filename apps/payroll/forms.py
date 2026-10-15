from decimal import Decimal
from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.payroll.models import EmployeeContract, PayrollPeriod, Payslip

User = get_user_model()

INPUT_BASE_CLS = (
    "w-full bg-white border border-zinc-200 rounded-[4px] px-3 py-1.5 text-xs text-zinc-900 "
    "placeholder-zinc-400 focus:outline-none focus:border-zinc-900 transition-colors font-sans"
)
INPUT_MONO_CLS = f"{INPUT_BASE_CLS} font-mono tabular-nums"
SELECT_BASE_CLS = (
    "w-full bg-white border border-zinc-200 rounded-[4px] px-2.5 py-1.5 text-xs text-zinc-900 "
    "focus:outline-none focus:border-zinc-900 transition-colors font-sans cursor-pointer"
)


class EmployeeContractForm(forms.ModelForm):
    """
    Formulario de alta y edición de Ficha y Contrato Laboral.
    """
    class Meta:
        model = EmployeeContract
        fields = [
            'full_name',
            'national_id',
            'inss_number',
            'job_title',
            'department',
            'hire_date',
            'monthly_base_salary',
            'bank_name',
            'bank_account_number',
            'user',
        ]
        widgets = {
            'full_name': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Ing. Marcos Antonio Silva'}),
            'national_id': forms.TextInput(attrs={'class': INPUT_MONO_CLS, 'placeholder': '001-220785-0002A'}),
            'inss_number': forms.TextInput(attrs={'class': INPUT_MONO_CLS, 'placeholder': '2458901-4'}),
            'job_title': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Coordinador de Operaciones Industriales'}),
            'department': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'hire_date': forms.DateInput(attrs={'class': INPUT_MONO_CLS, 'type': 'date'}),
            'monthly_base_salary': forms.NumberInput(attrs={'class': INPUT_MONO_CLS, 'step': '0.01', 'min': '0'}),
            'bank_name': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'BAC Credomatic'}),
            'bank_account_number': forms.TextInput(attrs={'class': INPUT_MONO_CLS, 'placeholder': '350-100234-5'}),
            'user': forms.Select(attrs={'class': SELECT_BASE_CLS}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields['user'].queryset = User.objects.filter(
                memberships__organization=organization,
                memberships__is_active=True,
            ).distinct()
        self.fields['user'].empty_label = "— Sin Usuario ERP Vinculado —"
        self.fields['user'].required = False


class PayrollPeriodForm(forms.ModelForm):
    """
    Formulario de creación de corrida o planilla de nómina.
    """
    class Meta:
        model = PayrollPeriod
        fields = [
            'period_name',
            'frequency',
            'start_date',
            'end_date',
            'payment_date',
            'employer_inss_rate',
            'inatec_rate',
        ]
        widgets = {
            'period_name': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Planilla Mensual Octubre 2026'}),
            'frequency': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'start_date': forms.DateInput(attrs={'class': INPUT_MONO_CLS, 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': INPUT_MONO_CLS, 'type': 'date'}),
            'payment_date': forms.DateInput(attrs={'class': INPUT_MONO_CLS, 'type': 'date'}),
            'employer_inss_rate': forms.NumberInput(attrs={'class': INPUT_MONO_CLS, 'step': '0.01', 'value': '22.50'}),
            'inatec_rate': forms.NumberInput(attrs={'class': INPUT_MONO_CLS, 'step': '0.01', 'value': '2.00'}),
        }
