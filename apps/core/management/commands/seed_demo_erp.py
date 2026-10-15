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

        self.stdout.write(f"[SEED-DEMO] 2/3 Inicializando organización '{org_name}'...")
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
                'accounting_template': Organization.AccountingTemplate.NIIF_PYMES,
                'enabled_modules': ['crm', 'operations', 'sst', 'inventory', 'finance', 'billing', 'purchasing'],
                'business_profile': Organization.BusinessProfile.ENGINEERING_SERVICES,
                'onboarding_completed': True,
                'is_active': True,
            }
        )
        org.enabled_modules = ['crm', 'operations', 'sst', 'inventory', 'finance', 'billing', 'purchasing']
        org.business_profile = Organization.BusinessProfile.ENGINEERING_SERVICES
        org.onboarding_completed = True
        org.save()

        OrganizationMembership.objects.update_or_create(
            user=admin_user,
            organization=org,
            defaults={
                'role_level': RoleLevel.OWNER_ADMIN,
                'job_title': 'Director General & Socio Fundador',
                'is_active': True,
            }
        )

        self.stdout.write("[SEED-DEMO] 3/3 Sembrando datos operativos, fiscal DGI y cartera...")
        result = SandboxScenarioSeeder.populate_for_organization(org, owner_user=admin_user)

        # Poblar catálogos multi-vertical para pruebas y demostración completa
        from apps.core.services.sandbox_seeder import ensure_vertical_demo_catalog
        ensure_vertical_demo_catalog(org, 'HARDWARE')
        ensure_vertical_demo_catalog(org, 'PHARMACY')

        self.stdout.write(
            self.style.SUCCESS(
                f"[SEED-DEMO] Escenario sembrado exitosamente en {org.name} con {result.get('invoices_count', 1)} factura(s), "
                f"{result.get('receipts_count', 1)} recibo(s) oficial(es) de caja ROC y catálogos multi-vertical (Ferretería y Farmacia FEFO)."
            )
        )

