import datetime
from django import forms
from django.utils import timezone

from apps.tenancy.models import RoleLevel
from .models import McpAccessToken
from .services import MCP_TOOLS_SPEC


class McpAccessTokenCreateForm(forms.Form):
    """
    Formulario para la emisión administrativa de tokens MCP para clientes y agentes IA.
    """
    EXPIRATION_CHOICES = [
        ('30', '30 Días (Recomendado)'),
        ('90', '90 Días (Trimestral)'),
        ('180', '180 Días (Semestral)'),
        ('365', '1 Año (Anual)'),
        ('0', 'Sin Expiración (Permanente)'),
    ]

    name = forms.CharField(
        max_length=150,
        label="Nombre del Cliente / Agente IA",
        widget=forms.TextInput(attrs={
            'class': 'w-full text-xs bg-white border border-slate-200 rounded px-3 py-2 text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-900',
            'placeholder': 'Ej: Claude Desktop - Dirección Operativa'
        })
    )
    scoped_role_level = forms.TypedChoiceField(
        choices=RoleLevel.choices,
        coerce=int,
        initial=RoleLevel.OPERATIONS_COORD,
        label="Nivel Jerárquico de Autoridad (RBAC)",
        widget=forms.Select(attrs={
            'class': 'w-full text-xs bg-white border border-slate-200 rounded px-3 py-2 text-slate-800 focus:outline-none focus:ring-1 focus:ring-slate-900'
        }),
        help_text="Define el techo de permisos que tendrá el LLM al consultar los datos del ERP."
    )
    allowed_tools = forms.MultipleChoiceField(
        choices=[(k, f"{v['title']} ({k})") for k, v in MCP_TOOLS_SPEC.items()],
        initial=list(MCP_TOOLS_SPEC.keys()),
        label="Herramientas Habilitadas",
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'rounded border-slate-300 text-slate-900 focus:ring-slate-900'
        }),
        help_text="Seleccione las herramientas a las que este token tendrá acceso."
    )
    expiration = forms.ChoiceField(
        choices=EXPIRATION_CHOICES,
        initial='90',
        label="Plazo de Expiración",
        widget=forms.Select(attrs={
            'class': 'w-full text-xs bg-white border border-slate-200 rounded px-3 py-2 text-slate-800 focus:outline-none focus:ring-1 focus:ring-slate-900'
        })
    )

    def __init__(self, *args, max_role_level=100, **kwargs):
        super().__init__(*args, **kwargs)
        # Limitar la lista de scoped_role_level al nivel del usuario que crea el token
        allowed_choices = [(lvl, lbl) for lvl, lbl in RoleLevel.choices if lvl <= max_role_level]
        self.fields['scoped_role_level'].choices = allowed_choices

    def get_expiration_datetime(self):
        val = self.cleaned_data.get('expiration', '90')
        if val == '0':
            return None
        days = int(val)
        return timezone.now() + datetime.timedelta(days=days)
