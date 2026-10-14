from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from apps.core.models import CountryConfig
from apps.tenancy.forms import OrganizationOnboardingForm
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel
from apps.tenancy.views_onboarding import DashboardWorkspaceView

User = get_user_model()


class TenancyOnboardingAndStrictModularTestCase(TestCase):
    """
    Suite de pruebas para validar:
    1. Registro enriquecido con Moneda Funcional, Régimen Fiscal DGI, Giro/Rubro y Plan Contable.
    2. Modulación Estricta: Lo que el usuario selecciona es ESTRICTAMENTE lo que se habilita.
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
        self.user = User.objects.create_user(
            email='cfo@corporacion.ni',
            password='Password123!',
            full_name='Carlos Contreras',
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_onboarding_form_contains_fiscal_and_industry_fields(self):
        """Verifica que el formulario de onboarding valide los nuevos rubros técnicos."""
        form = OrganizationOnboardingForm(data={
            'country_code': 'NI',
            'name': 'Energía y Construcción S.A.',
            'legal_name': 'Energía y Construcción de Nicaragua Sociedad Anónima',
            'tax_id': 'J0310000099999',
            'currency': Organization.Currency.USD,
            'tax_regime': Organization.TaxRegime.SPECIAL,
            'industry': Organization.Industry.ENERGY_TELCO,
            'accounting_template': Organization.AccountingTemplate.NIIF_PYMES,
            'enabled_modules': ['crm', 'finance'],
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['currency'], Organization.Currency.USD)
        self.assertEqual(form.cleaned_data['tax_regime'], Organization.TaxRegime.SPECIAL)
        self.assertEqual(form.cleaned_data['industry'], Organization.Industry.ENERGY_TELCO)
        self.assertEqual(form.cleaned_data['accounting_template'], Organization.AccountingTemplate.NIIF_PYMES)

    def test_onboarding_wizard_post_persists_organization_and_sets_active_session(self):
        """Verifica el flujo completo de creación de organización con los rubros seleccionados."""
        response = self.client.post(reverse('tenancy:onboarding'), {
            'country_code': 'NI',
            'name': 'Telecom Redes',
            'legal_name': 'Telecomunicaciones y Redes de Occidente S.A.',
            'tax_id': 'J0310000088888',
            'currency': Organization.Currency.USD,
            'tax_regime': Organization.TaxRegime.GENERAL,
            'industry': Organization.Industry.ENERGY_TELCO,
            'accounting_template': Organization.AccountingTemplate.NIIF_PYMES,
            'enabled_modules': ['crm', 'finance'],
        }, follow=True)

        self.assertEqual(response.status_code, 200)

        org = Organization.objects.get(tax_id='J0310000088888')
        self.assertEqual(org.name, 'Telecom Redes')
        self.assertEqual(org.currency, Organization.Currency.USD)
        self.assertEqual(org.currency_symbol, '$')
        self.assertEqual(org.tax_regime, Organization.TaxRegime.GENERAL)
        self.assertEqual(org.industry, Organization.Industry.ENERGY_TELCO)
        self.assertEqual(org.accounting_template, Organization.AccountingTemplate.NIIF_PYMES)
        self.assertEqual(org.enabled_modules, ['crm', 'finance'])

        # Membresía Owner creada
        membership = OrganizationMembership.objects.get(user=self.user, organization=org)
        self.assertEqual(membership.role_level, RoleLevel.OWNER_ADMIN)
        self.assertTrue(membership.is_default_org)

    def test_strict_module_access_rules(self):
        """
        Regla Estricta: Lo que el usuario seleccione es lo que se habilitará.
        Si la empresa sólo contrató ['crm', 'finance'], los módulos 'operations' y 'sst'
        quedan estrictamente denegados incluso para el OWNER_ADMIN.
        """
        org = Organization.objects.create(
            country=self.country_ni,
            name='Comercializadora Alfa',
            legal_name='Comercializadora Alfa S.A.',
            tax_id='J0310000077777',
            currency=Organization.Currency.NIO,
            tax_regime=Organization.TaxRegime.GENERAL,
            industry=Organization.Industry.COMMERCE,
            accounting_template=Organization.AccountingTemplate.SIMPLIFIED,
            slug='comercializadora-alfa',
            enabled_modules=['crm', 'finance'],
            onboarding_completed=True,
            is_active=True,
        )

        owner_membership = OrganizationMembership.objects.create(
            user=self.user,
            organization=org,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
        )

        # Módulos habilitados
        self.assertTrue(org.is_module_enabled('crm'))
        self.assertTrue(org.is_module_enabled('finance'))
        self.assertTrue(owner_membership.has_module_access('crm'))
        self.assertTrue(owner_membership.has_module_access('finance'))

        # Módulos NO contratados quedan estrictamente denegados
        self.assertFalse(org.is_module_enabled('operations'))
        self.assertFalse(org.is_module_enabled('sst'))
        self.assertFalse(org.is_module_enabled('inventory'))
        self.assertFalse(owner_membership.has_module_access('operations'))
        self.assertFalse(owner_membership.has_module_access('sst'))
        self.assertFalse(owner_membership.has_module_access('inventory'))

    def test_dashboard_kpis_reflect_strictly_enabled_modules(self):
        """El dashboard renderiza tarjetas de KPI estrictamente para los módulos contratados."""
        org = Organization.objects.create(
            country=self.country_ni,
            name='Servicios Puro Finanzas',
            legal_name='Servicios Financieros S.A.',
            tax_id='J0310000066666',
            currency=Organization.Currency.USD,
            tax_regime=Organization.TaxRegime.SPECIAL,
            industry=Organization.Industry.SERVICES,
            accounting_template=Organization.AccountingTemplate.NIIF_PYMES,
            slug='servicios-puro-finanzas',
            enabled_modules=['finance'],
            onboarding_completed=True,
            is_active=True,
        )

        OrganizationMembership.objects.create(
            user=self.user,
            organization=org,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
            is_default_org=True,
        )

        session = self.client.session
        session['active_org_id'] = str(org.id)
        session.save()

        response = self.client.get(reverse('tenancy:dashboard'))
        self.assertEqual(response.status_code, 200)

        kpi_cards = response.context['kpi_cards']
        card_ids = [c['id'] for c in kpi_cards]

        # MOD-FIN y governance deben estar presentes
        self.assertIn('finance', card_ids)
        self.assertIn('governance', card_ids)

        # MOD-OPS, MOD-SST, MOD-CRM, MOD-TECH, MOD-MKT no contratados NO deben aparecer en kpi_cards
        self.assertNotIn('operations', card_ids)
        self.assertNotIn('sst', card_ids)
        self.assertNotIn('crm', card_ids)
        self.assertNotIn('tech', card_ids)
        self.assertNotIn('marketing', card_ids)

    def test_tech_and_marketing_modules_access_and_isolation(self):
        """Verifica la habilitación de MOD-TECH y MOD-MKT y el control de acceso estricto."""
        tech_org = Organization.objects.create(
            country=self.country_ni,
            name='Tech Solutions Lab',
            legal_name='Tech Solutions Lab S.A.',
            tax_id='J0310000088888',
            currency=Organization.Currency.USD,
            tax_regime=Organization.TaxRegime.GENERAL,
            industry=Organization.Industry.TECHNOLOGY,
            accounting_template=Organization.AccountingTemplate.NIIF_PYMES,
            slug='tech-solutions-lab',
            enabled_modules=['tech', 'marketing'],
            onboarding_completed=True,
            is_active=True,
        )

        owner_mem = OrganizationMembership.objects.create(
            user=self.user,
            organization=tech_org,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
            is_default_org=True,
        )

        # Módulos contratados
        self.assertTrue(tech_org.is_module_enabled('tech'))
        self.assertTrue(tech_org.is_module_enabled('marketing'))
        self.assertTrue(owner_mem.has_module_access('tech'))
        self.assertTrue(owner_mem.has_module_access('marketing'))

        session = self.client.session
        session['active_org_id'] = str(tech_org.id)
        session.save()

        # Acceso permitido a sus consolas respectivas
        resp_tech = self.client.get(reverse('tenancy:tech_dashboard'))
        self.assertEqual(resp_tech.status_code, 200)
        self.assertContains(resp_tech, 'Tecnología, Soporte IT')

        resp_mkt = self.client.get(reverse('tenancy:marketing_dashboard'))
        self.assertEqual(resp_mkt.status_code, 200)
        self.assertContains(resp_mkt, 'Marketing Digital, Campañas')

        # Dashboard refleja KPI cards de tech y marketing
        resp_dash = self.client.get(reverse('tenancy:dashboard'))
        self.assertEqual(resp_dash.status_code, 200)
        kpi_ids = [c['id'] for c in resp_dash.context['kpi_cards']]
        self.assertIn('tech', kpi_ids)
        self.assertIn('marketing', kpi_ids)
        self.assertNotIn('finance', kpi_ids)

    def test_finance_action_buttons_rendered_with_event_dispatch(self):
        """Los botones de acción en el módulo de Finanzas renderizan despachadores de eventos de ventana."""
        fin_org = Organization.objects.create(
            country=self.country_ni,
            name='Finanzas Corporativas',
            legal_name='Finanzas Corporativas S.A.',
            tax_id='J0310000099999',
            currency=Organization.Currency.NIO,
            tax_regime=Organization.TaxRegime.GENERAL,
            industry=Organization.Industry.SERVICES,
            accounting_template=Organization.AccountingTemplate.NIIF_PYMES,
            slug='finanzas-corporativas',
            enabled_modules=['finance'],
            onboarding_completed=True,
            is_active=True,
        )

        OrganizationMembership.objects.create(
            user=self.user,
            organization=fin_org,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
            is_default_org=True,
        )

        session = self.client.session
        session['active_org_id'] = str(fin_org.id)
        session.save()

        resp = self.client.get(reverse('finance:dashboard'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()

        self.assertIn('btn-register-expense', content)
        self.assertIn('btn-request-replenish', content)
        self.assertIn('btn-open-fund', content)
        self.assertIn('btn-create-bank-account', content)
        self.assertIn("window.dispatchEvent(new CustomEvent('open-expense-modal'))", content)
        self.assertIn("window.dispatchEvent(new CustomEvent('open-replenish-modal'))", content)
        self.assertIn("window.dispatchEvent(new CustomEvent('open-fund-modal'))", content)
        self.assertIn("window.dispatchEvent(new CustomEvent('open-bank-modal'))", content)

