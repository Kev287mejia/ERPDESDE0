from django import forms
from apps.tenancy.models import RoleLevel
from .models import RepositoryFolder, CorporateDocument, DocumentVersion

INPUT_BASE_CLS = (
    "w-full bg-white border border-slate-300 rounded px-3 py-2 text-xs text-slate-800 "
    "focus:outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900 transition-colors"
)
SELECT_BASE_CLS = (
    "w-full bg-white border border-slate-300 rounded px-3 py-2 text-xs text-slate-800 "
    "focus:outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900 transition-colors"
)
INPUT_MONO_CLS = (
    "w-full bg-white border border-slate-300 rounded px-3 py-2 text-xs font-mono tabular-nums text-slate-800 "
    "focus:outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900 transition-colors"
)


class RepositoryFolderForm(forms.ModelForm):
    class Meta:
        model = RepositoryFolder
        fields = [
            'name',
            'parent',
            'department',
            'min_role_level_view',
            'min_role_level_upload',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Planos y Diagramas Unifilares'}),
            'parent': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'department': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'min_role_level_view': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'min_role_level_upload': forms.Select(attrs={'class': SELECT_BASE_CLS}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields['parent'].queryset = RepositoryFolder.objects.filter(organization=organization)
        self.fields['parent'].empty_label = "— Carpeta Raíz (Sin Padre) —"


class CorporateDocumentCreateForm(forms.ModelForm):
    initial_filename = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'class': INPUT_MONO_CLS, 'placeholder': 'ej: UNIFILAR-ISA-15KV-V1.DWG'}),
        label="Archivo Adjunto / Nombre de Fichero"
    )
    initial_file_size_kb = forms.IntegerField(
        initial=180,
        widget=forms.NumberInput(attrs={'class': INPUT_MONO_CLS}),
        label="Tamaño Estimado (KB)"
    )
    change_log = forms.CharField(
        widget=forms.Textarea(attrs={'class': INPUT_BASE_CLS, 'rows': '2', 'placeholder': 'Emisión inicial para revisión técnica en campo.'}),
        label="Notas de Versión Inicial"
    )
    content_payload = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': INPUT_MONO_CLS, 'rows': '2', 'placeholder': 'Metadatos de ingeniería o referencia de archivo'}),
        label="Carga Útil / Metadatos Técnicos"
    )

    class Meta:
        model = CorporateDocument
        fields = [
            'folder',
            'work_order',
            'title',
            'document_type',
        ]
        widgets = {
            'folder': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'work_order': forms.Select(attrs={'class': SELECT_BASE_CLS}),
            'title': forms.TextInput(attrs={'class': INPUT_BASE_CLS, 'placeholder': 'ej: Diagrama Unifilar Subestación 15kV'}),
            'document_type': forms.Select(attrs={'class': SELECT_BASE_CLS}),
        }

    def __init__(self, *args, organization=None, allowed_folders_qs=None, **kwargs):
        super().__init__(*args, **kwargs)
        if allowed_folders_qs is not None:
            self.fields['folder'].queryset = allowed_folders_qs
        elif organization:
            self.fields['folder'].queryset = RepositoryFolder.objects.filter(organization=organization)

        if organization:
            from apps.operations.models import WorkOrder
            self.fields['work_order'].queryset = WorkOrder.objects.filter(organization=organization)
            self.fields['work_order'].empty_label = "— Sin Orden de Trabajo Vinculada —"


class NewDocumentVersionForm(forms.Form):
    filename = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'class': INPUT_MONO_CLS, 'placeholder': 'ej: UNIFILAR-ISA-15KV-V2.PDF'}),
        label="Nombre del Archivo de Nueva Versión"
    )
    file_size_kb = forms.IntegerField(
        initial=240,
        widget=forms.NumberInput(attrs={'class': INPUT_MONO_CLS}),
        label="Tamaño del Archivo (KB)"
    )
    change_log = forms.CharField(
        widget=forms.Textarea(attrs={'class': INPUT_BASE_CLS, 'rows': '3', 'placeholder': 'Corrección de capacidad interruptiva y calibre de conductores según visita técnica.'}),
        label="Notas de Cambio de la Revisión"
    )
    content_payload = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': INPUT_MONO_CLS, 'rows': '2', 'placeholder': 'Metadatos de revisión o hash fuente'}),
        label="Metadatos / Carga Útil"
    )
