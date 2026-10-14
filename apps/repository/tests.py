from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase, Client
from django.urls import reverse

from apps.core.models import CountryConfig
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel
from apps.repository.models import RepositoryFolder, CorporateDocument, DocumentVersion
from apps.repository.services import publish_new_document_version

User = get_user_model()


class RepositoryTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        self.country = CountryConfig.objects.create(
            code='NI',
            name='Nicaragua',
            primary_currency_code='NIO',
            primary_currency_symbol='C$',
            is_active=True,
        )

        self.org = Organization.objects.create(
            name='SERMANSA Test Org',
            tax_id='J0310000000018',
            country=self.country,
            currency='NIO',
            enabled_modules=['repository'],
            onboarding_completed=True,
        )

        # Usuarios con diferentes niveles RBAC
        self.owner = User.objects.create_user(
            email='owner@sermansa.ni',
            password='Password123*',
            full_name='Ing. Fernando Buitrago'
        )
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.org,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
        )

        self.engineer = User.objects.create_user(
            email='engineer@sermansa.ni',
            password='Password123*',
            full_name='Ing. Carlos Chamorro'
        )
        OrganizationMembership.objects.create(
            user=self.engineer,
            organization=self.org,
            role_level=RoleLevel.ENGINEER,
            is_active=True,
        )

        self.technician = User.objects.create_user(
            email='technician@sermansa.ni',
            password='Password123*',
            full_name='Téc. Carlos Ruiz'
        )
        OrganizationMembership.objects.create(
            user=self.technician,
            organization=self.org,
            role_level=RoleLevel.TECHNICIAN,
            is_active=True,
        )

        self.commercial_mgr = User.objects.create_user(
            email='commercial@sermansa.ni',
            password='Password123*',
            full_name='Lic. Valentina Jarquín'
        )
        OrganizationMembership.objects.create(
            user=self.commercial_mgr,
            organization=self.org,
            role_level=RoleLevel.COMMERCIAL_MGR,
            is_active=True,
        )

        # Carpetas con políticas RBAC diferenciadas
        self.folder_ing = RepositoryFolder.objects.create(
            organization=self.org,
            code='FLD-ING-01',
            name='Planos y Manuales de Campo',
            department=RepositoryFolder.Department.ENGINEERING,
            min_role_level_view=RoleLevel.TECHNICIAN,  # 20
            min_role_level_upload=RoleLevel.ENGINEER,  # 50
        )

        self.folder_fin = RepositoryFolder.objects.create(
            organization=self.org,
            code='FLD-FIN-01',
            name='Contratos y Solvencias Fiscales DGI',
            department=RepositoryFolder.Department.FINANCE_LEGAL,
            min_role_level_view=RoleLevel.COMMERCIAL_MGR,  # 85
            min_role_level_upload=RoleLevel.COMMERCIAL_MGR,  # 85
        )

        # Documento inicial en Carpeta de Ingeniería
        self.doc_ing = CorporateDocument.objects.create(
            organization=self.org,
            code='DOC-2026-0001',
            folder=self.folder_ing,
            title='Diagrama Unifilar Subestación 15kV',
            document_type=CorporateDocument.DocumentType.CAD_PLAN,
            current_version_number=1,
            latest_filename='UNIFILAR-ISA-V1.CAD',
            latest_checksum='a'*64,
            is_locked=False,
            created_by=self.engineer,
        )

        self.ver_ing_v1 = DocumentVersion.objects.create(
            organization=self.org,
            document=self.doc_ing,
            version_number=1,
            filename='UNIFILAR-ISA-V1.CAD',
            file_size_kb=1500,
            content_summary_or_payload='Esquema base v1',
            checksum_sha256='a'*64,
            change_log='Emisión inicial para revisión.',
            uploaded_by=self.engineer,
        )

        # Documento confidencial en Carpeta de Finanzas
        self.doc_fin = CorporateDocument.objects.create(
            organization=self.org,
            code='DOC-2026-0002',
            folder=self.folder_fin,
            title='Constancia Fiscal DGI',
            document_type=CorporateDocument.DocumentType.TAX_LEGAL,
            current_version_number=1,
            latest_filename='DGI-2026.PDF',
            latest_checksum='b'*64,
            is_locked=False,
            created_by=self.commercial_mgr,
        )

        self.ver_fin_v1 = DocumentVersion.objects.create(
            organization=self.org,
            document=self.doc_fin,
            version_number=1,
            filename='DGI-2026.PDF',
            file_size_kb=500,
            content_summary_or_payload='Solvencia DGI',
            checksum_sha256='b'*64,
            change_log='Emisión fiscal.',
            uploaded_by=self.commercial_mgr,
        )

    def test_concurrent_versioning_and_unique_checksums(self):
        """
        Un Ingeniero (50) publica la versión v2 y v3 de un plano en FLD-ING-01.
        Verifica que se generen checksum_sha256 únicos e incremente current_version_number = 3.
        """
        # Publicar versión v2
        doc, v2 = publish_new_document_version(
            organization=self.org,
            document_id=self.doc_ing.pk,
            filename='UNIFILAR-ISA-V2.PDF',
            file_size_kb=2100,
            change_log='Ajuste de coordinación de relevadores y protecciones.',
            content_payload='Payload técnico revisión 2',
            user=self.engineer,
            role_level=RoleLevel.ENGINEER,
        )
        self.assertEqual(doc.current_version_number, 2)
        self.assertEqual(v2.version_number, 2)
        self.assertNotEqual(v2.checksum_sha256, self.ver_ing_v1.checksum_sha256)

        # Publicar versión v3
        doc, v3 = publish_new_document_version(
            organization=self.org,
            document_id=self.doc_ing.pk,
            filename='UNIFILAR-ISA-V3.PDF',
            file_size_kb=2400,
            change_log='Aprobación ejecutiva final con visto bueno ENATREL.',
            content_payload='Payload técnico revisión 3 ejecutiva',
            user=self.engineer,
            role_level=RoleLevel.ENGINEER,
        )
        self.assertEqual(doc.current_version_number, 3)
        self.assertEqual(v3.version_number, 3)
        self.assertNotEqual(v3.checksum_sha256, v2.checksum_sha256)
        self.assertEqual(doc.latest_filename, 'UNIFILAR-ISA-V3.PDF')
        self.assertEqual(doc.latest_checksum, v3.checksum_sha256)
        self.assertEqual(self.doc_ing.versions.count(), 3)

    def test_document_version_strict_immutability(self):
        """
        Intentar editar o borrar un DocumentVersion existente lanza ValidationError.
        """
        v1 = DocumentVersion.objects.get(pk=self.ver_ing_v1.pk)

        # Intento de modificación directa
        v1.filename = 'ARCHIVO_ALTERADO.PDF'
        with self.assertRaises(ValidationError):
            v1.save()

        # Intento de eliminación directa
        with self.assertRaises(ValidationError):
            v1.delete()

    def test_locked_document_prevents_new_version(self):
        """
        Un documento bloqueado administrativamente impide publicar nuevas versiones.
        """
        self.doc_ing.is_locked = True
        self.doc_ing.save()

        with self.assertRaises(ValidationError):
            publish_new_document_version(
                organization=self.org,
                document_id=self.doc_ing.pk,
                filename='UNIFILAR-ISA-V2.PDF',
                file_size_kb=2100,
                change_log='Intento de actualización en doc bloqueado',
                content_payload='Payload',
                user=self.engineer,
                role_level=RoleLevel.ENGINEER,
            )

    def test_rbac_folder_view_and_upload_permissions(self):
        """
        El Técnico (20) ve FLD-ING-01 (min_role_level_view=20), pero recibe HTTP 403
        si intenta subir una nueva versión (min_role_level_upload=50)
        y NO ve ni puede abrir FLD-FIN-01 (min_role_level_view=85, devuelve HTTP 403).
        """
        # 1. Técnico consulta FLD-ING-01 -> 200 OK
        self.client.force_login(self.technician)
        res = self.client.get(f'/repository/?folder={self.folder_ing.pk}')
        self.assertEqual(res.status_code, 200)

        # 2. Técnico intenta subir nueva versión a DOC-ING (min_role_level_upload=50) -> 403 Forbidden
        upload_url = reverse('repository:document_new_version', kwargs={'pk': self.doc_ing.pk})
        res_upload = self.client.post(upload_url, {
            'filename': 'PLANO-TECNICO-V2.PDF',
            'file_size_kb': 1200,
            'change_log': 'Intento de subida por técnico',
            'content_payload': 'Payload',
        })
        self.assertEqual(res_upload.status_code, 403)

        # 3. Técnico intenta consultar FLD-FIN-01 (min_role_level_view=85) -> 403 Forbidden
        res_fin_folder = self.client.get(f'/repository/?folder={self.folder_fin.pk}')
        self.assertEqual(res_fin_folder.status_code, 403)

        # 4. Técnico intenta ver detalle de DOC-FIN (min_role_level_view=85) -> 403 Forbidden
        res_fin_doc = self.client.get(reverse('repository:document_detail', kwargs={'pk': self.doc_fin.pk}))
        self.assertEqual(res_fin_doc.status_code, 403)

        # 5. Gerente Comercial (85) consulta FLD-FIN-01 y DOC-FIN -> 200 OK
        self.client.force_login(self.commercial_mgr)
        res_mgr = self.client.get(f'/repository/?folder={self.folder_fin.pk}')
        self.assertEqual(res_mgr.status_code, 200)
        res_mgr_doc = self.client.get(reverse('repository:document_detail', kwargs={'pk': self.doc_fin.pk}))
        self.assertEqual(res_mgr_doc.status_code, 200)

        # 6. Ingeniero (50) publica con éxito v2 en DOC-ING (min_role_level_upload=50)
        self.client.force_login(self.engineer)
        res_eng_upload = self.client.post(upload_url, {
            'filename': 'PLANO-INGENIERIA-V2.PDF',
            'file_size_kb': 2200,
            'change_log': 'Versión v2 aprobada por residente',
            'content_payload': 'Payload plano aprobado',
        })
        self.assertEqual(res_eng_upload.status_code, 302)
        self.doc_ing.refresh_from_db()
        self.assertEqual(self.doc_ing.current_version_number, 2)
