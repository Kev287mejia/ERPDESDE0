from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import CountryConfig
from apps.crm.models import Account
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel, SaasSubscriptionInvoice

User = get_user_model()


class SaasHQMonetizationAndLocksTestCase(TestCase):
    """
    Suite de pruebas integrales para el Paso 15.1:
    - Consola Ejecutiva de Monetización SaaS HQ (MRR / ARR bimonetario).
    - Conmutador de Planes de Suscripción (STARTER, PYME_PRO, ENTERPRISE).
    - Candado de Límite de Asientos (max_users).
    - Candado de Suspensión por Mora (SUSPENDED -> Modo Solo Lectura para mutaciones POST).
    - Seguridad RBAC en /saas-hq/* (Exclusivo RoleLevel.OWNER_ADMIN 100).
    - Endpoint público de salud /healthz/ para infraestructura Docker.
    """

    def setUp(self):
        self.country_ni, _ = CountryConfig.objects.get_or_create(
            code='NI',
            defaults={
                'name': 'Nicaragua',
                'flag_emoji': '🇳🇮',
                'primary_currency_code': 'NIO',
                'primary_currency_symbol': 'C$',
                'tax_id_label': 'RUC',
                'tax_id_regex': r'^[A-Z]\d{13}$',
                'is_active': True,
                'default_tax_rate': Decimal('15.00'),
                'default_tax_name': 'IVA',
            }
        )

        # Organización de prueba
        self.org = Organization.objects.create(
            name='SERMANSA Industrial',
            slug='sermansa-industrial',
            legal_name='Servicios y Mantenimiento Electromecánico S.A.',
            tax_id='J0310000458912',
            country=self.country_ni,
            currency=Organization.Currency.NIO,
            subscription_plan=Organization.SubscriptionPlan.ENTERPRISE,
            subscription_status=Organization.SubscriptionStatus.ACTIVE,
            monthly_fee_usd=Decimal('249.00'),
            max_users=999,
            enabled_modules=['crm', 'operations', 'inventory', 'finance', 'billing', 'purchasing'],
            onboarding_completed=True,
            is_active=True,
        )

        # Usuario Superadministrador de Plataforma (Eternal Labs HQ)
        self.owner = User.objects.create_user(
            email='admin@sermansa.ni',
            password='Password123!',
            full_name='Ing. Carlos Mendoza Rivas',
            is_superuser=True,
            is_staff=True,
        )
        self.mem_owner = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.owner,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
        )

        # Usuario Comercial (RoleLevel 85)
        self.commercial = User.objects.create_user(
            email='comercial@sermansa.ni',
            password='Password123!',
            full_name='Lic. Valentina Jarquín Rivas',
        )
        self.mem_commercial = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.commercial,
            role_level=RoleLevel.COMMERCIAL_MGR,
            is_active=True,
        )

        # Cliente para pruebas con login Owner
        self.client_owner = Client()
        self.client_owner.force_login(self.owner)
        s = self.client_owner.session
        s['active_org_id'] = str(self.org.id)
        s.save()

        # Cliente para pruebas con login Comercial
        self.client_commercial = Client()
        self.client_commercial.force_login(self.commercial)
        s2 = self.client_commercial.session
        s2['active_org_id'] = str(self.org.id)
        s2.save()

    def test_saas_plan_switching_helper_and_pricing_tiers(self):
        """Verifica la lógica de negocio y tarifas de conmutación de planes SaaS."""
        # 1. Conmutar a STARTER
        self.org.apply_subscription_plan(Organization.SubscriptionPlan.STARTER)
        self.assertEqual(self.org.subscription_plan, Organization.SubscriptionPlan.STARTER)
        self.assertEqual(self.org.monthly_fee_usd, Decimal('49.00'))
        self.assertEqual(self.org.max_users, 5)

        # 2. Conmutar a PYME_PRO
        self.org.apply_subscription_plan(Organization.SubscriptionPlan.PYME_PRO)
        self.assertEqual(self.org.subscription_plan, Organization.SubscriptionPlan.PYME_PRO)
        self.assertEqual(self.org.monthly_fee_usd, Decimal('119.00'))
        self.assertEqual(self.org.max_users, 15)

        # 3. Conmutar a ENTERPRISE
        self.org.apply_subscription_plan(Organization.SubscriptionPlan.ENTERPRISE)
        self.assertEqual(self.org.subscription_plan, Organization.SubscriptionPlan.ENTERPRISE)
        self.assertEqual(self.org.monthly_fee_usd, Decimal('249.00'))
        self.assertEqual(self.org.max_users, 999)

    def test_saas_hq_dashboard_view_and_mrr_metrics(self):
        """Verifica que SaasHQDashboardView calcule métricas bimonetarias MRR y ARR."""
        # Crear segunda organización en TRIAL para verificar suma de MRR
        Organization.objects.create(
            name='Agroquímica del Norte',
            slug='agroquimica-del-norte',
            legal_name='Agroquímica del Norte S.A.',
            tax_id='J0310000998877',
            country=self.country_ni,
            subscription_plan=Organization.SubscriptionPlan.STARTER,
            subscription_status=Organization.SubscriptionStatus.TRIAL,
            monthly_fee_usd=Decimal('49.00'),
            max_users=5,
            is_active=True,
        )

        response = self.client_owner.get(reverse('tenancy:saas_hq'))
        self.assertEqual(response.status_code, 200)

        # MRR esperado: 249.00 (SERMANSA) + 49.00 (Agroquímica) = 298.00 USD
        self.assertEqual(response.context['total_mrr_usd'], Decimal('298.00'))
        expected_nio = (Decimal('298.00') * Decimal('36.6243')).quantize(Decimal('0.01'))
        self.assertEqual(response.context['total_mrr_nio'], expected_nio)

        # ARR esperado: 298.00 * 12 = 3576.00 USD
        self.assertEqual(response.context['total_arr_usd'], Decimal('3576.00'))

    def test_saas_switch_plan_view_via_post(self):
        """Verifica la conmutación de plan desde la interfaz SaaS HQ mediante POST."""
        response = self.client_owner.post(
            reverse('tenancy:saas_switch_plan'),
            data={'subscription_plan': 'PYME_PRO'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        self.org.refresh_from_db()
        self.assertEqual(self.org.subscription_plan, Organization.SubscriptionPlan.PYME_PRO)
        self.assertEqual(self.org.monthly_fee_usd, Decimal('119.00'))
        self.assertEqual(self.org.max_users, 15)

    def test_saas_generate_invoice_view_creates_correlative_receipt(self):
        """Verifica la emisión de comprobante de facturación de suscripción SaaS correlativo."""
        response = self.client_owner.post(
            reverse('tenancy:saas_generate_invoice'),
            data={
                'billing_period': '2026-11',
                'status': 'PAID',
                'payment_reference': 'TEST-STRIPE-NI-001',
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        invoice = SaasSubscriptionInvoice.objects.filter(
            organization=self.org,
            billing_period='2026-11'
        ).first()
        self.assertIsNotNone(invoice)
        self.assertTrue(invoice.number.startswith('SAAS-'))
        self.assertEqual(invoice.amount_usd, Decimal('249.00'))
        self.assertEqual(invoice.exchange_rate, Decimal('36.6243'))
        self.assertEqual(invoice.status, SaasSubscriptionInvoice.Status.PAID)

    def test_user_seat_quota_lock_enforcement(self):
        """
        Verifica el candado de cuota de asientos (max_users).
        En plan STARTER (límite 5 asientos), al alcanzar la cuota se bloquea
        el alta de nuevos colaboradores en /settings/team/create/.
        """
        # Configurar organización en plan STARTER (límite 5)
        self.org.apply_subscription_plan(Organization.SubscriptionPlan.STARTER)
        self.org.refresh_from_db()
        self.assertEqual(self.org.max_users, 5)

        # Actualmente hay 2 miembros (owner + commercial). Añadimos 3 más para completar 5.
        for i in range(3):
            extra_user = User.objects.create_user(
                email=f'user{i}@sermansa.ni',
                password='Password123!',
                full_name=f'Colaborador Extra {i}',
            )
            OrganizationMembership.objects.create(
                organization=self.org,
                user=extra_user,
                role_level=RoleLevel.TECHNICIAN,
                is_active=True,
            )

        self.assertEqual(self.org.active_members_count(), 5)
        can_add, reason = self.org.can_add_more_users()
        self.assertFalse(can_add)
        self.assertIn("Límite de asientos alcanzado", reason)

        # Intentar crear un 6to miembro debe ser RECHAZADO con HTTP 403
        response = self.client_owner.post(
            reverse('tenancy:team_create'),
            data={
                'email': 'rejected_user@sermansa.ni',
                'full_name': 'Ing. Candidato Rechazado',
                'role_level': RoleLevel.TECHNICIAN,
                'job_title': 'Técnico de Campo',
            }
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.org.active_members_count(), 5)

        # Al ampliar a PYME_PRO (15 usuarios), el candado se desbloquea
        self.org.apply_subscription_plan(Organization.SubscriptionPlan.PYME_PRO)
        can_add_now, _ = self.org.can_add_more_users()
        self.assertTrue(can_add_now)

    def test_saas_suspension_locks_operational_mutations_into_read_only(self):
        """
        Verifica el candado de suspensión comercial:
        - Si subscription_status == 'SUSPENDED':
          * GET en módulos operativos sigue funcionando (HTTP 200).
          * POST en módulos operativos es bloqueado con HTTP 403 (aviso de suspensión).
          * POST en /saas-hq/update-status/ está exento y permite reactivar la organización a 'ACTIVE'.
          * Tras reactivar a 'ACTIVE', las operaciones POST se restauran con éxito.
        """
        # 1. Suspender la organización
        self.org.subscription_status = Organization.SubscriptionStatus.SUSPENDED
        self.org.save(update_fields=['subscription_status'])
        self.assertTrue(self.org.is_write_blocked_by_saas_suspension())

        # 2. Consultas GET siguen funcionando (Modo Consulta / Auditoría)
        get_response = self.client_owner.get(reverse('crm:account_list'))
        self.assertEqual(get_response.status_code, 200)

        # 3. Mutación POST en CRM (crear cliente) debe ser bloqueada con HTTP 403
        post_response = self.client_owner.post(
            reverse('crm:account_create'),
            data={
                'commercial_name': 'Cliente Bloqueado por Mora',
                'legal_name': 'Cliente Bloqueado S.A.',
                'account_type': Account.AccountType.CORPORATE,
                'lifecycle_stage': Account.LifecycleStage.PROSPECT,
                'tax_id': 'J0310000112233',
                'default_currency': 'NIO',
            }
        )
        self.assertEqual(post_response.status_code, 403)
        self.assertContains(post_response, "SUSPENSIÓN COMERCIAL SAAS", status_code=403)
        self.assertFalse(Account.objects.filter(tax_id='J0310000112233').exists())

        # 4. Reactivación desde /saas-hq/update-status/ (Exento del candado para permitir autogestión)
        reactivate_response = self.client_owner.post(
            reverse('tenancy:saas_update_status'),
            data={'subscription_status': 'ACTIVE'},
            follow=True,
        )
        self.assertEqual(reactivate_response.status_code, 200)

        self.org.refresh_from_db()
        self.assertEqual(self.org.subscription_status, Organization.SubscriptionStatus.ACTIVE)
        self.assertFalse(self.org.is_write_blocked_by_saas_suspension())

        # 5. La mutación POST ahora se ejecuta correctamente
        restore_post_response = self.client_owner.post(
            reverse('crm:account_create'),
            data={
                'commercial_name': 'Cliente Habilitado Post-Reactivación',
                'legal_name': 'Cliente Habilitado S.A.',
                'account_type': Account.AccountType.CORPORATE,
                'lifecycle_stage': Account.LifecycleStage.PROSPECT,
                'tax_id': 'J0310000112233',
                'city': 'Managua',
                'default_currency': 'NIO',
                'payment_terms_days': 0,
            },
            follow=True,
        )
        self.assertEqual(restore_post_response.status_code, 200)
        self.assertTrue(Account.objects.filter(tax_id='J0310000112233').exists())

    def test_rbac_security_on_saas_hq_endpoints(self):
        """
        Verifica que un usuario con nivel subordinado (< 100, ej: Commercial Mgr 85)
        reciba HTTP 403 al intentar acceder a la consola SaaS HQ.
        """
        # GET /saas-hq/ como Commercial Manager (85) -> 403
        response_get = self.client_commercial.get(reverse('tenancy:saas_hq'))
        self.assertEqual(response_get.status_code, 403)

        # POST /saas-hq/switch-plan/ como Commercial Manager (85) -> 403
        response_post = self.client_commercial.post(
            reverse('tenancy:saas_switch_plan'),
            data={'subscription_plan': 'STARTER'},
        )
        self.assertEqual(response_post.status_code, 403)

    def test_system_healthcheck_endpoint_healthz(self):
        """
        Verifica el endpoint público /healthz/ para Docker y balanceadores de carga.
        No requiere sesión ni autenticación, ejecuta SELECT 1 y devuelve JSON status 200.
        """
        anonymous_client = Client()
        response = anonymous_client.get('/healthz/')
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data.get('status'), 'ok')
        self.assertEqual(data.get('service'), 'VECTOR-ERP-SAS')
        self.assertEqual(data.get('database'), 'connected')
        self.assertEqual(data.get('country_engine'), 'NI-DGI-822')
        self.assertIn('latency_ms', data)
        self.assertIsInstance(data['latency_ms'], (int, float))


class SaasHqSecurityPhase1ATestCase(TestCase):
    """
    Suite de Pruebas de Regresión de Seguridad — Fase 1A (Aislamiento y Autorización SaaS HQ).
    Verifica que:
    1. Usuario anónimo: acceso denegado (403) a todas las rutas de SaaS HQ.
    2. Usuario cliente con rol Owner nivel 100 (sin is_superuser): acceso denegado (403).
    3. Usuario autenticado de una organización normal y roles subordinados (85, 80, etc.): acceso denegado (403).
    4. Intento de manipulación cruzada (cross-tenant tampering / data leak) por parte de cliente Owner: bloqueado (403).
    5. Superusuario autorizado de plataforma (is_superuser=True): acceso permitido (200 / 302).
    6. Protección individual y granular de cada operación: inspección, exportación, actualización de plan y suspensión.
    7. Métodos HTTP alternativos (PUT, DELETE, PATCH): bloqueados consistentemente por la compuerta de autorización (403).
    """

    def setUp(self):
        self.country_ni, _ = CountryConfig.objects.get_or_create(
            code='NI',
            defaults={
                'name': 'Nicaragua',
                'flag_emoji': '🇳🇮',
                'primary_currency_code': 'NIO',
                'primary_currency_symbol': 'C$',
                'tax_id_label': 'RUC',
                'tax_id_regex': r'^[A-Z]\d{13}$',
                'is_active': True,
                'default_tax_rate': Decimal('15.00'),
                'default_tax_name': 'IVA',
            }
        )

        # 1. Inquilino Cliente A
        self.org_client_a = Organization.objects.create(
            name='Farmacia Central S.A.',
            slug='farmacia-central',
            legal_name='Farmacia Central de Nicaragua S.A.',
            tax_id='J0310000888991',
            country=self.country_ni,
            currency=Organization.Currency.NIO,
            subscription_plan=Organization.SubscriptionPlan.BUSINESS_PRO,
            subscription_status=Organization.SubscriptionStatus.ACTIVE,
            monthly_fee_usd=Decimal('89.00'),
            max_users_quota=15,
            max_users=15,
            enabled_modules=['crm', 'inventory', 'billing'],
            onboarding_completed=True,
            is_active=True,
        )

        # 2. Inquilino Víctima B (Inquilino Objetivo para pruebas de manipulación cruzada)
        self.org_victim_b = Organization.objects.create(
            name='Ferretería El Tornillo S.A.',
            slug='ferreteria-el-tornillo',
            legal_name='Ferretería El Tornillo de Managua S.A.',
            tax_id='J0310000777662',
            country=self.country_ni,
            currency=Organization.Currency.NIO,
            subscription_plan=Organization.SubscriptionPlan.ENTERPRISE,
            subscription_status=Organization.SubscriptionStatus.ACTIVE,
            monthly_fee_usd=Decimal('199.00'),
            max_users_quota=50,
            max_users=50,
            enabled_modules=['crm', 'inventory', 'billing', 'purchasing'],
            onboarding_completed=True,
            is_active=True,
        )

        # Usuario Cliente: Propietario / Owner (Nivel 100 en su empresa, pero SIN privilegios globales)
        self.user_tenant_owner = User.objects.create_user(
            email='dueno@farmaciacentral.ni',
            password='Password123!',
            full_name='Lic. Marcio Somarriba (Owner Cliente)',
            is_superuser=False,
            is_staff=False,
        )
        self.mem_tenant_owner = OrganizationMembership.objects.create(
            organization=self.org_client_a,
            user=self.user_tenant_owner,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
        )
        self.client_tenant_owner = Client()
        self.client_tenant_owner.force_login(self.user_tenant_owner)
        session_a = self.client_tenant_owner.session
        session_a['active_org_id'] = str(self.org_client_a.id)
        session_a.save()

        # Usuario Cliente: Gerente Comercial (Nivel 85)
        self.user_commercial = User.objects.create_user(
            email='comercial@farmaciacentral.ni',
            password='Password123!',
            full_name='Valentina Comercial',
            is_superuser=False,
            is_staff=False,
        )
        self.mem_commercial = OrganizationMembership.objects.create(
            organization=self.org_client_a,
            user=self.user_commercial,
            role_level=RoleLevel.COMMERCIAL_MGR,
            is_active=True,
        )
        self.client_commercial = Client()
        self.client_commercial.force_login(self.user_commercial)
        session_comm = self.client_commercial.session
        session_comm['active_org_id'] = str(self.org_client_a.id)
        session_comm.save()

        # Usuario Superadministrador Global de Plataforma (Eternal Labs)
        self.user_platform_superadmin = User.objects.create_user(
            email='superadmin@eternallabs.com',
            password='Password123!',
            full_name='Superadmin Global Eternal Labs',
            is_superuser=True,
            is_staff=True,
        )
        self.mem_superadmin = OrganizationMembership.objects.create(
            organization=self.org_client_a,
            user=self.user_platform_superadmin,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
        )
        self.client_superadmin = Client()
        self.client_superadmin.force_login(self.user_platform_superadmin)
        session_super = self.client_superadmin.session
        session_super['active_org_id'] = str(self.org_client_a.id)
        session_super.save()

        # Cliente Anónimo (Sin autenticar)
        self.client_anonymous = Client()

        # Lista de rutas bajo auditoría de SaaS HQ
        self.saas_hq_url = reverse('tenancy:saas_hq')
        self.switch_plan_url = reverse('tenancy:saas_switch_plan')
        self.update_status_url = reverse('tenancy:saas_update_status')
        self.generate_invoice_url = reverse('tenancy:saas_generate_invoice')
        self.backup_current_url = reverse('tenancy:saas_backup_export_current')
        self.backup_victim_url = reverse('tenancy:saas_backup_export', args=[str(self.org_victim_b.id)])

    def test_anonymous_user_denied_all_saas_hq_endpoints(self):
        """Verifica que un usuario no autenticado sea bloqueado con redirección (302 a login) en todas las rutas de SaaS HQ."""
        self.assertEqual(self.client_anonymous.get(self.saas_hq_url).status_code, 302)
        self.assertEqual(self.client_anonymous.post(self.saas_hq_url, data={}).status_code, 302)
        self.assertEqual(self.client_anonymous.post(self.switch_plan_url, data={'subscription_plan': 'STARTER'}).status_code, 302)
        self.assertEqual(self.client_anonymous.post(self.update_status_url, data={'subscription_status': 'ACTIVE'}).status_code, 302)
        self.assertEqual(self.client_anonymous.post(self.generate_invoice_url, data={}).status_code, 302)
        self.assertEqual(self.client_anonymous.get(self.backup_current_url).status_code, 302)
        self.assertEqual(self.client_anonymous.get(self.backup_victim_url).status_code, 302)

    def test_client_tenant_owner_level_100_denied_all_saas_hq_endpoints(self):
        """
        Verifica que un usuario cliente con rol Owner (Nivel 100) en su propia empresa
        pero sin privilegio global de superusuario (is_superuser=False) sea bloqueado estrictamente con 403.
        """
        self.assertEqual(self.client_tenant_owner.get(self.saas_hq_url).status_code, 403)
        self.assertEqual(self.client_tenant_owner.post(self.saas_hq_url, data={}).status_code, 403)
        self.assertEqual(self.client_tenant_owner.post(self.switch_plan_url, data={'subscription_plan': 'STARTER'}).status_code, 403)
        self.assertEqual(self.client_tenant_owner.post(self.update_status_url, data={'subscription_status': 'ACTIVE'}).status_code, 403)
        self.assertEqual(self.client_tenant_owner.post(self.generate_invoice_url, data={}).status_code, 403)
        self.assertEqual(self.client_tenant_owner.get(self.backup_current_url).status_code, 403)
        self.assertEqual(self.client_tenant_owner.get(self.backup_victim_url).status_code, 403)

    def test_authenticated_normal_org_subordinate_roles_denied(self):
        """Verifica que usuarios con roles subordinados (85, 80, etc.) reciban 403."""
        self.assertEqual(self.client_commercial.get(self.saas_hq_url).status_code, 403)
        self.assertEqual(self.client_commercial.post(self.switch_plan_url, data={}).status_code, 403)
        self.assertEqual(self.client_commercial.post(self.update_status_url, data={}).status_code, 403)

    def test_client_tenant_owner_cannot_tamper_or_export_other_tenants(self):
        """
        Demuestra y verifica que un cliente no puede modificar parámetros ni exportar
        datos de otra organización enviando su identificador (org_id).
        """
        # Intento de alterar el plan de la empresa víctima
        tamper_res = self.client_tenant_owner.post(
            self.saas_hq_url,
            data={
                'org_id': str(self.org_victim_b.id),
                'subscription_plan': 'PYME_STARTER',
                'monthly_fee_usd': '1.00',
                'subscription_status': 'SUSPENDED',
                'max_users_quota': '1',
            }
        )
        self.assertEqual(tamper_res.status_code, 403)

        # Verificar que la organización víctima permanezca 100% inalterada en BD
        self.org_victim_b.refresh_from_db()
        self.assertEqual(self.org_victim_b.subscription_plan, Organization.SubscriptionPlan.ENTERPRISE)
        self.assertEqual(self.org_victim_b.subscription_status, Organization.SubscriptionStatus.ACTIVE)
        self.assertEqual(self.org_victim_b.monthly_fee_usd, Decimal('199.00'))
        self.assertEqual(self.org_victim_b.max_users_quota, 50)

        # Intento de descargar la bóveda de datos de la empresa víctima
        leak_res = self.client_tenant_owner.get(self.backup_victim_url)
        self.assertEqual(leak_res.status_code, 403)

    def test_platform_superuser_allowed_all_saas_hq_endpoints(self):
        """Verifica que un Superadministrador global tenga acceso pleno a todas las funciones."""
        # 1. Acceso al Dashboard de SaaS HQ
        res_dash = self.client_superadmin.get(self.saas_hq_url)
        self.assertEqual(res_dash.status_code, 200)

        # 2. Conmutación de Plan
        res_plan = self.client_superadmin.post(
            self.switch_plan_url,
            data={'subscription_plan': 'ENTERPRISE'},
            follow=True
        )
        self.assertEqual(res_plan.status_code, 200)
        self.org_client_a.refresh_from_db()
        self.assertEqual(self.org_client_a.subscription_plan, Organization.SubscriptionPlan.ENTERPRISE)

        # 3. Cambio de Estado a SUSPENDED
        res_status = self.client_superadmin.post(
            self.update_status_url,
            data={'subscription_status': 'SUSPENDED'},
            follow=True
        )
        self.assertEqual(res_status.status_code, 200)
        self.org_client_a.refresh_from_db()
        self.assertEqual(self.org_client_a.subscription_status, Organization.SubscriptionStatus.SUSPENDED)

        # 4. Generación de Factura
        res_inv = self.client_superadmin.post(
            self.generate_invoice_url,
            data={'billing_period': '2026-12', 'status': 'PAID'},
            follow=True
        )
        self.assertEqual(res_inv.status_code, 200)

        # 5. Descarga de Backup con Sello SHA-256
        res_backup = self.client_superadmin.get(self.backup_victim_url)
        self.assertEqual(res_backup.status_code, 200)
        self.assertEqual(res_backup['Content-Type'], 'application/json')
        data = res_backup.json()
        self.assertIn('integrity_seal_sha256', data)
        self.assertEqual(data['payload']['organization']['slug'], self.org_victim_b.slug)

    def test_alternative_http_methods_blocked_by_authorization_gate(self):
        """Verifica que métodos HTTP alternativos (PUT, DELETE, PATCH) sean bloqueados por la compuerta de seguridad."""
        self.assertEqual(self.client_tenant_owner.put(self.saas_hq_url).status_code, 403)
        self.assertEqual(self.client_tenant_owner.delete(self.saas_hq_url).status_code, 403)
        self.assertEqual(self.client_tenant_owner.patch(self.saas_hq_url).status_code, 403)
