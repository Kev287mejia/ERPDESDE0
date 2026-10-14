from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.operations.models import WorkOrder, Crew
from apps.sst.models import SafetyChecklist, EPPDelivery, LeaveRequest

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


class SafetyChecklistForm(forms.ModelForm):
    """
    Formulario de Registro de Checklist Pre-Operacional en Campo.
    """
    class Meta:
        model = SafetyChecklist
        fields = [
            'work_order',
            'crew',
            'work_type',
            'epp_verified',
            'loto_verified',
            'tools_inspected',
            'area_signaled',
            'risk_briefing_done',
            'hazard_notes',
        ]
        widgets = {
            'work_order': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'crew': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'work_type': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'epp_verified': forms.CheckboxInput(attrs={'class': CHECKBOX_CLS}),
            'loto_verified': forms.CheckboxInput(attrs={'class': CHECKBOX_CLS}),
            'tools_inspected': forms.CheckboxInput(attrs={'class': CHECKBOX_CLS}),
            'area_signaled': forms.CheckboxInput(attrs={'class': CHECKBOX_CLS}),
            'risk_briefing_done': forms.CheckboxInput(attrs={'class': CHECKBOX_CLS}),
            'hazard_notes': forms.Textarea(attrs={
                'class': INPUT_BASE_CLS,
                'rows': '2',
                'placeholder': 'Describa condiciones del entorno, interferencias o peligros específicos identificados...'
            }),
        }

    def __init__(self, *args, organization=None, initial_work_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        if organization:
            self.fields['work_order'].queryset = WorkOrder.objects.for_org(organization).exclude(
                phase__in=[WorkOrder.Phase.COMPLETED, WorkOrder.Phase.CANCELLED]
            )
            self.fields['crew'].queryset = Crew.objects.for_org(organization).filter(is_active=True)

        self.fields['work_order'].empty_label = "— Seleccione Orden de Trabajo —"
        self.fields['crew'].empty_label = "— Sin Cuadrilla Específica —"

        if initial_work_order:
            self.fields['work_order'].initial = initial_work_order
            if hasattr(initial_work_order, 'assigned_crew') and initial_work_order.assigned_crew:
                self.fields['crew'].initial = initial_work_order.assigned_crew


class EPPDeliveryForm(forms.ModelForm):
    """
    Formulario de Asignación y Entrega de Equipos de Protección Personal (EPP).
    Exclusivo para Oficial SST (70+).
    """
    class Meta:
        model = EPPDelivery
        fields = [
            'collaborator',
            'category',
            'item_name',
            'serial_or_batch',
            'quantity',
            'delivery_date',
            'expiration_date',
        ]
        widgets = {
            'collaborator': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'category': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'item_name': forms.TextInput(attrs={
                'class': INPUT_BASE_CLS,
                'placeholder': 'ej: Casco Dieléctrico Clase E 20kV con Barbiquejo'
            }),
            'serial_or_batch': forms.TextInput(attrs={
                'class': INPUT_MONO_CLS,
                'placeholder': 'ej: LOTE-3M-9941'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': INPUT_MONO_CLS,
                'min': '1',
            }),
            'delivery_date': forms.DateInput(attrs={
                'class': INPUT_MONO_CLS,
                'type': 'date'
            }),
            'expiration_date': forms.DateInput(attrs={
                'class': INPUT_MONO_CLS,
                'type': 'date'
            }),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        if organization:
            self.fields['collaborator'].queryset = User.objects.filter(
                memberships__organization=organization,
                memberships__is_active=True
            ).distinct()

        self.fields['collaborator'].empty_label = "— Seleccione Colaborador —"
        if not self.initial.get('delivery_date'):
            self.fields['delivery_date'].initial = timezone.now().date()


class LeaveRequestForm(forms.ModelForm):
    """
    Formulario de Solicitud de Permiso Laboral / Vacaciones / Reposo Médico.
    Accesible para todos los colaboradores (Nivel 20+).
    """
    class Meta:
        model = LeaveRequest
        fields = [
            'leave_type',
            'start_date',
            'end_date',
            'days_requested',
            'reason',
        ]
        widgets = {
            'leave_type': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'start_date': forms.DateInput(attrs={
                'class': INPUT_MONO_CLS,
                'type': 'date'
            }),
            'end_date': forms.DateInput(attrs={
                'class': INPUT_MONO_CLS,
                'type': 'date'
            }),
            'days_requested': forms.NumberInput(attrs={
                'class': INPUT_MONO_CLS,
                'min': '1'
            }),
            'reason': forms.Textarea(attrs={
                'class': INPUT_BASE_CLS,
                'rows': '3',
                'placeholder': 'Motivo justificado, constancia o referencia de reposo/vacaciones...'
            }),
        }
