import hashlib
from django.contrib import messages
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import TemplateView

from apps.tenancy.models import RoleLevel
from apps.tenancy.permissions import ModuleAccessRequiredMixin, render_403_rbac
from .forms import (
    RepositoryFolderForm,
    CorporateDocumentCreateForm,
    NewDocumentVersionForm,
)
from .models import RepositoryFolder, CorporateDocument, DocumentVersion
from .services import publish_new_document_version


class RepositoryBrowserView(ModuleAccessRequiredMixin, TemplateView):
    """
    Explorador Jerárquico de Documentos Técnicos e Institucionales.
    Filtra carpetas según min_role_level_view <= request.role_level.
    """
    template_name = 'repository/browser.html'
    required_module = 'repository'
    min_role_level = RoleLevel.TECHNICIAN

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        role_level = getattr(self.request, 'role_level', 0)

        # 1. Carpetas accesibles por nivel de lectura
        visible_folders = RepositoryFolder.objects.for_org(org).filter(
            min_role_level_view__lte=role_level
        ).select_related('parent')

        active_folder_id = self.request.GET.get('folder')
        active_folder = None
        if active_folder_id:
            try:
                active_folder = RepositoryFolder.objects.for_org(org).get(pk=active_folder_id)
                if role_level < active_folder.min_role_level_view:
                    active_folder = None
            except RepositoryFolder.DoesNotExist:
                active_folder = None

        # 2. Documentos a listar
        if active_folder:
            documents = CorporateDocument.objects.for_org(org).filter(
                folder=active_folder
            ).select_related('folder', 'work_order', 'created_by')
        else:
            documents = CorporateDocument.objects.for_org(org).filter(
                folder__in=visible_folders
            ).select_related('folder', 'work_order', 'created_by')

        # 3. Permisos de creación
        can_create_folder = role_level >= RoleLevel.OPERATIONS_COORD
        can_upload_doc = False
        if active_folder:
            can_upload_doc = role_level >= active_folder.min_role_level_upload
        else:
            can_upload_doc = visible_folders.filter(min_role_level_upload__lte=role_level).exists()

        allowed_upload_folders = visible_folders.filter(min_role_level_upload__lte=role_level)

        context.update({
            'folders': visible_folders,
            'active_folder': active_folder,
            'documents': documents,
            'total_docs_count': documents.count(),
            'can_create_folder': can_create_folder,
            'can_upload_doc': can_upload_doc,
            'folder_form': RepositoryFolderForm(organization=org) if can_create_folder else None,
            'doc_form': CorporateDocumentCreateForm(
                organization=org,
                allowed_folders_qs=allowed_upload_folders,
                initial={'folder': active_folder} if active_folder else {}
            ) if can_upload_doc else None,
        })
        return context

    def get(self, request, *args, **kwargs):
        active_folder_id = request.GET.get('folder')
        if active_folder_id:
            org = request.organization
            role_level = getattr(request, 'role_level', 0)
            target = RepositoryFolder.objects.for_org(org).filter(pk=active_folder_id).first()
            if target and role_level < target.min_role_level_view:
                return render_403_rbac(
                    request,
                    required_module='repository',
                    min_role_level=target.min_role_level_view,
                    reason=f"La carpeta '{target.name}' es de carácter confidencial (requiere nivel {target.min_role_level_view}+)."
                )
        return super().get(request, *args, **kwargs)


class RepositoryFolderCreateView(ModuleAccessRequiredMixin, View):
    """
    Creación administrativa de carpetas en el repositorio.
    Requiere Nivel 80 (OPERATIONS_COORD) en adelante.
    """
    required_module = 'repository'
    min_role_level = RoleLevel.OPERATIONS_COORD

    def post(self, request):
        form = RepositoryFolderForm(request.POST, organization=request.organization)
        if form.is_valid():
            folder = form.save(commit=False)
            folder.organization = request.organization
            folder.save()
            messages.success(request, f"Carpeta '{folder.code} · {folder.name}' creada exitosamente.")
            return redirect(f"/repository/?folder={folder.pk}")
        else:
            messages.error(request, "Error al crear carpeta. Verifique los campos requeridos.")
            return redirect('repository:browser')


class CorporateDocumentCreateView(ModuleAccessRequiredMixin, View):
    """
    Carga de Nuevo Documento Corporativo e Inicialización de Versión 1.
    Valida que request.role_level >= folder.min_role_level_upload.
    """
    required_module = 'repository'
    min_role_level = RoleLevel.TECHNICIAN

    @transaction.atomic
    def post(self, request):
        org = request.organization
        role_level = getattr(request, 'role_level', 0)
        form = CorporateDocumentCreateForm(request.POST, organization=org)

        if form.is_valid():
            folder = form.cleaned_data['folder']

            if role_level < folder.min_role_level_upload:
                return render_403_rbac(
                    request,
                    required_module='repository',
                    min_role_level=folder.min_role_level_upload,
                    reason=f"La carpeta '{folder.name}' exige nivel {folder.min_role_level_upload}+ para subir documentos."
                )

            filename = form.cleaned_data['initial_filename']
            file_size_kb = form.cleaned_data['initial_file_size_kb']
            change_log = form.cleaned_data['change_log']
            content_payload = form.cleaned_data['content_payload']

            doc = form.save(commit=False)
            doc.organization = org
            doc.created_by = request.user
            doc.current_version_number = 1
            doc.latest_filename = filename
            doc.save()

            # Cálculo de Checksum SHA-256 para Versión 1
            raw_payload = f"{doc.code}|1|{filename}|{content_payload}".encode('utf-8')
            checksum = hashlib.sha256(raw_payload).hexdigest()

            doc.latest_checksum = checksum
            doc.save(update_fields=['latest_checksum'])

            DocumentVersion.objects.create(
                organization=org,
                document=doc,
                version_number=1,
                filename=filename,
                file_size_kb=max(1, file_size_kb),
                content_summary_or_payload=content_payload or '',
                checksum_sha256=checksum,
                change_log=change_log or 'Emisión inicial del documento.',
                uploaded_by=request.user,
            )

            messages.success(request, f"Documento '{doc.code} · {doc.title}' registrado exitosamente (v1).")
            return redirect('repository:document_detail', pk=doc.pk)
        else:
            messages.error(request, "Error al registrar documento. Verifique los campos obligatorios.")
            return redirect('repository:browser')


