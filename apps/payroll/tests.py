from decimal import Decimal
import datetime
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import CountryConfig
from apps.finance.models import JournalEntry
from apps.payroll.models import EmployeeContract, PayrollPeriod, Payslip
from apps.payroll.services import (
    calculate_nicaragua_ir_monthly,
    compute_payslip_figures,
    generate_and_calculate_period_payslips,
    close_and_account_payroll_period,
)
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel

User = get_user_model()


class PayrollModuleTestSuite(TestCase):
    """
    Suite Integral de Pruebas Automatizadas para el Módulo de Planilla y Nómina Laboral (apps/payroll).
    Verifica:
    1. Precisión matemática de INSS 7% y Tabla Progresiva del IR Salarial (Ley 822 Art. 23 DGI Nicaragua).
    2. Cargas patronales (INSS 22.5%, INATEC 2%) y Provisiones Sociales MITRAB (1/12 cada una).
    3. Cierre de planilla, sello criptográfico SHA-256 e inmutabilidad de periodos y colillas.
    4. Póliza contable de partida doble perfectamente cuadrada (Debe == Haber == Costo Total Empresa).
    5. Segregación RBAC estricta (umbral 85 para gestión maestra, 403 para < 85).
    6. Confidencialidad salarial y autoservicio de colillas (Nivel 20+ para mis colillas, 403 en colillas ajenas).
    """

    def setUp(self):
        # 1. Configuración País (Nicaragua)
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
                'default_tax_name': 'IVA',
                'default_tax_rate': Decimal('15.00'),
                'is_active': True,
            }
        )

        # 2. Organización Principal
        self.org = Organization.objects.create(
            name="SERMANSA Ingeniería S.A.",
            legal_name="Servicios y Mantenimiento Electromecánico S.A.",
            slug="sermansa-payroll-ni",
            tax_id="J0310000458912",
            country=self.country_ni,
            currency=Organization.Currency.NIO,
            enabled_modules=['crm', 'operations', 'sst', 'inventory', 'finance', 'billing', 'purchasing', 'payroll'],
            business_profile=Organization.BusinessProfile.ENGINEERING_SERVICES,
            is_active=True,
        )

        # 3. Usuarios de Distintos Niveles Jerárquicos
        # Nivel 100: Director / Owner Admin
        self.owner = User.objects.create_user(
            email='avega@sermansa.ni',
            full_name='Ing. Alejandro Vega (Owner)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.org,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 85: Gerente Comercial
        self.commercial_mgr = User.objects.create_user(
            email='vjarquin@sermansa.ni',
            full_name='Lic. Valentina Jarquín (Comercial)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.commercial_mgr,
            organization=self.org,
            role_level=RoleLevel.COMMERCIAL_MGR,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 80: Coordinador de Operaciones
        self.ops_coord = User.objects.create_user(
            email='msilva@sermansa.ni',
            full_name='Ing. Marcos Silva (Operaciones)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.ops_coord,
            organization=self.org,
            role_level=RoleLevel.OPERATIONS_COORD,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 50: Ingeniero Residente
        self.engineer = User.objects.create_user(
            email='rblandon@sermansa.ni',
            full_name='Ing. Ricardo Blandón (Ingeniero)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.engineer,
            organization=self.org,
            role_level=RoleLevel.ENGINEER,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 20: Técnico Electromecánico
        self.technician = User.objects.create_user(
            email='cruiz@sermansa.ni',
            full_name='Téc. Carlos Ruiz (Técnico)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.technician,
            organization=self.org,
            role_level=RoleLevel.TECHNICIAN,
            is_active=True,
            is_default_org=True,
        )

        # 4. Fichas de Contratos Laborales
        self.contract_owner = EmployeeContract.objects.create(
            organization=self.org,
            code='EMP-0001',
            user=self.owner,
            full_name='Ing. Alejandro Vega',
            national_id='001-150882-0003K',
            inss_number='2458901-4',
            job_title='Director General',
            department=EmployeeContract.Department.MANAGEMENT,
            monthly_base_salary=Decimal('65000.00'),
            is_active=True,
        )

        self.contract_mgr = EmployeeContract.objects.create(
            organization=self.org,
            code='EMP-0002',
            user=self.commercial_mgr,
            full_name='Lic. Valentina Jarquín',
            national_id='001-140288-0004Y',
            inss_number='4589123-1',
            job_title='Gerente Comercial',
            department=EmployeeContract.Department.COMMERCIAL,
            monthly_base_salary=Decimal('40000.00'),
            is_active=True,
        )

        self.contract_eng = EmployeeContract.objects.create(
            organization=self.org,
            code='EMP-0003',
            user=self.engineer,
            full_name='Ing. Ricardo Blandón',
            national_id='001-051189-0006L',
            inss_number='4712039-2',
            job_title='Ingeniero Residente',
            department=EmployeeContract.Department.OPERATIONS,
            monthly_base_salary=Decimal('25000.00'),
            is_active=True,
        )

        self.contract_tech = EmployeeContract.objects.create(
            organization=self.org,
            code='EMP-0004',
            user=self.technician,
            full_name='Téc. Carlos Ruiz',
            national_id='001-300895-0008F',
            inss_number='6294810-7',
            job_title='Técnico Electromecánico',
            department=EmployeeContract.Department.OPERATIONS,
            monthly_base_salary=Decimal('9500.00'),
            is_active=True,
        )

        self.client = Client()

    def test_01_ley_822_exact_ir_bracket_calculations(self):
        """
        Prueba la exactitud matemática de la tabla progresiva anual del Art. 23 Ley 822 DGI Nicaragua.
        """
        # Caso A: Salario C$ 8,500.00 -> INSS 7% = 595.00 -> Base Neta = 7,905.00 -> Anual = 94,860.00 (<= 100,000)
        net_taxable_exempt = Decimal('7905.00')
        ir_exempt = calculate_nicaragua_ir_monthly(net_taxable_exempt)
        self.assertEqual(ir_exempt, Decimal('0.00'))

        # Caso B: Salario C$ 9,500.00 -> INSS 7% = 665.00 -> Base Neta = 8,835.00 -> Anual = 106,020.00 (Tramo 15%)
        # Exceso = 6,020.00 * 15% = 903.00 anual / 12 = 75.25 mensual
        net_taxable_tech = Decimal('8835.00')
        ir_tech = calculate_nicaragua_ir_monthly(net_taxable_tech)
        self.assertEqual(ir_tech, Decimal('75.25'))

        # Caso C: Salario C$ 25,000.00 -> INSS 7% = 1,750.00 -> Base Neta = 23,250.00 -> Anual = 279,000.00 (Tramo 20%)
        # Base = 15,000 + (79,000 * 20%) = 30,800.00 anual / 12 = 2,566.67 mensual
        net_taxable_eng = Decimal('23250.00')
        ir_eng = calculate_nicaragua_ir_monthly(net_taxable_eng)
        self.assertEqual(ir_eng, Decimal('2566.67'))

        # Caso D: Salario C$ 35,000.00 -> INSS 7% = 2,450.00 -> Base Neta = 32,550.00 -> Anual = 390,600.00 (Tramo 25%)
        # Base = 45,000 + (40,600 * 25%) = 55,150.00 anual / 12 = 4,595.83 mensual
        net_taxable_ops = Decimal('32550.00')
        ir_ops = calculate_nicaragua_ir_monthly(net_taxable_ops)
        self.assertEqual(ir_ops, Decimal('4595.83'))

        # Caso E: Salario C$ 65,000.00 -> INSS 7% = 4,550.00 -> Base Neta = 60,450.00 -> Anual = 725,400.00 (Tramo 30%)
        # Base = 82,500 + (225,400 * 30%) = 150,120.00 anual / 12 = 12,510.00 mensual
        net_taxable_owner = Decimal('60450.00')
        ir_owner = calculate_nicaragua_ir_monthly(net_taxable_owner)
        self.assertEqual(ir_owner, Decimal('12510.00'))

    def test_02_payslip_deductions_and_mitrab_provisions(self):
        """
        Prueba el cálculo de una colilla individual para un salario de C$ 25,000.00:
        INSS 7%, Base Neta, IR Ley 822, Neto a Pagar, Cargas Patronales (22.5% + 2%) y Provisiones (1/12 c/u).
        """
        period = PayrollPeriod.objects.create(
            organization=self.org,
            number='NOM-2026-TEST',
            period_name='Planilla de Prueba Octubre 2026',
            frequency=PayrollPeriod.Frequency.MONTHLY,
            start_date=datetime.date(2026, 10, 1),
            end_date=datetime.date(2026, 10, 31),
            payment_date=datetime.date(2026, 10, 31),
            employer_inss_rate=Decimal('22.50'),
            inatec_rate=Decimal('2.00'),
        )

        payslip = Payslip.objects.create(
            organization=self.org,
            period=period,
            contract=self.contract_eng,
            days_worked=Decimal('30.00'),
            base_salary_earned=Decimal('25000.00'),
        )

        compute_payslip_figures(payslip)
        payslip.save()

        # Deducciones Laborales
        self.assertEqual(payslip.gross_salary, Decimal('25000.00'))
        self.assertEqual(payslip.inss_employee_amount, Decimal('1750.00'))
        self.assertEqual(payslip.net_taxable_base, Decimal('23250.00'))
        self.assertEqual(payslip.ir_salary_tax_amount, Decimal('2566.67'))
        self.assertEqual(payslip.total_deductions, Decimal('4316.67'))
        self.assertEqual(payslip.net_payable, Decimal('20683.33'))

        # Cargas Patronales
        self.assertEqual(payslip.inss_employer_amount, Decimal('5625.00'))
        self.assertEqual(payslip.inatec_amount, Decimal('500.00'))

        # Provisiones Sociales MITRAB Ley 185 (25000 / 12 = 2083.33 cada una)
        self.assertEqual(payslip.vacation_provision, Decimal('2083.33'))
        self.assertEqual(payslip.thirteenth_month_provision, Decimal('2083.33'))
        self.assertEqual(payslip.severance_provision, Decimal('2083.33'))

    def test_03_period_generation_and_consolidation(self):
        """
        Prueba la generación masiva de colillas y la consolidación de totales para la organización.
        """
        period = PayrollPeriod.objects.create(
            organization=self.org,
            number='NOM-2026-GEN',
            period_name='Planilla de Prueba Octubre 2026',
            frequency=PayrollPeriod.Frequency.MONTHLY,
            start_date=datetime.date(2026, 10, 1),
            end_date=datetime.date(2026, 10, 31),
            payment_date=datetime.date(2026, 10, 31),
            employer_inss_rate=Decimal('22.50'),
            inatec_rate=Decimal('2.00'),
        )

        generate_and_calculate_period_payslips(period)
        period.refresh_from_db()

        self.assertEqual(period.payslips.count(), 4)
        # Suma de salarios: 65000 + 40000 + 25000 + 9500 = 139500.00
        self.assertEqual(period.total_gross_salary, Decimal('139500.00'))
        # INSS 7% sobre 139500 = 9765.00
        self.assertEqual(period.total_inss_employee, Decimal('9765.00'))
        # Costo Total = Masa Salarial Bruta + Cargas Patronales + Provisiones MITRAB
        expected_cost = (
            period.total_gross_salary
            + period.total_inss_employer
            + period.total_inatec
            + period.total_provisions
        )
        self.assertEqual(period.total_company_cost, expected_cost)

    def test_04_period_close_sha256_seal_and_double_entry_balance(self):
        """
        Prueba el cierre oficial de la nómina:
        - Sello criptográfico SHA-256 generado
        - Póliza contable creada con partida doble cuadrada (Debe == Haber == Costo Total)
        - Inmutabilidad estricta tras el cierre
        """
        period = PayrollPeriod.objects.create(
            organization=self.org,
            number='NOM-2026-CLOSE',
            period_name='Planilla para Cierre Oficial',
            frequency=PayrollPeriod.Frequency.MONTHLY,
            start_date=datetime.date(2026, 10, 1),
            end_date=datetime.date(2026, 10, 31),
            payment_date=datetime.date(2026, 10, 31),
            employer_inss_rate=Decimal('22.50'),
            inatec_rate=Decimal('2.00'),
        )

        closed_period = close_and_account_payroll_period(period, self.owner)
        self.assertEqual(closed_period.status, PayrollPeriod.Status.CLOSED)
        self.assertTrue(len(closed_period.audit_hash) == 64)
        self.assertIsNotNone(closed_period.journal_entry)

        je = closed_period.journal_entry
        self.assertTrue(je.is_balanced)
        self.assertEqual(je.total_debit, closed_period.total_company_cost)
        self.assertEqual(je.total_credit, closed_period.total_company_cost)

    def test_05_immutability_validation_errors(self):
        """
        Garantiza que una vez cerrada la planilla, no se pueda modificar ni eliminar
        ni el periodo ni ninguna de sus colillas de pago.
        """
        period = PayrollPeriod.objects.create(
            organization=self.org,
            number='NOM-2026-LOCK',
            period_name='Planilla Bloqueada',
            frequency=PayrollPeriod.Frequency.MONTHLY,
            start_date=datetime.date(2026, 10, 1),
            end_date=datetime.date(2026, 10, 31),
            payment_date=datetime.date(2026, 10, 31),
        )
        close_and_account_payroll_period(period, self.owner)

        # Intento de eliminar el periodo cerrado debe disparar ValidationError
        with self.assertRaises(ValidationError):
            period.delete()

        # Intento de modificar el periodo cerrado debe disparar ValidationError
        period.period_name = 'Nombre Alterado'
        with self.assertRaises(ValidationError):
            period.save()

        # Intento de eliminar o modificar una colilla de periodo cerrado debe fallar
        payslip = period.payslips.first()
        with self.assertRaises(ValidationError):
            payslip.delete()

        payslip.overtime_and_bonuses = Decimal('5000.00')
        with self.assertRaises(ValidationError):
            payslip.save()

    def test_06_rbac_master_payroll_console_security(self):
        """
        Prueba la segregación RBAC en la consola maestra de planilla (/payroll/):
        - Rol >= 85 (COMMERCIAL_MGR, OWNER_ADMIN) -> HTTP 200
        - Rol < 85 (OPERATIONS_COORD 80, ENGINEER 50, TECHNICIAN 20) -> HTTP 403
        """
        url_dashboard = reverse('payroll:dashboard')

        # 1. Gerente Comercial (85) -> Permitido
        self.client.force_login(self.commercial_mgr)
        session = self.client.session
        session['active_org_id'] = str(self.org.id)
        session.save()
        response = self.client.get(url_dashboard)
        self.assertEqual(response.status_code, 200)

        # 2. Owner Admin (100) -> Permitido
        self.client.force_login(self.owner)
        session = self.client.session
        session['active_org_id'] = str(self.org.id)
        session.save()
        response = self.client.get(url_dashboard)
        self.assertEqual(response.status_code, 200)

        # 3. Coordinador de Operaciones (80) -> Bloqueado HTTP 403
        self.client.force_login(self.ops_coord)
        session = self.client.session
        session['active_org_id'] = str(self.org.id)
        session.save()
        response = self.client.get(url_dashboard)
        self.assertEqual(response.status_code, 403)

        # 4. Ingeniero Residente (50) -> Bloqueado HTTP 403
        self.client.force_login(self.engineer)
        session = self.client.session
        session['active_org_id'] = str(self.org.id)
        session.save()
        response = self.client.get(url_dashboard)
        self.assertEqual(response.status_code, 403)

        # 5. Técnico de Campo (20) -> Bloqueado HTTP 403
        self.client.force_login(self.technician)
        session = self.client.session
        session['active_org_id'] = str(self.org.id)
        session.save()
        response = self.client.get(url_dashboard)
        self.assertEqual(response.status_code, 403)

    def test_07_rbac_self_service_and_payslip_confidentiality(self):
        """
        Prueba el portal de autoservicio de colillas (/payroll/my-payslips/)
        y la confidencialidad estricta al imprimir colillas individuales:
        - Colaborador (20+) puede ver y descargar ÚNICAMENTE su colilla.
        - Intentar ver o imprimir la colilla de otro empleado devuelve HTTP 403.
        - El Gerente (85+) puede ver e imprimir colillas de todos.
        """
        period = PayrollPeriod.objects.create(
            organization=self.org,
            number='NOM-2026-AUTOSERVICE',
            period_name='Planilla de Prueba Autoservicio',
            frequency=PayrollPeriod.Frequency.MONTHLY,
            start_date=datetime.date(2026, 10, 1),
            end_date=datetime.date(2026, 10, 31),
            payment_date=datetime.date(2026, 10, 31),
        )
        generate_and_calculate_period_payslips(period)

        payslip_tech = period.payslips.get(contract=self.contract_tech)
        payslip_mgr = period.payslips.get(contract=self.contract_mgr)

        url_my_payslips = reverse('payroll:my_payslips')
        url_print_tech = reverse('payroll:payslip_print', kwargs={'pk': payslip_tech.pk})
        url_print_mgr = reverse('payroll:payslip_print', kwargs={'pk': payslip_mgr.pk})

        # 1. Técnico accede a su portal de autoservicio -> HTTP 200
        self.client.force_login(self.technician)
        session = self.client.session
        session['active_org_id'] = str(self.org.id)
        session.save()

        response = self.client.get(url_my_payslips)
        self.assertEqual(response.status_code, 200)
        # Verifica que solo ve su propia colilla
        self.assertContains(response, payslip_tech.number)
        self.assertNotContains(response, payslip_mgr.number)

        # 2. Técnico imprime su propia colilla -> HTTP 200
        response = self.client.get(url_print_tech)
        self.assertEqual(response.status_code, 200)

        # 3. Técnico intenta imprimir colilla del Gerente -> Bloqueo HTTP 403
        response = self.client.get(url_print_mgr)
        self.assertEqual(response.status_code, 403)

        # 4. Coordinador de Operaciones (80) intenta imprimir colilla del Gerente -> Bloqueo HTTP 403
        self.client.force_login(self.ops_coord)
        session = self.client.session
        session['active_org_id'] = str(self.org.id)
        session.save()
        response = self.client.get(url_print_mgr)
        self.assertEqual(response.status_code, 403)

        # 5. Gerente Comercial (85) imprime la colilla del Técnico -> HTTP 200
        self.client.force_login(self.commercial_mgr)
        session = self.client.session
        session['active_org_id'] = str(self.org.id)
        session.save()
        response = self.client.get(url_print_tech)
        self.assertEqual(response.status_code, 200)

        # 6. Gerente Comercial (85) imprime su propia colilla -> HTTP 200
        response = self.client.get(url_print_mgr)
        self.assertEqual(response.status_code, 200)
