from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import CountryConfig
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel
from apps.crm.models import Account
from apps.operations.models import Crew, WorkOrder, WorkOrderTimelineLog
from apps.finance.models import (
    BankAccount,
    PettyCashFund,
    PettyCashExpense,
    PettyCashReplenishment,
    FinancialTransaction,
)
from apps.finance.services import (
    allocate_petty_cash_fund,
    record_petty_cash_expense,
    submit_petty_cash_replenishment,
    disburse_petty_cash_replenishment,
)

User = get_user_model()


class FinanceModuleEndToEndTestCase(TestCase):
    """
    Suite de Pruebas End-to-End para el Módulo de Finanzas, Tesorería y Fondos de Caja Chica (apps/finance).
    Verifica:
    1. Ciclo Financiero Completo:
       Apertura Bancaria -> Dotación de Fondo Fijo -> Registro de Comprobantes de Campo vinculados a OT
       -> Arqueo y Solicitud de Reposición -> Aprobación y Desembolso Bancario -> Restauración de Saldo.
    2. Prevención Estricta de Sobregiros y Saldos Negativos en Cajas Chicas y Bancos.
    3. Inmutabilidad Estricta del Libro Mayor (FinancialTransaction) y Comprobantes Liquidados.
    4. Matriz de Autoridad Jerárquica RBAC y Confidencialidad Bancaria:
       - Nivel 20 (Técnico de Campo): Acceso Prohibido (HTTP 403).
       - Nivel 50 (Ingeniero Residente / Custodio): Acceso a su caja asignada, ocultamiento total de cuentas bancarias.
       - Nivel 80 (Coordinador Operativo): Visibilidad global, aprobación y desembolso bancario.
       - Nivel 100 (Owner / Administrador): Acceso irrestricto y apertura de cuentas bancarias.
    5. Aislamiento Multi-Tenant Estricto por Organización.
    """

    def setUp(self):
        # 1. Configuración de Jurisdicción Fiscal Nicaragua
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

        # 2. Organizaciones Multi-Tenant
        self.org = Organization.objects.create(
            name="Vector Soluciones Industriales, S.A.",
            legal_name="Vector Soluciones Industriales de Nicaragua, S.A.",
            slug="vector-ni-finance",
            tax_id="J0310000199991",
            country=self.country_ni,
            enabled_modules=['crm', 'operations', 'sst', 'inventory', 'finance'],
            is_active=True,
        )

        self.org_intruder = Organization.objects.create(
            name="Constructora del Norte, S.A.",
            legal_name="Constructora del Norte S.A.",
            slug="norte-ni-finance",
            tax_id="J0310000188882",
            country=self.country_ni,
            enabled_modules=['finance'],
            is_active=True,
        )

        # 3. Usuarios de la Matriz RBAC
        # Nivel 100: Owner / Administrador General
        self.user_owner = User.objects.create_user(
            email='owner@vector.com.ni',
            full_name='Ing. Roberto Meza (Owner)',
            password='Password123!',
        )
        OrganizationMembership.objects.create(
            user=self.user_owner,
            organization=self.org,
            role_level=RoleLevel.OWNER_ADMIN,
            job_title='Director General',
            is_active=True,
            is_default_org=True,
        )

        # Nivel 80: Coordinador Operativo
        self.user_coord = User.objects.create_user(
            email='coordinador@vector.com.ni',
            full_name='Ing. Carlos Pineda (Coordinador)',
            password='Password123!',
        )
        OrganizationMembership.objects.create(
            user=self.user_coord,
            organization=self.org,
            role_level=RoleLevel.OPERATIONS_COORD,
            job_title='Coordinador de Proyectos',
            is_active=True,
            is_default_org=True,
        )

        # Nivel 50: Ingeniero Residente (Custodio de Caja 1)
        self.user_engineer = User.objects.create_user(
            email='ingeniero@vector.com.ni',
            full_name='Ing. Andrea Salgado (Residente Alfa)',
            password='Password123!',
        )
        OrganizationMembership.objects.create(
            user=self.user_engineer,
            organization=self.org,
            role_level=RoleLevel.ENGINEER,
            job_title='Ingeniero Residente',
            is_active=True,
            is_default_org=True,
        )

        # Nivel 50: Segundo Ingeniero Residente (Custodio de Caja 2)
        self.user_engineer_beta = User.objects.create_user(
            email='ing.beta@vector.com.ni',
            full_name='Ing. Denis Morales (Residente Beta)',
            password='Password123!',
        )
        OrganizationMembership.objects.create(
            user=self.user_engineer_beta,
            organization=self.org,
            role_level=RoleLevel.ENGINEER,
            job_title='Ingeniero Residente Beta',
            is_active=True,
            is_default_org=True,
        )

        # Nivel 20: Técnico de Campo
        self.user_tech = User.objects.create_user(
            email='tecnico@vector.com.ni',
            full_name='Armando Solís (Técnico)',
            password='Password123!',
        )
        OrganizationMembership.objects.create(
            user=self.user_tech,
            organization=self.org,
            role_level=RoleLevel.TECHNICIAN,
            job_title='Técnico Electricista',
            is_active=True,
            is_default_org=True,
        )

        # Usuario Organización Intrusora
        self.user_intruder = User.objects.create_user(
            email='owner@norte.com.ni',
            full_name='Mario Espinoza (Intruso)',
            password='Password123!',
        )
        OrganizationMembership.objects.create(
            user=self.user_intruder,
            organization=self.org_intruder,
            role_level=RoleLevel.OWNER_ADMIN,
            job_title='Gerente Intruso',
            is_active=True,
            is_default_org=True,
        )

        # 4. Datos Operativos Base (Cliente, OT y Cuadrilla)
        self.client_account = Account.objects.create(
            organization=self.org,
            commercial_name="Consorcio Minero de Nicaragua, S.A.",
            legal_name="Consorcio Minero S.A.",
            tax_id="J0310000223344",
        )

        self.crew_alfa = Crew.objects.create(
            organization=self.org,
            code="CRW-ALFA",
            name="Cuadrilla Alfa - Electromecánica",
            vehicle_plate="M-301294",
        )

        self.work_order = WorkOrder.objects.create(
            organization=self.org,
            number="OT-2026-0001",
            account=self.client_account,
            title="Mantenimiento Subestación Mina San Albino",
            phase=WorkOrder.Phase.IN_PROGRESS,
            assigned_crew=self.crew_alfa,
        )

        # 5. Cuenta Bancaria Inicial
        self.bank_bac = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BAC,
            currency='NIO',
            account_number='001-884920-001',
            account_type=BankAccount.AccountType.CHECKING,
            current_balance=Decimal('200000.00'),
            description='Cuenta Maestra Operativa BAC Credomatic Managua',
            is_active=True,
        )

        # 6. Caja Chica Asignada a Ingeniero Alfa
        self.fund_alfa = PettyCashFund.objects.create(
            organization=self.org,
            code="CAJ-01",
            name="Fondo Fijo Hilux Cuadrilla Alfa",
            custodian=self.user_engineer,
            linked_crew=self.crew_alfa,
            currency='NIO',
            allocated_amount=Decimal('10000.00'),
            current_balance=Decimal('0.00'),
            is_active=True,
        )

    # =========================================================================
    # 1. PRUEBA: CICLO FINANCIERO COMPLETO
    # =========================================================================
    def test_complete_petty_cash_lifecycle(self):
        """
        Valida el flujo end-to-end de tesorería y fondos de campo:
        1. Dotación inicial del fondo desde banco -> Saldos actualizados y TRX creada.
        2. Registro de gastos de campo vinculados a OT -> Balance disminuye, timeline de OT actualizado.
        3. Arqueo y solicitud formal de reposición -> Lote REP creado con estado SUBMITTED.
        4. Desembolso bancario ejecutado por Coordinador -> Fondos restaurados, gastos marcados is_replenished.
        """
        # Paso 1: Dotar el fondo fijo desde BAC Credomatic
        trx_dotacion = allocate_petty_cash_fund(
            organization=self.org,
            fund=self.fund_alfa,
            bank_account=self.bank_bac,
            amount=Decimal('10000.00'),
            user=self.user_owner,
        )
        self.fund_alfa.refresh_from_db()
        self.bank_bac.refresh_from_db()

        self.assertEqual(self.fund_alfa.current_balance, Decimal('10000.00'))
        self.assertEqual(self.bank_bac.current_balance, Decimal('190000.00'))
        self.assertEqual(trx_dotacion.transaction_type, FinancialTransaction.TransactionType.PETTY_CASH_ALLOCATION)
        self.assertEqual(trx_dotacion.balance_after, Decimal('10000.00'))

        # Paso 2: Registrar Gasto 1 (Combustible en ruta a mina)
        exp1 = record_petty_cash_expense(
            organization=self.org,
            fund=self.fund_alfa,
            expense_category=PettyCashExpense.Category.FUEL,
            vendor_name="Puma Tipitapa",
            amount=Decimal('2800.00'),
            description="35 Galones Diesel para Hilux Cuadrilla Alfa",
            user=self.user_engineer,
            work_order=self.work_order,
            vendor_tax_id="J0310000012345",
            invoice_number="FACT-9921",
        )
        self.fund_alfa.refresh_from_db()
        self.assertEqual(self.fund_alfa.current_balance, Decimal('7200.00'))
        self.assertEqual(self.fund_alfa.spent_amount, Decimal('2800.00'))
        self.assertEqual(self.fund_alfa.spent_percentage, 28)
        self.assertTrue(exp1.voucher_number.startswith("REC-"))
        self.assertFalse(exp1.is_replenished)

        # Verificar Bitácora Técnica en la Orden de Trabajo
        ot_log = WorkOrderTimelineLog.objects.filter(
            work_order=self.work_order,
            event_type='PETTY_CASH_EXPENSE'
        ).first()
        self.assertIsNotNone(ot_log)
        self.assertIn("FACT-9921", ot_log.details)
        self.assertIn("Puma Tipitapa", ot_log.details)

        # Paso 3: Registrar Gasto 2 (Viáticos y comida de cuadrilla)
        exp2 = record_petty_cash_expense(
            organization=self.org,
            fund=self.fund_alfa,
            expense_category=PettyCashExpense.Category.PER_DIEM,
            vendor_name="Restaurante La Casona Sebaco",
            amount=Decimal('1200.00'),
            description="Alimentación 4 técnicos despliegue montaje",
            user=self.user_engineer,
            work_order=self.work_order,
            invoice_number="REC-041",
        )
        self.fund_alfa.refresh_from_db()
        self.assertEqual(self.fund_alfa.current_balance, Decimal('6000.00'))
        self.assertEqual(self.fund_alfa.spent_amount, Decimal('4000.00'))

        # Paso 4: Ingeniero realiza Arqueo y Solicita Reposición
        rep = submit_petty_cash_replenishment(
            organization=self.org,
            fund=self.fund_alfa,
            notes="Arqueo físico semanal cuadrilla alfa. Todos los recibos adjuntos.",
            user=self.user_engineer,
        )
        self.assertEqual(rep.status, PettyCashReplenishment.Status.SUBMITTED)
        self.assertEqual(rep.total_expenses_amount, Decimal('4000.00'))
        self.assertEqual(rep.requested_amount, Decimal('4000.00'))
        self.assertTrue(rep.code.startswith("REP-"))
        self.assertEqual(rep.expenses.count(), 2)

        # Paso 5: Coordinador Operativo aprueba y desembolsa desde BAC
        trx_disburse = disburse_petty_cash_replenishment(
            organization=self.org,
            replenishment=rep,
            bank_account=self.bank_bac,
            user=self.user_coord,
        )
        self.fund_alfa.refresh_from_db()
        self.bank_bac.refresh_from_db()
        rep.refresh_from_db()
        exp1.refresh_from_db()
        exp2.refresh_from_db()

        # Validaciones de Estado Final
        self.assertEqual(rep.status, PettyCashReplenishment.Status.DISBURSED)
        self.assertEqual(rep.approved_by, self.user_coord)
        self.assertEqual(rep.disbursed_from_bank, self.bank_bac)
        self.assertTrue(exp1.is_replenished)
        self.assertTrue(exp2.is_replenished)

        # Saldo del Fondo Fijo debe haber retornado a su límite autorizado de C$ 10,000.00
        self.assertEqual(self.fund_alfa.current_balance, Decimal('10000.00'))
        self.assertEqual(self.fund_alfa.spent_amount, Decimal('0.00'))

        # Saldo bancario debe reflejar el débito de los C$ 4,000.00 reembolsados
        self.assertEqual(self.bank_bac.current_balance, Decimal('186000.00'))
        self.assertEqual(trx_disburse.transaction_type, FinancialTransaction.TransactionType.PETTY_CASH_REPLENISH)
        self.assertEqual(trx_disburse.balance_after, Decimal('10000.00'))

    # =========================================================================
    # 2. PRUEBA: PREVENCIÓN DE SOBREGIRO Y SALDO NEGATIVO
    # =========================================================================
    def test_negative_balance_prevention(self):
        """
        Verifica que el sistema rechace transacciones que generen saldos negativos,
        tanto en Cajas Chicas como en Cuentas Bancarias.
        """
        # 1. Rechazo de dotación bancaria por fondos insuficientes
        bank_pobre = BankAccount.objects.create(
            organization=self.org,
            bank_name=BankAccount.BankName.BANPRO,
            currency='NIO',
            account_number='002-111111-001',
            account_type=BankAccount.AccountType.CHECKING,
            current_balance=Decimal('500.00'),
            is_active=True,
        )
        with self.assertRaises(ValidationError) as ctx:
            allocate_petty_cash_fund(
                organization=self.org,
                fund=self.fund_alfa,
                bank_account=bank_pobre,
                amount=Decimal('1000.00'),
                user=self.user_owner,
            )
        self.assertIn("insuficiente", str(ctx.exception).lower())
        self.assertEqual(bank_pobre.current_balance, Decimal('500.00'))

        # 2. Rechazo de gasto en caja chica que excede el efectivo disponible
        # Caja tiene 0.00 de saldo disponible
        with self.assertRaises(ValidationError) as ctx:
            record_petty_cash_expense(
                organization=self.org,
                fund=self.fund_alfa,
                expense_category=PettyCashExpense.Category.FUEL,
                vendor_name="Puma",
                amount=Decimal('150.00'),
                description="Compra de combustible sin saldo",
                user=self.user_engineer,
            )
        self.assertIn("insuficiente", str(ctx.exception).lower())
        self.assertEqual(self.fund_alfa.current_balance, Decimal('0.00'))

    # =========================================================================
    # 3. PRUEBA: INMUTABILIDAD ESTRICTA DEL LIBRO MAYOR FINANCIERO
    # =========================================================================
    def test_ledger_immutability(self):
        """
        Garantiza que ningún registro de FinancialTransaction pueda ser alterado ni borrado.
        Garantiza que comprobantes ya liquidados (is_replenished=True) no puedan ser adulterados.
        """
        # Crear transacción válida
        trx = FinancialTransaction.objects.create(
            organization=self.org,
            transaction_type=FinancialTransaction.TransactionType.PETTY_CASH_ALLOCATION,
            bank_account=self.bank_bac,
            petty_cash_fund=self.fund_alfa,
            amount=Decimal('5000.00'),
            balance_after=Decimal('205000.00'),
            concept="Inyección de capital inicial",
            performed_by=self.user_owner,
        )

        # Intento de modificación debe lanzar ValidationError
        trx.concept = "Modificación fraudulenta de concepto"
        with self.assertRaises(ValidationError):
            trx.save()

        # Intento de eliminación debe lanzar ValidationError
        with self.assertRaises(ValidationError):
            trx.delete()

        # Validar inmutabilidad de comprobante liquidado
        self.fund_alfa.current_balance = Decimal('1000.00')
        self.fund_alfa.save()

        expense = record_petty_cash_expense(
            organization=self.org,
            fund=self.fund_alfa,
            expense_category=PettyCashExpense.Category.TOLL_PARKING,
            vendor_name="Peaje San Benito",
            amount=Decimal('100.00'),
            description="Peaje cuadrilla",
            user=self.user_engineer,
        )
        expense.is_replenished = True
        expense.save()

        # Intentar cambiar monto una vez reembolsado
        expense.amount = Decimal('500.00')
        with self.assertRaises(ValidationError):
            expense.clean()

    # =========================================================================
    # 4. PRUEBA: MATRIZ DE AUTORIDAD RBAC Y CONFIDENCIALIDAD BANCARIA
    # =========================================================================
    def test_rbac_and_financial_confidentiality(self):
        """
        Verifica:
        - Nivel 20 (Técnico de Campo) tiene acceso denegado (HTTP 403).
        - Nivel 50 (Ingeniero Custodio) puede ver su caja, pero NO ve cuentas bancarias ni saldos de bancos.
        - Nivel 50 no puede gastar ni rendir cajas asignadas a otro custodio.
        - Nivel 80 (Coordinador) ve cuentas bancarias y aprueba desembolsos.
        """
        # Dotar caja para pruebas de interfaz
        self.fund_alfa.current_balance = Decimal('5000.00')
        self.fund_alfa.save()

        # Caja asignada al Ingeniero Beta
        fund_beta = PettyCashFund.objects.create(
            organization=self.org,
            code="CAJ-02",
            name="Fondo Fijo Hilux Cuadrilla Beta",
            custodian=self.user_engineer_beta,
            currency='NIO',
            allocated_amount=Decimal('8000.00'),
            current_balance=Decimal('2000.00'),
            is_active=True,
        )

        # 1. Nivel 20: Técnico de Campo -> 403 Forbidden
        client_tech = Client()
        client_tech.force_login(self.user_tech)
        resp = client_tech.get(reverse('finance:dashboard'))
        self.assertEqual(resp.status_code, 403)

        # 2. Nivel 50: Ingeniero Alfa -> Dashboard
        client_eng = Client()
        client_eng.force_login(self.user_engineer)
        resp = client_eng.get(reverse('finance:dashboard'))
        self.assertEqual(resp.status_code, 200)

        # Confidencialidad Bancaria: can_view_bank_accounts debe ser False
        self.assertFalse(resp.context['can_view_bank_accounts'])
        # Las cuentas bancarias no deben estar presentes en el contexto del ingeniero
        self.assertEqual(len(resp.context['bank_accounts']), 0)
        self.assertEqual(resp.context['total_bank_nio'], Decimal('0.00'))

        # Solo debe ver su propia caja (CAJ-01), no la de Beta (CAJ-02)
        funds_visible = [f.code for f in resp.context['funds']]
        self.assertIn("CAJ-01", funds_visible)
        self.assertNotIn("CAJ-02", funds_visible)

        # Ingeniero Alfa intenta registrar gasto en CAJ-02 (de Beta) -> 403
        post_data = {
            'fund': str(fund_beta.pk),
            'amount': '500.00',
            'expense_category': 'FUEL',
            'vendor_name': 'Puma Tipitapa',
            'description': 'Intento de gasto en caja ajena',
            'spent_at': str(timezone.now().date()),
        }
        resp_post = client_eng.post(reverse('finance:expense_create'), data=post_data)
        self.assertEqual(resp_post.status_code, 403)

        # 3. Nivel 80: Coordinador Operativo -> Ve todo y tiene can_view_bank_accounts
        client_coord = Client()
        client_coord.force_login(self.user_coord)
        resp_coord = client_coord.get(reverse('finance:dashboard'))
        self.assertEqual(resp_coord.status_code, 200)
        self.assertTrue(resp_coord.context['can_view_bank_accounts'])
        self.assertTrue(resp_coord.context['can_manage_funds'])
        self.assertGreater(len(resp_coord.context['bank_accounts']), 0)
        # Debe ver ambas cajas
        coord_funds = [f.code for f in resp_coord.context['funds']]
        self.assertIn("CAJ-01", coord_funds)
        self.assertIn("CAJ-02", coord_funds)

    # =========================================================================
    # 5. PRUEBA: AISLAMIENTO MULTI-TENANT ESTRICTO
    # =========================================================================
    def test_multi_tenant_isolation(self):
        """
        Garantiza que un usuario de otra organización (Tenant B), incluso con rol Owner (100),
        no pueda consultar, listar ni operar cuentas bancarias, cajas chicas o transacciones de Tenant A.
        """
        # Crear cuenta bancaria y caja en la organización intrusa
        bank_intruder = BankAccount.objects.create(
            organization=self.org_intruder,
            bank_name=BankAccount.BankName.LAFISE,
            currency='USD',
            account_number='110-994821-001',
            account_type=BankAccount.AccountType.CHECKING,
            current_balance=Decimal('50000.00'),
            is_active=True,
        )
        fund_intruder = PettyCashFund.objects.create(
            organization=self.org_intruder,
            code="CAJ-01",
            name="Caja Intruso Norte",
            custodian=self.user_intruder,
            currency='NIO',
            allocated_amount=Decimal('5000.00'),
            current_balance=Decimal('5000.00'),
            is_active=True,
        )

        client_intruder = Client()
        client_intruder.force_login(self.user_intruder)

        # Dashboard del intruso: solo ve sus recursos
        resp = client_intruder.get(reverse('finance:dashboard'))
        self.assertEqual(resp.status_code, 200)

        bank_ids = [b.id for b in resp.context['bank_accounts']]
        fund_ids = [f.id for f in resp.context['funds']]

        self.assertIn(bank_intruder.id, bank_ids)
        self.assertNotIn(self.bank_bac.id, bank_ids)

        self.assertIn(fund_intruder.id, fund_ids)
        self.assertNotIn(self.fund_alfa.id, fund_ids)

        # Intento de consultar detalle de caja de Tenant A -> 404
        resp_detail = client_intruder.get(reverse('finance:fund_detail', kwargs={'pk': self.fund_alfa.pk}))
        self.assertEqual(resp_detail.status_code, 404)
