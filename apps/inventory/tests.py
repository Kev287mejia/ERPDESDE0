from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import CountryConfig
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel
from apps.crm.models import Account
from apps.operations.models import Crew, WorkOrder, WorkOrderItem, WorkOrderTimelineLog
from apps.inventory.models import (
    Warehouse,
    InventoryItem,
    StockBalance,
    StockMovement,
)
from apps.inventory.services import (
    record_stock_entry,
    transfer_stock_between_warehouses,
    dispatch_stock_to_work_order,
)

User = get_user_model()


class InventoryModuleEndToEndTestCase(TestCase):
    """
    Suite de pruebas End-to-End para el Módulo de Inventario, Bodegas Móviles,
    Kardex Transaccional y Despacho a OTs (apps/inventory).
    Verifica:
    1. Ciclo Logístico Completo: Entrada -> Traslado a Unidad Móvil -> Despacho a OT.
    2. Prevención estricta de saldo negativo y protección transaccional.
    3. Inmutabilidad del Libro Mayor (StockMovement).
    4. Confidencialidad de costos y segregación de funciones RBAC (Niveles 100, 80, 70, 50 y 20).
    5. Aislamiento Multi-Tenant Estricto por Organización.
    """

    def setUp(self):
        # 1. Configuración de País
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
            name="Vector Ingeniería Nicaragua, S.A.",
            legal_name="Vector Ingeniería de Centroamérica, S.A.",
            slug="vector-ni-inventory",
            tax_id="J0310000199999",
            country=self.country_ni,
            enabled_modules=['crm', 'operations', 'sst', 'inventory'],
            is_active=True,
        )

        self.org_intruder = Organization.objects.create(
            name="Constructora Invasora, S.A.",
            legal_name="Invasora S.A.",
            slug="invasora-ni-inventory",
            tax_id="J0310000188888",
            country=self.country_ni,
            enabled_modules=['inventory'],
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

        # Nivel 70: Oficial SST
        self.user_sst = User.objects.create_user(
            email='sst@vector.com.ni',
            full_name='Lic. Carmen Silva (Oficial SST)',
            password='password123'
        )
        OrganizationMembership.objects.create(
            user=self.user_sst,
            organization=self.org,
            role_level=RoleLevel.SST_OFFICER,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 50: Ingeniero Residente / Supervisor
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

        # Usuario en Organización Invasora
        self.user_intruder = User.objects.create_user(
            email='intruder@invasora.com.ni',
            full_name='Carlos Espía',
            password='password123'
        )
        OrganizationMembership.objects.create(
            user=self.user_intruder,
            organization=self.org_intruder,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
            is_default_org=True,
        )

        # 4. Datos Base de Operaciones: Cuadrilla Alfa y Orden de Trabajo OT-2026-0001
        self.crew_alfa = Crew.objects.create(
            organization=self.org,
            code="CUAD-01",
            name="Cuadrilla Alfa - Alta Tensión",
            specialty="Media y Alta Tensión",
            leader=self.user_engineer,
            vehicle_plate="M 345-890",
            vehicle_description="Hilux 4x4 #04",
            is_active=True,
        )
        self.crew_alfa.members.add(self.user_tech)

        self.account = Account.objects.create(
            organization=self.org,
            commercial_name="Ingenio Monte Rosa",
            legal_name="Pantaleon Nicaragua S.A.",
            tax_id="J0310000112233",
            city="Chinandega",
            address="Km 135 Carretera Chinandega - Corinto",
            default_currency="NIO",
        )

        self.work_order = WorkOrder.objects.create(
            organization=self.org,
            number="OT-2026-0001",
            title="Mantenimiento Subestación Eléctrica 138kV",
            account=self.account,
            assigned_crew=self.crew_alfa,
            assigned_engineer=self.user_engineer,
            phase=WorkOrder.Phase.IN_PROGRESS,
            is_high_risk=False,
            sst_cleared=True,
        )

        # Partida planificada en la OT (BOM)
        self.wo_item = WorkOrderItem.objects.create(
            organization=self.org,
            work_order=self.work_order,
            item_type=WorkOrderItem.ItemType.MATERIAL,
            code="MAT-CAB-01",
            description="Cable de Potencia XLP 15kV Calibre 2 AWG",
            unit="MTS",
            planned_quantity=Decimal('2.00'),
            executed_quantity=Decimal('0.00'),
            is_completed=False,
        )

    def _get_client_for_user(self, user, org=None):
        """Helper para autenticar cliente HTTP con sesión de organización activa."""
        client = Client()
        client.force_login(user)
        session = client.session
        target_org = org or self.org
        session['active_org_id'] = str(target_org.id)
        session.save()
        return client

    # --------------------------------------------------------------------------
    # TEST 1: Ciclo Logístico Completo (Entrada -> Traslado Móvil -> Despacho OT)
    # --------------------------------------------------------------------------
    def test_complete_logistics_cycle_and_bom_auto_execution(self):
        """
        1) Coordinador (80) crea Bodega Central y Unidad Móvil Cuadrilla Alfa,
           da de alta el SKU MAT-CAB-01 y registra una entrada de 10.00 MTS a C$ 20,000.00 c/u.
        2) Coordinador (80) traslada 4.00 MTS de Bodega Central a Unidad Móvil Cuadrilla Alfa.
           (StockBalance: 6.00 MTS en Central, 4.00 MTS en Móvil).
        3) Ingeniero (50) despacha 2.00 MTS desde Unidad Móvil hacia OT-2026-0001.
           El saldo móvil baja a 2.00 MTS, el WorkOrderItem de la OT actualiza automáticamente
           executed_quantity = 2.00 (is_completed = True) y se crea el evento inmutable
           MATERIAL_DISPATCHED en WorkOrderTimelineLog.
        """
        client_coord = self._get_client_for_user(self.user_ops_coord)

        # 1a. Crear Bodega Central
        resp = client_coord.post(reverse('inventory:warehouse_create'), {
            'code': 'BOD-01',
            'name': 'Bodega Central Managua',
            'warehouse_type': Warehouse.WarehouseType.CENTRAL,
            'address': 'Carretera Norte Km 5.5, Managua',
        })
        self.assertEqual(resp.status_code, 302)
        wh_central = Warehouse.objects.get(organization=self.org, code='BOD-01')

        # 1b. Crear Bodega Móvil de Cuadrilla Alfa
        resp = client_coord.post(reverse('inventory:warehouse_create'), {
            'code': 'BOD-MOV-01',
            'name': 'Unidad Móvil Hilux Cuadrilla Alfa',
            'warehouse_type': Warehouse.WarehouseType.MOBILE_CREW,
            'linked_crew': str(self.crew_alfa.id),
            'address': 'En Tránsito / Furgoneta',
        })
        self.assertEqual(resp.status_code, 302)
        wh_mobile = Warehouse.objects.get(organization=self.org, code='BOD-MOV-01')
        self.assertEqual(wh_mobile.linked_crew, self.crew_alfa)

        # 1c. Dar de alta SKU MAT-CAB-01
        resp = client_coord.post(reverse('inventory:item_create'), {
            'sku': 'MAT-CAB-01',
            'name': 'Cable de Potencia XLP 15kV Calibre 2 AWG',
            'category': InventoryItem.Category.ELECTRICAL,
            'unit': 'MTS',
            'min_stock_level': '3.00',
            'unit_cost': '0.00',
        })
        self.assertEqual(resp.status_code, 302)
        item = InventoryItem.objects.get(organization=self.org, sku='MAT-CAB-01')

        # 1d. Entrada por Compra de 10.00 MTS a C$ 20,000.00
        resp = client_coord.post(reverse('inventory:stock_entry'), {
            'warehouse': str(wh_central.id),
            'item': str(item.id),
            'quantity': '10.00',
            'unit_cost': '20000.00',
            'movement_type': StockMovement.MovementType.IN_PURCHASE,
            'reference_note': 'Factura Proveedor Elvatron #8812 - Recepción Inicial',
        })
        self.assertEqual(resp.status_code, 302)

        # Validar saldos tras entrada
        bal_central = StockBalance.objects.get(organization=self.org, warehouse=wh_central, item=item)
        self.assertEqual(bal_central.quantity, Decimal('10.00'))
        item.refresh_from_db()
        self.assertEqual(item.unit_cost, Decimal('20000.00'))
        self.assertEqual(item.total_stock(), Decimal('10.00'))
        self.assertFalse(item.is_low_stock())

        kardex_1 = StockMovement.objects.get(organization=self.org, movement_type=StockMovement.MovementType.IN_PURCHASE)
        self.assertEqual(kardex_1.number, "KDX-2026-0001")
        self.assertEqual(kardex_1.balance_after, Decimal('10.00'))

        # 2. Traslado de 4.00 MTS desde Bodega Central hacia Unidad Móvil Cuadrilla Alfa
        resp = client_coord.post(reverse('inventory:stock_transfer'), {
            'source_warehouse': str(wh_central.id),
            'target_warehouse': str(wh_mobile.id),
            'item': str(item.id),
            'quantity': '4.00',
            'reference_note': 'Carga inicial para labores en Subestación Eléctrica',
        })
        self.assertEqual(resp.status_code, 302)

        bal_central.refresh_from_db()
        bal_mobile = StockBalance.objects.get(organization=self.org, warehouse=wh_mobile, item=item)
        self.assertEqual(bal_central.quantity, Decimal('6.00'))
        self.assertEqual(bal_mobile.quantity, Decimal('4.00'))
        self.assertEqual(item.total_stock(), Decimal('10.00'))  # Suma total organizacional no cambia

        # 3. Ingeniero (50) despacha 2.00 MTS desde Unidad Móvil hacia OT-2026-0001
        client_eng = self._get_client_for_user(self.user_engineer)
        resp = client_eng.post(reverse('inventory:stock_dispatch_ot'), {
            'warehouse': str(wh_mobile.id),
            'item': str(item.id),
            'work_order': str(self.work_order.id),
            'quantity': '2.00',
            'reference_note': 'Instalación de acometida subterránea 15kV',
        })
        self.assertEqual(resp.status_code, 302)

        # Verificación de saldo en unidad móvil
        bal_mobile.refresh_from_db()
        self.assertEqual(bal_mobile.quantity, Decimal('2.00'))

        # Verificación de BOM en la OT
        self.wo_item.refresh_from_db()
        self.assertEqual(self.wo_item.executed_quantity, Decimal('2.00'))
        self.assertTrue(self.wo_item.is_completed)

        # Verificación del movimiento de Kardex tipo OUT_WORKORDER
        kardex_out = StockMovement.objects.get(
            organization=self.org,
            movement_type=StockMovement.MovementType.OUT_WORKORDER
        )
        self.assertEqual(kardex_out.work_order, self.work_order)
        self.assertEqual(kardex_out.work_order_item, self.wo_item)
        self.assertEqual(kardex_out.quantity, Decimal('2.00'))
        self.assertEqual(kardex_out.balance_after, Decimal('2.00'))

        # Verificación de evento en Bitácora de la OT (WorkOrderTimelineLog)
        timeline_event = WorkOrderTimelineLog.objects.filter(
            work_order=self.work_order,
            event_type='MATERIAL_DISPATCHED'
        ).latest('created_at')
        self.assertIn("MAT-CAB-01", timeline_event.summary)
        self.assertIn("2.00 MTS", timeline_event.summary)
        self.assertIn(kardex_out.number, timeline_event.details)

    # --------------------------------------------------------------------------
    # TEST 2: Prevención Estricta de Saldo Negativo
    # --------------------------------------------------------------------------
    def test_prevent_negative_stock_balance(self):
        """
        Verifica que intentar despachar o trasladar más existencias de las disponibles
        lanza ValidationError y rechaza la transacción de manera atómica sin alterar saldos.
        """
        wh_central = Warehouse.objects.create(
            organization=self.org,
            code="BOD-NEG-01",
            name="Bodega Negativo",
            warehouse_type=Warehouse.WarehouseType.CENTRAL,
        )
        wh_target = Warehouse.objects.create(
            organization=self.org,
            code="BOD-NEG-02",
            name="Bodega Negativo Destino",
            warehouse_type=Warehouse.WarehouseType.PROJECT,
        )
        item = InventoryItem.objects.create(
            organization=self.org,
            sku="MAT-SEC-01",
            name="Seccionador Tripolar 15kV",
            unit="UND",
            unit_cost=Decimal('15000.00'),
        )

        # Ingresar 2 unidades a bodega central
        record_stock_entry(
            organization=self.org,
            warehouse=wh_central,
            item=item,
            quantity=Decimal('2.00'),
            unit_cost=Decimal('15000.00'),
            reference_note="Stock limitado",
            user=self.user_ops_coord,
        )

        bal = StockBalance.objects.get(organization=self.org, warehouse=wh_central, item=item)
        self.assertEqual(bal.quantity, Decimal('2.00'))

        # Intento de traslado de 50.00 unidades (exceso de stock)
        with self.assertRaises(ValidationError) as ctx:
            transfer_stock_between_warehouses(
                organization=self.org,
                source_warehouse=wh_central,
                target_warehouse=wh_target,
                item=item,
                quantity=Decimal('50.00'),
                reference_note="Intento inválido de sobregiro",
                user=self.user_ops_coord,
            )
        self.assertIn("Existencia insuficiente", str(ctx.exception))

        # Intento de despacho a OT de 10.00 unidades (exceso de stock)
        with self.assertRaises(ValidationError) as ctx:
            dispatch_stock_to_work_order(
                organization=self.org,
                warehouse=wh_central,
                item=item,
                work_order=self.work_order,
                quantity=Decimal('10.00'),
                user=self.user_engineer,
            )
        self.assertIn("Existencia insuficiente", str(ctx.exception))

        # El saldo no debe haber cambiado
        bal.refresh_from_db()
        self.assertEqual(bal.quantity, Decimal('2.00'))

    # --------------------------------------------------------------------------
    # TEST 3: Inmutabilidad del Kardex (StockMovement)
    # --------------------------------------------------------------------------
    def test_kardex_stock_movement_immutability(self):
        """
        Verifica que una vez creado un registro en StockMovement, cualquier intento
        de actualización (.save()) o eliminación (.delete()) lanza ValidationError.
        """
        wh = Warehouse.objects.create(
            organization=self.org,
            code="BOD-INM-01",
            name="Bodega Inmutable",
            warehouse_type=Warehouse.WarehouseType.CENTRAL,
        )
        item = InventoryItem.objects.create(
            organization=self.org,
            sku="MAT-INM-01",
            name="Fusible de Expulsión 25A",
            unit="UND",
            unit_cost=Decimal('450.00'),
        )

        movement = record_stock_entry(
            organization=self.org,
            warehouse=wh,
            item=item,
            quantity=Decimal('5.00'),
            unit_cost=Decimal('450.00'),
            reference_note="Lote inicial inmutable",
            user=self.user_ops_coord,
        )

        # 1. Intento de modificación
        movement.quantity = Decimal('100.00')
        with self.assertRaises(ValidationError) as ctx:
            movement.save()
        self.assertIn("El registro de Kardex es inmutable", str(ctx.exception))

        # 2. Intento de eliminación
        with self.assertRaises(ValidationError) as ctx:
            movement.delete()
        self.assertIn("El registro de Kardex es inmutable", str(ctx.exception))

    # --------------------------------------------------------------------------
    # TEST 4: Confidencialidad de Costos y Matriz RBAC
    # --------------------------------------------------------------------------
    def test_cost_confidentiality_and_rbac_matrix(self):
        """
        Verifica:
        1. ENGINEER (50):
           - Puede consultar existencias físicas en /inventory/.
           - El HTML NUNCA expone costos unitarios ni valorización monetaria ('20000.00', '20,000.00').
           - Recibe HTTP 403 al intentar registrar entradas de stock o traslados (reservado a 80+).
        2. SST_OFFICER (70):
           - Puede consultar el almacén en /inventory/.
           - Recibe HTTP 403 al intentar despachar materiales técnicos a una OT (segregación de funciones).
        3. TECHNICIAN (20):
           - Recibe HTTP 403 inmediato al intentar acceder a /inventory/.
        """
        wh = Warehouse.objects.create(
            organization=self.org,
            code="BOD-CONF-01",
            name="Bodega Confidencial",
            warehouse_type=Warehouse.WarehouseType.CENTRAL,
        )
        item = InventoryItem.objects.create(
            organization=self.org,
            sku="MAT-CONF-01",
            name="Transformador de Distribución 25kVA",
            unit="UND",
            unit_cost=Decimal('78500.00'),
        )
        record_stock_entry(
            organization=self.org,
            warehouse=wh,
            item=item,
            quantity=Decimal('3.00'),
            unit_cost=Decimal('78500.00'),
            reference_note="Recepción Transformadores",
            user=self.user_ops_coord,
        )

        # 1. Pruebas con ENGINEER (50)
        client_eng = self._get_client_for_user(self.user_engineer)
        resp_eng = client_eng.get(reverse('inventory:dashboard'))
        self.assertEqual(resp_eng.status_code, 200)

        # Ve el SKU y cantidades físicas
        self.assertContains(resp_eng, "MAT-CONF-01")
        self.assertContains(resp_eng, "3.00")

        # NUNCA ve los costos financieros
        self.assertNotContains(resp_eng, "78500.00")
        self.assertNotContains(resp_eng, "78,500.00")
        self.assertNotContains(resp_eng, "Valorización Total")

        # Intento no autorizado de registrar entrada de stock -> HTTP 403
        resp_eng_entry = client_eng.post(reverse('inventory:stock_entry'), {
            'warehouse': str(wh.id),
            'item': str(item.id),
            'quantity': '1.00',
            'unit_cost': '78500.00',
            'movement_type': StockMovement.MovementType.IN_PURCHASE,
            'reference_note': 'Entrada por Ingeniero no permitida',
        })
        self.assertEqual(resp_eng_entry.status_code, 403)

        # 2. Pruebas con SST_OFFICER (70)
        client_sst = self._get_client_for_user(self.user_sst)
        resp_sst = client_sst.get(reverse('inventory:dashboard'))
        self.assertEqual(resp_sst.status_code, 200)
        self.assertContains(resp_sst, "MAT-CONF-01")

        # Intento de despachar materiales a una OT -> HTTP 403 (Segregación de funciones)
        resp_sst_dispatch = client_sst.post(reverse('inventory:stock_dispatch_ot'), {
            'warehouse': str(wh.id),
            'item': str(item.id),
            'work_order': str(self.work_order.id),
            'quantity': '1.00',
            'reference_note': 'Despacho intentado por SST',
        })
        self.assertEqual(resp_sst_dispatch.status_code, 403)

        # 3. Pruebas con TECHNICIAN (20) -> HTTP 403 inmediato
        client_tech = self._get_client_for_user(self.user_tech)
        resp_tech = client_tech.get(reverse('inventory:dashboard'))
        self.assertEqual(resp_tech.status_code, 403)

        # 4. Verificación con COORDINADOR (80) -> Sí ve costos y valorización
        client_coord = self._get_client_for_user(self.user_ops_coord)
        resp_coord = client_coord.get(reverse('inventory:dashboard'))
        self.assertEqual(resp_coord.status_code, 200)
        self.assertContains(resp_coord, "Valorización")
        self.assertContains(resp_coord, "78500.00")

    # --------------------------------------------------------------------------
    # TEST 5: Aislamiento Multi-Tenant Estricto por Organización
    # --------------------------------------------------------------------------
    def test_multi_tenant_isolation_in_inventory(self):
        """
        Verifica que los almacenes, existencias y movimientos de una organización
        son completamente invisibles para usuarios de otra organización.
        """
        # Crear bodega y producto en org invasora
        wh_intruder = Warehouse.objects.create(
            organization=self.org_intruder,
            code="BOD-INT-01",
            name="Bodega Invasora",
            warehouse_type=Warehouse.WarehouseType.CENTRAL,
        )
        item_intruder = InventoryItem.objects.create(
            organization=self.org_intruder,
            sku="SKU-INT-99",
            name="Material Invasor Confidencial",
            unit="UND",
            unit_cost=Decimal('100.00'),
        )

        # Crear item específico en org principal
        item_vector = InventoryItem.objects.create(
            organization=self.org,
            sku="SKU-VEC-99",
            name="Cable Primario Exclusivo Vector",
            unit="UND",
            unit_cost=Decimal('500.00'),
        )

        client_intruder = self._get_client_for_user(self.user_intruder, org=self.org_intruder)
        resp_intruder = client_intruder.get(reverse('inventory:dashboard'))
        self.assertEqual(resp_intruder.status_code, 200)

        # El invasor solo ve sus datos
        self.assertContains(resp_intruder, "SKU-INT-99")
        self.assertContains(resp_intruder, "Material Invasor Confidencial")
        self.assertNotContains(resp_intruder, "SKU-VEC-99")
        self.assertNotContains(resp_intruder, "Cable Primario Exclusivo Vector")

        # La org principal no ve los datos del invasor
        client_coord = self._get_client_for_user(self.user_ops_coord)
        resp_vector = client_coord.get(reverse('inventory:dashboard'))
        self.assertContains(resp_vector, "SKU-VEC-99")
        self.assertContains(resp_vector, "Cable Primario Exclusivo Vector")
        self.assertNotContains(resp_vector, "SKU-INT-99")
        self.assertNotContains(resp_vector, "Material Invasor Confidencial")
