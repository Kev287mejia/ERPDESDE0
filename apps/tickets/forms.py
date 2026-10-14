from django import forms
from .models import SupportTicket, TicketComment

INPUT_BASE_CLS = (
    "w-full bg-white border border-slate-300 rounded px-3 py-2 text-xs text-slate-800 "
    "focus:outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900 transition-colors"
)
SELECT_BASE_CLS = (
    "w-full bg-white border border-slate-300 rounded px-3 py-2 text-xs text-slate-800 "
    "focus:outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900 transition-colors"
)


class SupportTicketCreateForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = [
            'title',
            'category',
            'priority',
            'related_work_order',
            'description',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Falla de alternador en camioneta de cuadrilla Hilux M 345-890'}),
            'category': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'priority': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'related_work_order': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'description': forms.Textarea(attrs={'class': INPUT_BASE_CLS, 'rows': '4', 'placeholder': 'Detalle el problema operativo, ubicación, impacto y requerimiento...'}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            from apps.operations.models import WorkOrder
            self.fields['related_work_order'].queryset = WorkOrder.objects.filter(organization=organization)
        self.fields['related_work_order'].empty_label = "— Sin Orden de Trabajo Vinculada —"


class TicketCommentForm(forms.ModelForm):
    class Meta:
        model = TicketComment
        fields = ['message']
        widgets = {
            'message': forms.Textarea(attrs={'class': INPUT_BASE_CLS, 'rows': '3', 'placeholder': 'Escriba una actualización técnica o respuesta...'}),
        }


class TicketResolveForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ['status', 'resolution_summary']
        widgets = {
            'status': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'resolution_summary': forms.Textarea(attrs={'class': INPUT_BASE_CLS, 'rows': '3', 'placeholder': 'Describa la solución técnica aplicada para dar por cerrado el incidente...'}),
        }
