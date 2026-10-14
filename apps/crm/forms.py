from decimal import Decimal
from django import forms
from django.contrib.auth import get_user_model
from apps.crm.models import Account, AccountContact, Opportunity, Quote, QuoteItem

User = get_user_model()

INPUT_BASE_CLS = (
    "w-full bg-white border border-slate-300 rounded px-3 py-1.5 text-xs text-slate-800 "
    "placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-900 focus:border-slate-900 "
    "transition duration-150 disabled:bg-slate-50 disabled:text-slate-400"
)
INPUT_MONO_CLS = f"{INPUT_BASE_CLS} font-mono tabular-nums"
SELECT_BASE_CLS = (
    "w-full bg-white border border-slate-300 rounded px-2.5 py-1.5 text-xs text-slate-800 "
    "focus:outline-none focus:ring-1 focus:ring-slate-900 focus:border-slate-900 "
    "transition duration-150"
)
CHECKBOX_CLS = (
    "rounded border-slate-300 text-slate-900 focus:ring-slate-900 h-4 w-4 text-xs"
)


class AccountForm(forms.ModelForm):
    """
    Formulario de alta y edición de Cuenta Comercial / Cliente Único.
    """
    class Meta:
        model = Account
        fields = [
            'commercial_name',
            'legal_name',
            'account_type',
            'lifecycle_stage',
            'tax_id',
            'email',
            'phone',
            'address',
            'city',
            'default_currency',
            'payment_terms_days',
            'is_tax_exempt',
            'assigned_to',
        ]
        widgets = {
            'commercial_name': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Ingenio San Antonio / DISNORTEL'}),
            'legal_name': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Nicaragua Sugar Estates Limited, S.A.'}),
            'account_type': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'lifecycle_stage': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'tax_id': forms.TextInput(attrs={'class': INPUT_MONO_CLS, 'placeholder': 'ej: J0310000112233'}),
            'email': forms.EmailInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'facturacion@empresa.com.ni'}),
            'phone': forms.TextInput(attrs={'class': INPUT_MONO_CLS, 'placeholder': '+505 2222-0000'}),
            'address': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'Km 11.5 Carretera a Masaya'}),
            'city': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'Managua'}),
            'default_currency': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'payment_terms_days': forms.NumberInput(attrs={'class': INPUT_MONO_CLS, 'min': '0', 'step': '1'}),
            'is_tax_exempt': forms.CheckboxInput(attrs={'class': CHECKBOX_CLS}),
            'assigned_to': forms.Select(attrs={'class': SELECT_BASE_CLS}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        country = getattr(organization, 'country', None) if organization else None

        # Monedas disponibles dinámicas según CountryConfig
        if country:
            currencies = [
                (country.primary_currency_code, f"{country.primary_currency_code} ({country.primary_currency_symbol}) - Principal"),
                (country.secondary_currency_code, f"{country.secondary_currency_code} ({country.secondary_currency_symbol}) - Secundaria"),
            ]
            self.fields['default_currency'].widget = forms.Select(
                choices=currencies,
                attrs={'class': SELECT_BASE_CLS}
            )
            if country.tax_id_label:
                self.fields['tax_id'].label = f"{country.tax_id_label} ({country.code})"
                self.fields['tax_id'].widget.attrs['placeholder'] = f"Formato {country.tax_id_label} de {country.name}"

        # Filtrar ejecutivos asignables por organización
        if organization:
            self.fields['assigned_to'].queryset = User.objects.filter(
                memberships__organization=organization,
                memberships__is_active=True,
            ).distinct()
        self.fields['assigned_to'].empty_label = "— Sin Ejecutivo Asignado —"

    def clean_tax_id(self):
        tax_id = self.cleaned_data.get('tax_id', '').strip().upper()
        if not tax_id:
            return tax_id
        if self.organization and self.organization.country:
            country = self.organization.country
            if not country.validate_tax_id(tax_id):
                raise forms.ValidationError(
                    f"El formato del {country.tax_id_label} no es válido para {country.name}. "
                    "Verifique el número tributario oficial."
                )
        return tax_id


class AccountContactForm(forms.ModelForm):
    """
    Formulario para puntos de contacto dentro de una Cuenta.
    """
    class Meta:
        model = AccountContact
        fields = ['full_name', 'job_title', 'email', 'phone', 'is_primary']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Ing. Roberto Mendoza'}),
            'job_title': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Gerente de Operaciones / Jefe de Planta'}),
            'email': forms.EmailInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'rmendoza@empresa.com.ni'}),
            'phone': forms.TextInput(attrs={'class': INPUT_MONO_CLS, 'placeholder': '+505 8888-1234'}),
            'is_primary': forms.CheckboxInput(attrs={'class': CHECKBOX_CLS}),
        }


