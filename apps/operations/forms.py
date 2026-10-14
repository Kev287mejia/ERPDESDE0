from decimal import Decimal
from django import forms
from django.contrib.auth import get_user_model
from apps.crm.models import Account
from apps.operations.models import Crew, WorkOrder, WorkOrderItem, WorkOrderEvidence

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
CHECKBOX_CLS = "rounded border-slate-300 text-slate-900 focus:ring-slate-900 h-4 w-4 text-xs"


class WorkOrderCreateForm(forms.ModelForm):
    """
    Formulario de Apertura Manual de Orden de Trabajo (Coordinador 80+ / Owner 100).
    """
    class Meta:
        model = WorkOrder
        fields = [
            'account',
            'title',
            'technical_scope',
            'site_address',
            'priority',
            'is_high_risk',
            'assigned_engineer',
            'assigned_crew',
            'scheduled_start',
            'scheduled_end',
        ]
        widgets = {
            'account': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'title': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Mantenimiento Preventivo Subestación'}),
            'technical_scope': forms.Textarea(attrs={'class': INPUT_BASE_CLS, 'rows': '3', 'placeholder': 'Procedimientos de ingeniería, maniobras requeridas y normas técnicas...'}),
            'site_address': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Km 14 Carretera Norte, Planta Tipitapa'}),
            'priority': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'is_high_risk': forms.CheckboxInput(attrs={'class': CHECKBOX_CLS}),
            'assigned_engineer': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'assigned_crew': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'scheduled_start': forms.DateInput(attrs={'class': INPUT_MONO_CLS, 'type': 'date'}),
            'scheduled_end': forms.DateInput(attrs={'class': INPUT_MONO_CLS, 'type': 'date'}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization

        if organization:
            self.fields['account'].queryset = Account.objects.for_org(organization)
            self.fields['assigned_engineer'].queryset = User.objects.filter(
                memberships__organization=organization,
                memberships__role_level__gte=50,
                memberships__is_active=True,
            ).distinct()
            self.fields['assigned_crew'].queryset = Crew.objects.for_org(organization).filter(is_active=True)

        self.fields['account'].empty_label = "— Seleccione Cliente —"
        self.fields['assigned_engineer'].empty_label = "— Sin Ingeniero Asignado —"
        self.fields['assigned_crew'].empty_label = "— Sin Cuadrilla Asignada —"


class CrewForm(forms.ModelForm):
    """
    Formulario de Creación y Configuración de Cuadrilla Operativa.
    """
    class Meta:
        model = Crew
        fields = [
            'name',
            'specialty',
            'leader',
            'members',
            'vehicle_plate',
            'vehicle_description',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Cuadrilla Electromecánica Alfa'}),
            'specialty': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Media Tensión y Subestaciones'}),
            'leader': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'members': forms.SelectMultiple(attrs={'class': SELECT_BASE_CLS, 'size': '5'}),
            'vehicle_plate': forms.TextInput(attrs={'class': INPUT_MONO_CLS, 'placeholder': 'ej: M 345-890'}),
            'vehicle_description': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Camioneta Hilux 4x4 #04'}),
            'is_active': forms.CheckboxInput(attrs={'class': CHECKBOX_CLS}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization

        if organization:
            users_qs = User.objects.filter(
                memberships__organization=organization,
                memberships__is_active=True,
            ).distinct()
            self.fields['leader'].queryset = users_qs
            self.fields['members'].queryset = users_qs

        self.fields['leader'].empty_label = "— Seleccione Líder de Brigada —"


class WorkOrderItemForm(forms.ModelForm):
    """
    Formulario para agregar Partida Técnica a la OT (BOM sin precios comerciales).
    """
    class Meta:
        model = WorkOrderItem
        fields = [
            'item_type',
            'code',
            'description',
            'unit',
            'planned_quantity',
        ]
        widgets = {
            'item_type': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'code': forms.TextInput(attrs={'class': INPUT_MONO_CLS, 'placeholder': 'SRV-ING-01'}),
            'description': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'Descripción técnica de la labor o material'}),
            'unit': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'UND, MTS, HRS, GLB'}),
            'planned_quantity': forms.NumberInput(attrs={'class': INPUT_MONO_CLS, 'min': '0.01', 'step': '0.01'}),
        }


class WorkOrderEvidenceForm(forms.ModelForm):
    """
    Formulario para subir evidencias de campo (fotos antes/durante/después, reportes).
    """
    class Meta:
        model = WorkOrderEvidence
        fields = [
            'evidence_type',
            'title',
            'notes',
            'file_reference',
        ]
        widgets = {
            'evidence_type': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'title': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Estado inicial del banco de transformadores'}),
            'notes': forms.Textarea(attrs={'class': INPUT_BASE_CLS, 'rows': '2', 'placeholder': 'Detalles técnicos observados en campo...'}),
            'file_reference': forms.TextInput(attrs={'class': INPUT_MONO_CLS, 'placeholder': 'ej: FOTO-01-SUBESTACION.JPG o enlace interno'}),
        }
