import hashlib
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction

from .models import CorporateDocument, DocumentVersion


@transaction.atomic
def publish_new_document_version(
    organization,
    document_id,
    filename: str,
    file_size_kb: int,
    change_log: str,
    content_payload: str,
    user,
    role_level: int = None
) -> tuple[CorporateDocument, DocumentVersion]:
    """
    Publica concurrentemente una nueva versión de un documento corporativo.
    Utiliza select_for_update() para evitar condiciones de carrera en revisiones simultáneas.
    Valida nivel jerárquico de subida (min_role_level_upload) y bloqueo de documento.
    Calcula el checksum SHA-256 y almacena la versión inmutable.
    """
    doc = CorporateDocument.objects.select_for_update().select_related('folder').get(
        pk=document_id,
        organization=organization
    )

    if doc.is_locked:
        raise ValidationError("El documento está administrativamente bloqueado para nuevas versiones.")

    if role_level is not None and role_level < doc.folder.min_role_level_upload:
        raise PermissionDenied("Nivel de rol insuficiente para publicar o versionar documentos en esta carpeta.")

    next_version = doc.current_version_number + 1

    clean_filename = (filename or '').strip()
    clean_log = (change_log or '').strip()
    raw_payload = f"{doc.code}|{next_version}|{clean_filename}|{content_payload}".encode('utf-8')
    computed_checksum = hashlib.sha256(raw_payload).hexdigest()

    version = DocumentVersion.objects.create(
        organization=organization,
        document=doc,
        version_number=next_version,
        filename=clean_filename,
        file_size_kb=max(1, int(file_size_kb or 120)),
        content_summary_or_payload=content_payload or '',
        checksum_sha256=computed_checksum,
        change_log=clean_log or 'Actualización técnica de versión.',
        uploaded_by=user,
    )

    doc.current_version_number = next_version
    doc.latest_filename = clean_filename
    doc.latest_checksum = computed_checksum
    doc.save(update_fields=['current_version_number', 'latest_filename', 'latest_checksum', 'updated_at'])

    return doc, version
