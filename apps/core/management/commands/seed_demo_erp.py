import datetime
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import CountryConfig
from apps.core.services.sandbox_seeder import SandboxScenarioSeeder
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel

User = get_user_model()


class Command(BaseCommand):
    help = "Siembra el escenario de demostración oficial para SERMANSA Ingeniería con facturación DGI y retenciones."

    def add_arguments(self, parser):
        parser.add_argument(
            '--org-name',
            type=str,
            default='SERMANSA Ingeniería S.A.',
            help='Nombre de la organización a poblar.',
        )

    def handle(self, *args, **options):
        self.stdout.write("[SEED-DEMO] 1/3 Verificando migraciones y configuraciones fiscales...")
        call_command('migrate', interactive=False)
        call_command('seed_countries')

        country_ni = CountryConfig.objects.filter(code='NI').first()
        org_name = options['org_name']

        self.stdout.write(f"[SEED-DEMO] 2/4 Inicializando usuarios evaluadores...")
        admin_user, _ = User.objects.get_or_create(
            email='admin@sermansa.ni',
            defaults={
                'full_name': 'Ing. Carlos Mendoza Rivas',
                'personal_id_number': '001-150882-0003K',
                'phone': '+505 8899-1122',
            }
        )
        if not admin_user.check_password('Eternal2026*'):
            admin_user.set_password('Eternal2026*')
            admin_user.save()

        evaluator_user, _ = User.objects.get_or_create(
            email='evaluador@eternallabs.ni',
            defaults={
                'full_name': 'Evaluador Principal Eternal Labs',
                'personal_id_number': '001-201090-0005M',
                'phone': '+505 8765-4321',
            }
        )
        if not evaluator_user.check_password('Eternal2026*'):
            evaluator_user.set_password('Eternal2026*')
            evaluator_user.save()

        self.stdout.write(f"[SEED-DEMO] 3/4 Inicializando organización principal '{org_name}' (Ingeniería)...")
        from apps.tenancy.constants import BusinessVertical
        org, _ = Organization.objects.get_or_create(
            slug='sermansa-ingenieria',
            defaults={
                'name': org_name,
                'legal_name': 'Servicios y Mantenimiento Electromecánico Sociedad Anónima',
                'tax_id': 'J0310000458912',
                'country': country_ni,
                'currency': Organization.Currency.NIO,
                'tax_regime': Organization.TaxRegime.GENERAL,
                'industry': Organization.Industry.ENERGY_TELCO,
                'business_vertical': BusinessVertical.ENGINEERING_SERVICES,
                'business_profile': Organization.BusinessProfile.ENGINEERING_SERVICES,
                'accounting_template': Organization.AccountingTemplate.NIIF_PYMES,
                'enabled_modules': ['crm', 'operations', 'sst', 'inventory', 'finance', 'billing', 'purchasing', 'repository', 'tickets', 'ai_agent', 'payroll'],
                'subscription_plan': Organization.SubscriptionPlan.ENTERPRISE,
                'subscription_status': Organization.SubscriptionStatus.ACTIVE,
                'monthly_fee_usd': Decimal('199.00'),
                'max_users_quota': 50,
                'max_users': 50,
                'onboarding_completed': True,
                'is_active': True,
            }
        )
        org.business_vertical = BusinessVertical.ENGINEERING_SERVICES
        org.business_profile = Organization.BusinessProfile.ENGINEERING_SERVICES
        org.enabled_modules = ['crm', 'operations', 'sst', 'inventory', 'finance', 'billing', 'purchasing', 'repository', 'tickets', 'ai_agent', 'payroll']
        org.subscription_plan = Organization.SubscriptionPlan.ENTERPRISE
        org.subscription_status = Organization.SubscriptionStatus.ACTIVE
        org.monthly_fee_usd = Decimal('199.00')
        org.max_users_quota = 50
        org.max_users = 50
        org.next_billing_date = datetime.date(2026, 11, 1)
        org.onboarding_completed = True
        org.save()

        OrganizationMembership.objects.update_or_create(
            user=admin_user,
            organization=org,
            defaults={
                'role_level': RoleLevel.OWNER_ADMIN,
                'job_title': 'Director General & Socio Fundador',
                'is_active': True,
                'is_default_org': True,
            }
        )
        OrganizationMembership.objects.update_or_create(
            user=evaluator_user,
            organization=org,
            defaults={
                'role_level': RoleLevel.OWNER_ADMIN,
                'job_title': 'Evaluador de Producto / Auditor',
                'is_active': True,
                'is_default_org': True,
            }
        )

        result = SandboxScenarioSeeder.populate_for_organization(org, owner_user=admin_user)

        self.stdout.write("[SEED-DEMO] 4/4 Sembrando organizaciones satélites independientes por giro...")
        from apps.core.services.sandbox_seeder import seed_multi_vertical_demo_organizations
        satellite_orgs = seed_multi_vertical_demo_organizations(country_ni, [admin_user, evaluator_user])

        self.stdout.write(
            self.style.SUCCESS(
                f"[SEED-DEMO] Escenario sembrado exitosamente en 4 organizaciones independientes:\n"
                f"  1. {org.name} (INGENIERÍA · {result.get('invoices_count', 1)} facturas, nómina y OTs)\n"
                f"  2. Ferretería El Maestro S.A. (HARDWARE · POS y 3 listas de precios)\n"
                f"  3. Farmacia Santa Lucía S.A. (PHARMACY · POS, lotes FEFO y Registro MINSA)\n"
                f"  4. Comercial Masaya S.A. (SME_RETAIL · Tienda PYME, facturación y caja)"
            )
        )