class CorporateDocumentDetailView(ModuleAccessRequiredMixin, TemplateView):
    """
    Ficha de Detalle de Documento y Línea de Tiempo Inmutable de Versiones.
    Exige min_role_level_view <= request.role_level.
    """
    template_name = 'repository/document_detail.html'
    required_module = 'repository'
    min_role_level = RoleLevel.TECHNICIAN

    def get(self, request, pk, *args, **kwargs):
        org = request.organization
        role_level = getattr(request, 'role_level', 0)
        doc = get_object_or_404(
            CorporateDocument.objects.for_org(org).select_related('folder', 'work_order', 'created_by'),
            pk=pk
        )

        if role_level < doc.folder.min_role_level_view:
            return render_403_rbac(
                request,
                required_module='repository',
                min_role_level=doc.folder.min_role_level_view,
                reason="Documento confidencial. Nivel de acceso insuficiente."
            )

        versions = doc.versions.all().select_related('uploaded_by').order_by('-version_number')
        can_upload_version = (role_level >= doc.folder.min_role_level_upload) and not doc.is_locked
        can_toggle_lock = role_level >= RoleLevel.OPERATIONS_COORD

        return render(request, self.template_name, {
            'doc': doc,
            'versions': versions,
            'can_upload_version': can_upload_version,
            'can_toggle_lock': can_toggle_lock,
            'version_form': NewDocumentVersionForm() if can_upload_version else None,
        })


class CorporateDocumentNewVersionView(ModuleAccessRequiredMixin, View):
    """
    Publicación concurrente de nueva revisión técnica de un documento.
    Invocada mediante POST; valida min_role_level_upload y select_for_update.
    """
    required_module = 'repository'
    min_role_level = RoleLevel.TECHNICIAN

    def post(self, request, pk):
        org = request.organization
        role_level = getattr(request, 'role_level', 0)
        doc = get_object_or_404(CorporateDocument.objects.for_org(org).select_related('folder'), pk=pk)

        if role_level < doc.folder.min_role_level_upload:
            return render_403_rbac(
                request,
                required_module='repository',
                min_role_level=doc.folder.min_role_level_upload,
                reason=f"Nivel {doc.folder.min_role_level_upload}+ requerido para versionar documentos en '{doc.folder.name}'."
            )

        if doc.is_locked:
            messages.error(request, "El documento se encuentra bloqueado administrativamente contra nuevas versiones.")
            return redirect('repository:document_detail', pk=doc.pk)

        form = NewDocumentVersionForm(request.POST)
        if form.is_valid():
            try:
                updated_doc, new_ver = publish_new_document_version(
                    organization=org,
                    document_id=doc.pk,
                    filename=form.cleaned_data['filename'],
                    file_size_kb=form.cleaned_data['file_size_kb'],
                    change_log=form.cleaned_data['change_log'],
                    content_payload=form.cleaned_data['content_payload'],
                    user=request.user,
                    role_level=role_level,
                )
                messages.success(
                    request,
                    f"Revisión técnica v{new_ver.version_number} publicada exitosamente. Checksum SHA-256: {new_ver.checksum_sha256[:16]}..."
                )
            except (ValidationError, PermissionDenied) as e:
                messages.error(request, str(e.message if hasattr(e, 'message') else e))
            except Exception as e:
                messages.error(request, f"Error al publicar versión: {str(e)}")
        else:
            messages.error(request, "Datos de revisión inválidos. Verifique el nombre de archivo y notas de cambio.")

        return redirect('repository:document_detail', pk=doc.pk)


class CorporateDocumentToggleLockView(ModuleAccessRequiredMixin, View):
    """
    Bloqueo administrativo del documento contra nuevas revisiones.
    Accesible desde Nivel 80 (OPERATIONS_COORD).
    """
    required_module = 'repository'
    min_role_level = RoleLevel.OPERATIONS_COORD

    def post(self, request, pk):
        org = request.organization
        doc = get_object_or_404(CorporateDocument.objects.for_org(org), pk=pk)
        doc.is_locked = not doc.is_locked
        doc.save(update_fields=['is_locked', 'updated_at'])

        status_txt = "bloqueado contra nuevas revisiones" if doc.is_locked else "desbloqueado para edición y versionado"
        messages.success(request, f"El documento '{doc.code}' ha sido {status_txt}.")
        return redirect('repository:document_detail', pk=doc.pk)
