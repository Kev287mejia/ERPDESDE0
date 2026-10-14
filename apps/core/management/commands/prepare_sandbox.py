from django.core.management import call_command
from django.core.management.base import BaseCommand
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Prepara el entorno sandbox para pruebas de diseno, marketing y evaluadores de producto."

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Elimina organizaciones de prueba huerfanas o sin miembros activos.',
        )

    def handle(self, *args, **options):
        self.stdout.write("[SANDBOX] 1/3 Aplicando migraciones de base de datos...")
        call_command('migrate', interactive=False)

        self.stdout.write("[SANDBOX] 2/3 Sembrando configuracion fiscal de Centroamerica...")
        call_command('seed_countries')

        if options.get('reset'):
            self.stdout.write("[SANDBOX] Limpiando organizaciones huerfanas de prueba...")
            orphans = Organization.objects.filter(memberships__isnull=True)
            deleted_count, _ = orphans.delete()
            self.stdout.write(f"[SANDBOX] Organizaciones huerfanas eliminadas: {deleted_count}")

        self.stdout.write("")
        self.stdout.write("=" * 70)
        self.stdout.write("ENTORNO SANDBOX PREPARADO CORRECTAMENTE - ETERNAL LABS")
        self.stdout.write("=" * 70)
        self.stdout.write("Instrucciones para evaluadores (UX / Marketing / Diseno):")
        self.stdout.write("")
        self.stdout.write("1. Iniciar el servidor local:")
        self.stdout.write("   python manage.py runserver")
        self.stdout.write("")
        self.stdout.write("2. Registrar una nueva cuenta corporativa en:")
        self.stdout.write("   http://127.0.0.1:8000/auth/register/")
        self.stdout.write("")
        self.stdout.write("3. Completar el Onboarding Wizard en 3 pasos:")
        self.stdout.write("   - Paso 1: Seleccionar bandera/pais fiscal.")
        self.stdout.write("   - Paso 2: Datos legales, identificador tributario y rubro.")
        self.stdout.write("   - Paso 3: Seleccionar modulos operativos contratados.")
        self.stdout.write("")
        self.stdout.write("4. Explorar el Simulador de Roles Jerarquicos en la barra superior:")
        self.stdout.write("   - Cambie entre LVL-100 (Owner) y roles operativos (LVL-85 a LVL-10)")
        self.stdout.write("     para verificar como el menu, dashboard y permisos reaccionan en vivo.")
        self.stdout.write("=" * 70)