class OpportunityForm(forms.ModelForm):
    """
    Formulario de registro y edición de Oportunidades Comerciales (Pipeline).
    """
    class Meta:
        model = Opportunity
        fields = [
            'account',
            'title',
            'stage',
            'currency',
            'estimated_value',
            'expected_close_date',
            'assigned_to',
        ]
        widgets = {
            'account': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'title': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Mantenimiento Preventivo Subestación Tipitapa'}),
            'stage': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'currency': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'estimated_value': forms.NumberInput(attrs={'class': INPUT_MONO_CLS, 'min': '0', 'step': '0.01'}),
            'expected_close_date': forms.DateInput(attrs={'class': INPUT_MONO_CLS, 'type': 'date'}),
            'assigned_to': forms.Select(attrs={'class': SELECT_BASE_CLS}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        country = getattr(organization, 'country', None) if organization else None

        if organization:
            self.fields['account'].queryset = Account.objects.for_org(organization)
            self.fields['assigned_to'].queryset = User.objects.filter(
                memberships__organization=organization,
                memberships__is_active=True,
            ).distinct()

        self.fields['account'].empty_label = "— Seleccione Cliente / Cuenta —"
        self.fields['assigned_to'].empty_label = "— Sin Asignar —"

        if country:
            currencies = [
                (country.primary_currency_code, f"{country.primary_currency_code} ({country.primary_currency_symbol})"),
                (country.secondary_currency_code, f"{country.secondary_currency_code} ({country.secondary_currency_symbol})"),
            ]
            self.fields['currency'].widget = forms.Select(choices=currencies, attrs={'class': SELECT_BASE_CLS})


class QuoteCreateForm(forms.ModelForm):
    """
    Formulario de creación inicial de Cotización Formal.
    """
    class Meta:
        model = Quote
        fields = [
            'account',
            'opportunity',
            'title',
            'currency_code',
            'exchange_rate',
            'tax_name',
            'tax_rate',
            'apply_tax',
            'valid_until',
            'notes',
        ]
        widgets = {
            'account': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'opportunity': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'title': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Mantenimiento Mayor y Acondicionamiento de Subestación'}),
            'currency_code': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'exchange_rate': forms.NumberInput(attrs={'class': INPUT_MONO_CLS, 'step': '0.0001'}),
            'tax_name': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'readonly': 'readonly'}),
            'tax_rate': forms.NumberInput(attrs={'class': INPUT_MONO_CLS, 'step': '0.01'}),
            'apply_tax': forms.CheckboxInput(attrs={'class': CHECKBOX_CLS}),
            'valid_until': forms.DateInput(attrs={'class': INPUT_MONO_CLS, 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': INPUT_BASE_CLS, 'rows': '3', 'placeholder': 'Garantía técnica de 12 meses. Forma de pago: 50% anticipo, 50% contra entrega...'}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        country = getattr(organization, 'country', None) if organization else None

        if organization:
            self.fields['account'].queryset = Account.objects.for_org(organization)
            self.fields['opportunity'].queryset = Opportunity.objects.for_org(organization)

        self.fields['account'].empty_label = "— Seleccione Cliente / Cuenta —"
        self.fields['opportunity'].empty_label = "— Oportunidad Opcional —"

        if country:
            currencies = [
                (country.primary_currency_code, f"{country.primary_currency_code} ({country.primary_currency_symbol}) - Principal"),
                (country.secondary_currency_code, f"{country.secondary_currency_code} ({country.secondary_currency_symbol}) - Dólares"),
            ]
            self.fields['currency_code'].widget = forms.Select(choices=currencies, attrs={'class': SELECT_BASE_CLS})
            if not self.initial.get('tax_name'):
                self.initial['tax_name'] = getattr(country, 'default_tax_name', 'IVA')
            if not self.initial.get('tax_rate'):
                self.initial['tax_rate'] = country.default_tax_rate
            if not self.initial.get('currency_code'):
                self.initial['currency_code'] = country.primary_currency_code


class QuoteItemForm(forms.ModelForm):
    """
    Formulario de agregado de Partida técnica / comercial a la Cotización.
    """
    class Meta:
        model = QuoteItem
        fields = [
            'item_type',
            'code',
            'description',
            'unit',
            'quantity',
            'unit_price',
            'discount_percent',
        ]
        widgets = {
            'item_type': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'code': forms.TextInput(attrs={'class': INPUT_MONO_CLS, 'placeholder': 'SRV-ING-01'}),
            'description': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'Descripción técnica del servicio o suministro'}),
            'unit': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'UND, HRS, GLB'}),
            'quantity': forms.NumberInput(attrs={'class': INPUT_MONO_CLS, 'min': '0.01', 'step': '0.01'}),
            'unit_price': forms.NumberInput(attrs={'class': INPUT_MONO_CLS, 'min': '0.00', 'step': '0.01'}),
            'discount_percent': forms.NumberInput(attrs={'class': INPUT_MONO_CLS, 'min': '0.00', 'max': '100.00', 'step': '0.01'}),
        }
