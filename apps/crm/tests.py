from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import CountryConfig
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel
from apps.crm.models import Account, AccountContact, Opportunity, Quote, QuoteItem

User = get_user_model()


class CrmModuleEndToEndTestCase(TestCase):
    """
    Suite de Pruebas End-to-End para el Módulo Comercial (CRM).
    Valida Aislamiento Multi-Tenant, Matemática Bimonetaria de Cotizaciones (DGI Nicaragua),
    Efectos de Aprobación y Matriz Estricta de Seguridad RBAC.
    """
    def setUp(self):
        # 1. Configuración de Jurisdicción Fiscal Nicaragua (NI)
        self.country_ni, _ = CountryConfig.objects.get_or_create(
            code='NI',
            defaults={
                'name': 'Nicaragua',
                'flag_emoji': '🇳🇮',
                'primary_currency_code': 'NIO',
                'primary_currency_symbol': 'C$',
                'secondary_currency_code': 'USD',
                'secondary_currency_symbol': '$',
                'tax_id_label': 'RUC',
                'tax_id_regex': r'^[A-Z]\d{13}$',
                'personal_id_label': 'Cédula de Identidad',
                'personal_id_regex': r'^\d{3}-\d{6}-\d{4}[A-Z]$',
                'default_tax_name': 'IVA',
                'default_tax_rate': Decimal('15.00'),
                'is_active': True,
            }
        )

        # 2. Organización Operativa Principal
        self.org = Organization.objects.create(
            name="Vector Ingeniería Nicaragua, S.A.",
            legal_name="Vector Ingeniería de Centroamérica, S.A.",
            slug="vector-ni",
            tax_id="J0310000199999",
            country=self.country_ni,
            enabled_modules=['crm', 'operations', 'sst', 'inventory'],
            is_active=True,
        )

        # Organización Invasora (Para verificar Aislamiento Multi-Tenant)
        self.org_intruder = Organization.objects.create(
            name="Empresa Competidora S.A.",
            legal_name="Competidora S.A.",
            slug="competidora-ni",
            tax_id="J0310000188888",
            country=self.country_ni,
            enabled_modules=['crm'],
            is_active=True,
        )

        # 3. Usuarios de Distintos Niveles Jerárquicos RBAC
        # Nivel 100: Owner / Administrador General
        self.user_owner = User.objects.create_user(
            email='owner@vector.com.ni',
            full_name='Lic. Fernando Morales (Owner)',
            password='password123'
        )
        OrganizationMembership.objects.create(
            user=self.user_owner,
            organization=self.org,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 85: Gerente Comercial
        self.user_comm_mgr = User.objects.create_user(
            email='comercial@vector.com.ni',
            full_name='Lic. Sofía Alemán (Comercial)',
            password='password123'
        )
        OrganizationMembership.objects.create(
            user=self.user_comm_mgr,
            organization=self.org,
            role_level=RoleLevel.COMMERCIAL_MGR,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 80: Coordinador de Operaciones
        self.user_ops_coord = User.objects.create_user(
            email='operaciones@vector.com.ni',
            full_name='Ing. Marcos Ruiz (Coordinador)',
            password='password123'
        )
        OrganizationMembership.objects.create(
            user=self.user_ops_coord,
            organization=self.org,
            role_level=RoleLevel.OPERATIONS_COORD,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 50: Ingeniero / Residente
        self.user_engineer = User.objects.create_user(
            email='ingeniero@vector.com.ni',
            full_name='Ing. Roberto Solís (Ingeniero)',
            password='password123'
        )
        OrganizationMembership.objects.create(
            user=self.user_engineer,
            organization=self.org,
            role_level=RoleLevel.ENGINEER,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 20: Técnico de Campo
        self.user_tech = User.objects.create_user(
            email='tecnico@vector.com.ni',
            full_name='Juan Pérez (Técnico)',
            password='password123'
        )
        OrganizationMembership.objects.create(
            user=self.user_tech,
            organization=self.org,
            role_level=RoleLevel.TECHNICIAN,
            is_active=True,
            is_default_org=True,
        )

    # --------------------------------------------------------------------------
    # TEST 1: Modelos Transaccionales, Códigos Correlativos y Aislamiento Tenant
    # --------------------------------------------------------------------------
    def test_account_creation_validation_and_autocode(self):
        """Verifica validación de RUC nicaragüense y correlativo automático CLI-0001."""
        account = Account.objects.create(
            organization=self.org,
            commercial_name="Ingenio Monte Rosa",
            legal_name="Pantaleon Nicaragua S.A.",
            tax_id="J0310000112233",
            account_type=Account.AccountType.CORPORATE,
            lifecycle_stage=Account.LifecycleStage.PROSPECT,
            city="Chinandega",
            default_currency="NIO",
            payment_terms_days=30,
        )
        self.assertEqual(account.code, "CLI-0001")
        self.assertEqual(account.commercial_name, "Ingenio Monte Rosa")

        # Contacto técnico asociado
        contact = AccountContact.objects.create(
            organization=self.org,
            account=account,
            full_name="Ing. Carlos Gutiérrez",
            job_title="Gerente de Planta",
            email="cgutierrez@monterosa.com.ni",
            phone="+505 8888-1234",
            is_primary=True,
        )
        self.assertTrue(contact.is_primary)
        self.assertEqual(account.contacts.count(), 1)

        # Oportunidad asociada
        opp = Opportunity.objects.create(
            organization=self.org,
            account=account,
            title="Modernización de Subestación Eléctrica 138kV",
            stage=Opportunity.Stage.NEW,
            currency="NIO",
            estimated_value=Decimal('150000.00'),
        )
        self.assertTrue(opp.code.startswith("OP-"))
        self.assertEqual(opp.account, account)

        # Verificar Aislamiento Multi-Tenant estricto
        org_accounts = Account.objects.for_org(self.org)
        intruder_accounts = Account.objects.for_org(self.org_intruder)
        self.assertIn(account, org_accounts)
        self.assertNotIn(account, intruder_accounts)

    # --------------------------------------------------------------------------
    # TEST 2: Matemática de Cotización, Precisión Decimal e IVA 15% DGI
    # --------------------------------------------------------------------------
    def test_quote_exact_calculation_and_approval_transition(self):
        """
        Prueba matemática estricta:
        - Partida 1 (Servicio): 1 UND x C$ 50,000.00, desc 0% = C$ 50,000.00
        - Partida 2 (Material): 2 UND x C$ 25,000.00, desc 10% = C$ 45,000.00 (Bruto 50,000.00 - Descuento 5,000.00)
        - Subtotal: C$ 100,000.00
        - Descuento Total: C$ 5,000.00
        - Base Imponible: C$ 95,000.00
        - IVA 15.00%: C$ 14,250.00 (95,000.00 x 0.15)
        - Total General: C$ 109,250.00
        """
        account = Account.objects.create(
            organization=self.org,
            commercial_name="Distribuidora Eléctrica del Norte S.A.",
            tax_id="J0310000112233",
            lifecycle_stage=Account.LifecycleStage.PROSPECT,
        )

        opp = Opportunity.objects.create(
            organization=self.org,
            account=account,
            title="Suministro de Transformadores",
            stage=Opportunity.Stage.PROPOSAL,
            currency="NIO",
            estimated_value=Decimal('109250.00'),
        )

        quote = Quote.objects.create(
            organization=self.org,
            account=account,
            opportunity=opp,
            title="Suministro e Instalación de Subestación",
            currency_code="NIO",
            currency_symbol="C$",
            exchange_rate=Decimal('36.6243'),
            tax_name="IVA",
            tax_rate=Decimal('15.00'),
            apply_tax=True,
            created_by=self.user_comm_mgr,
        )
        self.assertTrue(quote.number.startswith("COT-"))

        # Agregar Partida 1: Servicio
        item1 = QuoteItem.objects.create(
            organization=self.org,
            quote=quote,
            item_type=QuoteItem.ItemType.SERVICE,
            code="SRV-ING-01",
            description="Diagnóstico y Pruebas de Resistencia en Bobinados",
            unit="GLB",
            quantity=Decimal('1.00'),
            unit_price=Decimal('50000.00'),
            discount_percent=Decimal('0.00'),
        )
        self.assertEqual(item1.line_total, Decimal('50000.00'))

        # Agregar Partida 2: Material con 10% de descuento
        item2 = QuoteItem.objects.create(
            organization=self.org,
            quote=quote,
            item_type=QuoteItem.ItemType.MATERIAL,
            code="MAT-CAB-01",
            description="Cable de Potencia 15kV y Terminales Contráctiles",
            unit="MTS",
            quantity=Decimal('2.00'),
            unit_price=Decimal('25000.00'),
            discount_percent=Decimal('10.00'),
        )
        self.assertEqual(item2.line_total, Decimal('45000.00'))

        # Recargar cotización para verificar totales automáticos
        quote.refresh_from_db()

        self.assertEqual(quote.subtotal, Decimal('100000.00'))
        self.assertEqual(quote.discount_total, Decimal('5000.00'))
        self.assertEqual(quote.tax_total, Decimal('14250.00'))
        self.assertEqual(quote.grand_total, Decimal('109250.00'))

        # Probar Transición de Aprobación Formal
        client = Client()
        client.login(email='comercial@vector.com.ni', password='password123')
        session = client.session
        session['active_org_id'] = str(self.org.id)
        session.save()

        response = client.post(
            reverse('crm:quote_status_transition', kwargs={'pk': quote.pk}),
            data={'status': Quote.Status.APPROVED}
        )
        self.assertEqual(response.status_code, 302)

        quote.refresh_from_db()
        account.refresh_from_db()
        opp.refresh_from_db()

        # Verificar Estado Aprobado y Trazabilidad
        self.assertEqual(quote.status, Quote.Status.APPROVED)
        self.assertEqual(quote.approved_by, self.user_comm_mgr)
        self.assertIsNotNone(quote.approved_at)

        # Verificar Efectos Colaterales de Aprobación
        self.assertEqual(account.lifecycle_stage, Account.LifecycleStage.ACTIVE)
        self.assertEqual(opp.stage, Opportunity.Stage.WON)

    # --------------------------------------------------------------------------
    # TEST 3: Manejo de Cliente Exento de IVA
    # --------------------------------------------------------------------------
    def test_tax_exempt_account_calculation(self):
        """Verifica que si la cuenta tiene is_tax_exempt=True, el IVA es 0.00."""
        account_exempt = Account.objects.create(
            organization=self.org,
            commercial_name="Organismo Internacional Exento",
            tax_id="J0310000112233",
            is_tax_exempt=True,
        )

        quote = Quote.objects.create(
            organization=self.org,
            account=account_exempt,
            title="Servicio Especial de Consultoría",
            currency_code="NIO",
            tax_rate=Decimal('15.00'),
            apply_tax=True,
        )

        QuoteItem.objects.create(
            organization=self.org,
            quote=quote,
            item_type=QuoteItem.ItemType.SERVICE,
            description="Estudio de Calidad de Energía",
            quantity=Decimal('1.00'),
            unit_price=Decimal('20000.00'),
            discount_percent=Decimal('0.00'),
        )

        quote.refresh_from_db()
        self.assertEqual(quote.subtotal, Decimal('20000.00'))
        self.assertEqual(quote.tax_total, Decimal('0.00'))
        self.assertEqual(quote.grand_total, Decimal('20000.00'))

    # --------------------------------------------------------------------------
    # TEST 4: Matriz Estricta de Jerarquía RBAC en Rutas /crm/*
    # --------------------------------------------------------------------------
    def test_rbac_hierarchy_permissions(self):
        """
        Verifica cumplimiento de permisos:
        1. OWNER (100) y COMMERCIAL_MGR (85): 200 en lectura, 200/302 en escritura/aprobación.
        2. OPERATIONS_COORD (80): 200 en lectura (directorio, pipeline, detalle cotización),
           pero 403 en escritura (crear cliente, agregar ítems, aprobar cotización, mover etapa).
        3. ENGINEER (50) y TECHNICIAN (20): 403 en TODAS las rutas de /crm/*.
        """
        account = Account.objects.create(
            organization=self.org,
            commercial_name="Empresa Minera San Albino",
            tax_id="J0310000112233",
        )
        opp = Opportunity.objects.create(
            organization=self.org,
            account=account,
            title="Mantenimiento Generador Diésel",
        )
        quote = Quote.objects.create(
            organization=self.org,
            account=account,
            title="Cotización Servicio Mina",
            currency_code="NIO",
            created_by=self.user_comm_mgr,
        )

        # ----------------------------------------------------------------------
        # A) Rol 85: Gerente Comercial -> Acceso Total
        # ----------------------------------------------------------------------
        client_85 = Client()
        client_85.login(email='comercial@vector.com.ni', password='password123')
        s85 = client_85.session
        s85['active_org_id'] = str(self.org.id)
        s85.save()

        # Lectura
        self.assertEqual(client_85.get(reverse('crm:account_list')).status_code, 200)
        self.assertEqual(client_85.get(reverse('crm:account_detail', kwargs={'pk': account.pk})).status_code, 200)
        self.assertEqual(client_85.get(reverse('crm:opportunity_kanban')).status_code, 200)
        self.assertEqual(client_85.get(reverse('crm:quote_list')).status_code, 200)
        self.assertEqual(client_85.get(reverse('crm:quote_detail', kwargs={'pk': quote.pk})).status_code, 200)
        self.assertEqual(client_85.get(reverse('crm:quote_print', kwargs={'pk': quote.pk})).status_code, 200)

        # Escritura
        self.assertEqual(client_85.get(reverse('crm:account_create')).status_code, 200)
        self.assertEqual(client_85.get(reverse('crm:quote_create')).status_code, 200)

        # ----------------------------------------------------------------------
        # B) Rol 80: Coordinador de Operaciones -> Solo Lectura Técnica
        # ----------------------------------------------------------------------
        client_80 = Client()
        client_80.login(email='operaciones@vector.com.ni', password='password123')
        s80 = client_80.session
        s80['active_org_id'] = str(self.org.id)
        s80.save()

        # Lectura Permitida (HTTP 200)
        self.assertEqual(client_80.get(reverse('crm:account_list')).status_code, 200)
        self.assertEqual(client_80.get(reverse('crm:account_detail', kwargs={'pk': account.pk})).status_code, 200)
        self.assertEqual(client_80.get(reverse('crm:opportunity_kanban')).status_code, 200)
        self.assertEqual(client_80.get(reverse('crm:quote_list')).status_code, 200)
        self.assertEqual(client_80.get(reverse('crm:quote_detail', kwargs={'pk': quote.pk})).status_code, 200)
        self.assertEqual(client_80.get(reverse('crm:quote_print', kwargs={'pk': quote.pk})).status_code, 200)

        # Escritura Bloqueada por RBAC (HTTP 403)
        self.assertEqual(client_80.get(reverse('crm:account_create')).status_code, 403)
        self.assertEqual(client_80.post(reverse('crm:account_create'), data={}).status_code, 403)
        self.assertEqual(client_80.get(reverse('crm:quote_create')).status_code, 403)
        self.assertEqual(
            client_80.post(
                reverse('crm:quote_add_item', kwargs={'pk': quote.pk}),
                data={'description': 'Intento Invalido'}
            ).status_code,
            403
        )
        self.assertEqual(
            client_80.post(
                reverse('crm:quote_status_transition', kwargs={'pk': quote.pk}),
                data={'status': Quote.Status.APPROVED}
            ).status_code,
            403
        )
        self.assertEqual(
            client_80.post(
                reverse('crm:opportunity_stage_update', kwargs={'pk': opp.pk}),
                data={'stage': Opportunity.Stage.WON}
            ).status_code,
            403
        )

        # ----------------------------------------------------------------------
        # C) Rol 50: Ingeniero / Residente -> Bloqueo Completo en CRM (HTTP 403)
        # ----------------------------------------------------------------------
        client_50 = Client()
        client_50.login(email='ingeniero@vector.com.ni', password='password123')
        s50 = client_50.session
        s50['active_org_id'] = str(self.org.id)
        s50.save()

        self.assertEqual(client_50.get(reverse('crm:account_list')).status_code, 403)
        self.assertEqual(client_50.get(reverse('crm:opportunity_kanban')).status_code, 403)
        self.assertEqual(client_50.get(reverse('crm:quote_list')).status_code, 403)
        self.assertEqual(client_50.get(reverse('crm:quote_detail', kwargs={'pk': quote.pk})).status_code, 403)

        # ----------------------------------------------------------------------
        # D) Rol 20: Técnico de Campo -> Bloqueo Inmediato en CRM (HTTP 403)
        # ----------------------------------------------------------------------
        client_20 = Client()
        client_20.login(email='tecnico@vector.com.ni', password='password123')
        s20 = client_20.session
        s20['active_org_id'] = str(self.org.id)
        s20.save()

        self.assertEqual(client_20.get(reverse('crm:account_list')).status_code, 403)
        self.assertEqual(client_20.get(reverse('crm:opportunity_kanban')).status_code, 403)
        self.assertEqual(client_20.get(reverse('crm:quote_list')).status_code, 403)
        self.assertEqual(client_20.get(reverse('crm:quote_detail', kwargs={'pk': quote.pk})).status_code, 403)

        # ----------------------------------------------------------------------
        # E) Rol 100: Owner / Administrador General -> Acceso Total
        # ----------------------------------------------------------------------
        client_100 = Client()
        client_100.login(email='owner@vector.com.ni', password='password123')
        s100 = client_100.session
        s100['active_org_id'] = str(self.org.id)
        s100.save()

        self.assertEqual(client_100.get(reverse('crm:account_list')).status_code, 200)
        self.assertEqual(client_100.get(reverse('crm:quote_detail', kwargs={'pk': quote.pk})).status_code, 200)
        self.assertEqual(client_100.get(reverse('crm:quote_create')).status_code, 200)
