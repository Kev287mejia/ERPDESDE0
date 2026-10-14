from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.core.models import CountryConfig
from apps.core.services.sandbox_seeder import SandboxScenarioSeeder
from apps.crm.models import Account, Opportunity, Quote
from apps.finance.models import (
    BankAccount,
    FinancialTransaction,
    PettyCashExpense,
    PettyCashFund,
    PettyCashReplenishment,
)
from apps.inventory.models import InventoryItem, StockBalance, StockMovement, Warehouse
from apps.operations.models import Crew, WorkOrder
from apps.sst.models import EPPDelivery, LeaveRequest, SafetyChecklist
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel

User = get_user_model()


class SandboxScenarioSeederTestCase(TestCase):
    """
    Suite de pruebas unitarias para el motor de escenario industrial de Nicaragua.
    Verifica la siembra transaccional idempotente en los 6 subsistemas y la purga limpia.
    """

    def setUp(self):
        self.country_ni, _ = CountryConfig.objects.get_or_create(
            code='NI',
            defaults={
                'name': 'Nicaragua',
                'flag_emoji': 'NI',
                'primary_currency_code': 'NIO',
                'primary_currency_symbol': 'C$',
                'tax_id_label': 'RUC',
                'tax_id_regex': r'^[A-Z]\d{13}$',
                'is_active': True,
                'default_tax_rate': Decimal('15.00'),
                'default_tax_name': 'IVA',
            }
        )
        self.owner = User.objects.create_user(
            email='evaluador.test@eternallabs.ni',
            password='Password123!',
            full_name='Ing. Evaluador Principal',
        )
        self.organization = Organization.objects.create(
            name='TEST INDUSTRIAL S.A.',
            legal_name='Test Industrial de Nicaragua Sociedad Anónima',
            tax_id='J0310000999888',
            country=self.country_ni,
            currency=Organization.Currency.NIO,
            tax_regime=Organization.TaxRegime.GENERAL,
            industry=Organization.Industry.CONSTRUCTION,
            accounting_template=Organization.AccountingTemplate.NIIF_PYMES,
            enabled_modules=['crm', 'operations', 'sst', 'inventory', 'finance'],
        )
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.owner,
            role_level=RoleLevel.OWNER_ADMIN,
            job_title='Director General',
            is_active=True,
        )

    def test_populate_for_organization_creates_all_subsystems(self):
        """Verifica que el seeder popule los registros industriales en todos los módulos."""
        SandboxScenarioSeeder.populate_for_organization(self.organization, self.owner)

        # 1. Tenancy: 6 colaboradores adicionales cubriendo la jerarquía
        members = OrganizationMembership.objects.filter(organization=self.organization)
        self.assertEqual(members.count(), 7)  # Owner + 6 adicionales
        roles = set(members.values_list('role_level', flat=True))
        self.assertTrue({85, 80, 70, 50, 20, 10}.issubset(roles))

        # 2. CRM: 5 cuentas, 6 oportunidades, 4 cotizaciones
        accounts = Account.objects.filter(organization=self.organization)
        self.assertEqual(accounts.count(), 5)
        opportunities = Opportunity.objects.filter(organization=self.organization)
        self.assertEqual(opportunities.count(), 6)
        quotes = Quote.objects.filter(organization=self.organization)
        self.assertEqual(quotes.count(), 4)

        # 3. Operations: 3 cuadrillas, 4 órdenes de trabajo
        crews = Crew.objects.filter(organization=self.organization)
        self.assertEqual(crews.count(), 3)
        work_orders = WorkOrder.objects.filter(organization=self.organization)
        self.assertEqual(work_orders.count(), 4)

        # 4. SST: 2 checklists, 3 entregas EPP, 2 solicitudes de permiso
        checklists = SafetyChecklist.objects.filter(organization=self.organization)
        self.assertEqual(checklists.count(), 2)
        epps = EPPDelivery.objects.filter(organization=self.organization)
        self.assertEqual(epps.count(), 3)
        leaves = LeaveRequest.objects.filter(organization=self.organization)
        self.assertEqual(leaves.count(), 2)

        # 5. Inventory: 3 bodegas, 8 items, balances y movimientos Kardex
        warehouses = Warehouse.objects.filter(organization=self.organization)
        self.assertEqual(warehouses.count(), 3)
        items = InventoryItem.objects.filter(organization=self.organization)
        self.assertEqual(items.count(), 8)
        balances = StockBalance.objects.filter(organization=self.organization)
        self.assertGreaterEqual(balances.count(), 8)
        movements = StockMovement.objects.filter(organization=self.organization)
        self.assertGreaterEqual(movements.count(), 4)

        # 6. Finance: 2 cuentas bancarias, 1 fondo de caja chica, gastos, reposición y transacciones
        bank_accounts = BankAccount.objects.filter(organization=self.organization)
        self.assertEqual(bank_accounts.count(), 2)
        funds = PettyCashFund.objects.filter(organization=self.organization)
        self.assertEqual(funds.count(), 1)
        expenses = PettyCashExpense.objects.filter(organization=self.organization)
        self.assertEqual(expenses.count(), 3)
        replenishments = PettyCashReplenishment.objects.filter(organization=self.organization)
        self.assertEqual(replenishments.count(), 1)
        transactions = FinancialTransaction.objects.filter(organization=self.organization)
        self.assertGreaterEqual(transactions.count(), 3)

    def test_populate_is_idempotent(self):
        """Verifica que ejecutar populate dos veces no duplique registros ni arroje errores."""
        SandboxScenarioSeeder.populate_for_organization(self.organization, self.owner)
        initial_accounts_count = Account.objects.filter(organization=self.organization).count()
        initial_wo_count = WorkOrder.objects.filter(organization=self.organization).count()

        # Segunda ejecución
        SandboxScenarioSeeder.populate_for_organization(self.organization, self.owner)
        self.assertEqual(Account.objects.filter(organization=self.organization).count(), initial_accounts_count)
        self.assertEqual(WorkOrder.objects.filter(organization=self.organization).count(), initial_wo_count)

    def test_reset_organization_data_cleans_cleanly(self):
        """Verifica que reset_organization_data limpie todos los registros operativos preservando la organización y al Owner."""
        SandboxScenarioSeeder.populate_for_organization(self.organization, self.owner)
        SandboxScenarioSeeder.reset_organization_data(self.organization)

        # La organización y el Owner permanecen intactos
        self.assertTrue(Organization.objects.filter(id=self.organization.id).exists())
        self.assertEqual(OrganizationMembership.objects.filter(organization=self.organization).count(), 1)
        owner_membership = OrganizationMembership.objects.filter(organization=self.organization).first()
        self.assertEqual(owner_membership.user, self.owner)
        self.assertEqual(owner_membership.role_level, RoleLevel.OWNER_ADMIN)

        # Todos los registros operativos deben ser 0
        self.assertEqual(Account.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(Opportunity.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(Quote.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(Crew.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(WorkOrder.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(SafetyChecklist.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(EPPDelivery.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(LeaveRequest.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(Warehouse.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(InventoryItem.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(StockBalance.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(StockMovement.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(BankAccount.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(PettyCashFund.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(PettyCashExpense.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(PettyCashReplenishment.objects.filter(organization=self.organization).count(), 0)
        self.assertEqual(FinancialTransaction.objects.filter(organization=self.organization).count(), 0)
