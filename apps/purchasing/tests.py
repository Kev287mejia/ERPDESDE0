"""
Suite Integral de Pruebas Unitarias y de Integración - apps/purchasing
Eternal Labs - Módulo de Compras, Proveedores, Kardex, Cuentas por Pagar y Retenciones DGI.
"""
from decimal import Decimal
import datetime
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import CountryConfig
from apps.inventory.models import InventoryItem, StockBalance, StockMovement, Warehouse
from apps.purchasing.models import PurchaseOrder, PurchaseOrderItem, Supplier, SupplierPayment
from apps.tenancy.models import Organization, OrganizationMembership, RoleLevel

User = get_user_model()


class PurchasingModuleTestSuite(TestCase):
    """
    Suite de Verificación y Auditoría para el Módulo de Compras (apps/purchasing):
    1. Aislamiento Multi-Tenant Estricto (.for_org(request.organization)).
    2. Precisión Fiscal Nicaragua (Ley 822 DGI & IMI Alcaldía sobre Base Imponible).
    3. Integración Transaccional con Almacén (record_stock_entry en Kardex e Idempotencia).
    4. Liquidación Bimonetaria de CxP e Inmutabilidad de Comprobantes de Egreso (EGR-*).
    5. Matriz de Autorización RBAC (Niveles 100, 85, 80, 50, 20).
    6. Emisión e Impresión de Constancias de Retención DGI (RET-*).
    """

    def setUp(self):
        # 1. Configuración Regional Nicaragua
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

        # 2. Organización Principal (SERMANSA) y Organización Aislada (Competencia)
        self.org = Organization.objects.create(
            name="SERMANSA Ingeniería S.A.",
            legal_name="Servicios y Mantenimiento Electromecánico S.A.",
            slug="sermansa-ni",
            tax_id="J0310000458912",
            country=self.country_ni,
            currency=Organization.Currency.NIO,
            enabled_modules=['crm', 'operations', 'sst', 'inventory', 'finance', 'billing', 'purchasing'],
            business_profile=Organization.BusinessProfile.ENGINEERING_SERVICES,
            is_active=True,
        )

        self.org_other = Organization.objects.create(
            name="Competencia Industrial S.A.",
            slug="competencia-ni",
            tax_id="J0310000999999",
            country=self.country_ni,
            currency=Organization.Currency.NIO,
            enabled_modules=['purchasing'],
            is_active=True,
        )

        # 3. Usuarios de Distintos Niveles Jerárquicos
        # Nivel 100: Director / Owner
        self.owner = User.objects.create_user(
            email='owner@sermansa.ni',
            full_name='Ing. Carlos Mendoza (Owner)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.org,
            role_level=RoleLevel.OWNER_ADMIN,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 85: Gerente Comercial / Compras
        self.commercial_mgr = User.objects.create_user(
            email='comercial@sermansa.ni',
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

        # Nivel 80: Coordinador de Operaciones / Almacén
        self.ops_coord = User.objects.create_user(
            email='operaciones@sermansa.ni',
            full_name='Ing. Marcos Fonseca (Operaciones)',
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
            email='ingeniero@sermansa.ni',
            full_name='Ing. Roberto Dávila (Ingeniero)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.engineer,
            organization=self.org,
            role_level=RoleLevel.ENGINEER,
            is_active=True,
            is_default_org=True,
        )

        # Nivel 20: Técnico de Campo
        self.technician = User.objects.create_user(
            email='tecnico@sermansa.ni',
            full_name='Téc. Pedro Martínez (Técnico)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.technician,
            organization=self.org,
            role_level=RoleLevel.TECHNICIAN,
            is_active=True,
            is_default_org=True,
        )

        # Usuario de otra organización
        self.other_user = User.objects.create_user(
            email='gerente@competencia.ni',
            full_name='Lic. Rodrigo Solís (Competencia)',
            password='Password123*',
        )
        OrganizationMembership.objects.create(
            user=self.other_user,
            organization=self.org_other,
            role_level=RoleLevel.COMMERCIAL_MGR,
            is_active=True,
            is_default_org=True,
        )

        # 4. Infraestructura de Bodega y Catálogo de Inventario
        self.warehouse = Warehouse.objects.create(
            organization=self.org,
            code='BOD-01',
            name='Bodega Central Managua',
            warehouse_type=Warehouse.WarehouseType.CENTRAL,
            is_active=True,
        )

        self.cable_item = InventoryItem.objects.create(
            organization=self.org,
            sku='MAT-CAB-02',
            name='Cable de Potencia XLP 15kV Calibre 2/0 AWG Apantallado',
            category=InventoryItem.Category.ELECTRICAL,
            unit='MTS',
            min_stock_level=Decimal('10.00'),
            unit_cost=Decimal('20000.00'),
            is_active=True,
        )

        # 5. Directorio de Proveedores Locales
        self.supplier = Supplier.objects.create(
            organization=self.org,
            code='PRV-0001',
            commercial_name='SINSA Industrial S.A.',
            legal_name='SERVICIOS INDUSTRIALES S.A.',
            tax_id='J0310000556677',
            contact_name='Ing. Roberto Somarriba',
            email='ventas.industriales@sinsa.com.ni',
            phone='+505 2270-1000',
            address='Carretera a Masaya Km 4.5',
            city='Managua',
            credit_days=30,
            default_ir_rate=Decimal('1.00'),
            default_imi_rate=Decimal('1.00'),
            is_active=True,
        )

    def test_01_exact_withholding_calculation_dgi_ley_822(self):
        """
        Verifica el cálculo matemático exacto de Retenciones en la Fuente según Ley 822 (DGI) e IMI (Alcaldía):
        - Base Imponible (subtotal): C$ 100,000.00 (5.00 MTS a C$ 20,000.00 c/u).
        - IVA Crédito Fiscal (15%): C$ 15,000.00.
        - Total Facturado (gross_total): C$ 115,000.00.
        - Retención IR 1% Bienes (sobre subtotal): C$ 1,000.00.
        - Retención IMI 1% Alcaldía (sobre subtotal): C$ 1,000.00.
        - Neto a Pagar al Proveedor (net_payable): C$ 113,000.00.
        - Consecutivo Oficial de Constancia: RET-YYYY-XXXX.
        """
        po = PurchaseOrder.objects.create(
            organization=self.org,
            number='OC-2026-0001',
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            supplier_invoice_number='FAC-SIN-99120',
            status=PurchaseOrder.Status.APPROVED,
            currency_code='NIO',
            currency_symbol='C$',
            exchange_rate=Decimal('36.6243'),
            apply_tax=True,
            tax_rate=Decimal('15.00'),
            ir_withholding_rate=Decimal('1.00'),
            imi_withholding_rate=Decimal('1.00'),
            created_by=self.commercial_mgr,
        )

        item = PurchaseOrderItem.objects.create(
            organization=self.org,
            purchase_order=po,
            inventory_item=self.cable_item,
            description='Cable de Potencia XLP 15kV',
            unit='MTS',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('20000.00'),
        )
        self.assertEqual(item.line_total, Decimal('100000.00'))

        po.recalculate_totals()
        po.save()

        # Verificaciones fiscales de precisión
        self.assertEqual(po.subtotal, Decimal('100000.00'))
        self.assertEqual(po.tax_total, Decimal('15000.00'))
        self.assertEqual(po.gross_total, Decimal('115000.00'))
        self.assertEqual(po.ir_withheld_amount, Decimal('1000.00'))
        self.assertEqual(po.imi_withheld_amount, Decimal('1000.00'))
        self.assertEqual(po.net_payable, Decimal('113000.00'))
        self.assertEqual(po.balance_due, Decimal('113000.00'))
        self.assertEqual(po.amount_paid, Decimal('0.00'))

        # Verificación del folio de constancia DGI
        self.assertTrue(po.withholding_certificate_number.startswith('RET-'))
        self.assertIn(str(timezone.now().year), po.withholding_certificate_number)

    def test_02_kardex_integration_and_receipt_idempotency(self):
        """
        Verifica la integración transaccional entre Compras y Almacén (apps/inventory):
        1. Al confirmar la recepción física en bodega por parte de OPERATIONS_COORD (80):
           - Invocación atómica a record_stock_entry().
           - Saldo físico incrementa en +5.00 MTS en Bodega Central.
           - Generación de folio inmutable KDX-* en el Kardex.
           - Costo unitario promedio ponderado actualizado.
           - Orden pasa a estado RECEIVED con stock_received = True.
        2. Idempotencia: Intentar recibir una segunda vez es bloqueado y no duplica stock.
        """
        po = PurchaseOrder.objects.create(
            organization=self.org,
            number='OC-2026-0002',
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            supplier_invoice_number='FAC-SIN-99121',
            status=PurchaseOrder.Status.APPROVED,
            currency_code='NIO',
            created_by=self.commercial_mgr,
        )
        PurchaseOrderItem.objects.create(
            organization=self.org,
            purchase_order=po,
            inventory_item=self.cable_item,
            quantity=Decimal('5.00'),
            unit_cost=Decimal('20000.00'),
        )
        po.recalculate_totals()
        po.save()

        # Verificar existencia inicial cero
        initial_stock = self.cable_item.total_stock()
        self.assertEqual(initial_stock, Decimal('0.00'))

        # Coordinador de Operaciones (80) ejecuta la recepción
        self.client.force_login(self.ops_coord)
        url = reverse('purchasing:order_receive', kwargs={'pk': po.pk})
        response = self.client.post(url, {'supplier_invoice_number': 'FAC-SIN-99121'})
        self.assertEqual(response.status_code, 302)

        # 1. Verificar estado de la Orden de Compra
        po.refresh_from_db()
        self.assertTrue(po.stock_received)
        self.assertEqual(po.status, PurchaseOrder.Status.RECEIVED)
        self.assertEqual(po.received_by, self.ops_coord)
        self.assertIsNotNone(po.received_at)
        self.assertEqual(po.supplier_invoice_number, 'FAC-SIN-99121')

        # 2. Verificar existencia en Bodega Central (+5.00 MTS)
        balance = StockBalance.objects.get(
            organization=self.org,
            warehouse=self.warehouse,
            item=self.cable_item,
        )
        self.assertEqual(balance.quantity, Decimal('5.00'))
        self.assertEqual(self.cable_item.total_stock(), Decimal('5.00'))

        # 3. Verificar registro en Kardex (StockMovement inmutable)
        kdx_movements = StockMovement.objects.filter(
            organization=self.org,
            warehouse=self.warehouse,
            item=self.cable_item,
        )
        self.assertEqual(kdx_movements.count(), 1)
        kdx = kdx_movements.first()
        self.assertTrue(kdx.number.startswith('KDX-'))
        self.assertEqual(kdx.movement_type, StockMovement.MovementType.IN_PURCHASE)
        self.assertEqual(kdx.quantity, Decimal('5.00'))
        self.assertEqual(kdx.balance_after, Decimal('5.00'))
        self.assertEqual(kdx.unit_cost_snapshot, Decimal('20000.00'))
        self.assertEqual(kdx.performed_by, self.ops_coord)

        # 4. Prueba de Idempotencia: Segundo intento de recepción
        response_retry = self.client.post(url, {'supplier_invoice_number': 'FAC-SIN-99121'})
        self.assertEqual(response_retry.status_code, 302)

        # No debe haber alterado el saldo ni creado otro movimiento de Kardex
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, Decimal('5.00'))
        self.assertEqual(StockMovement.objects.filter(item=self.cable_item).count(), 1)

    def test_03_supplier_payment_bimonetary_and_immutability(self):
        """
        Verifica la emisión de comprobantes de egreso bimonetarios (EGR-*) y la inmutabilidad:
        1. Pago parcial en córdobas reduce balance_due y pasa la orden a PARTIAL_PAID.
        2. Pago complementario liquida la orden a PAID con balance_due = 0.00.
        3. Regla de Inmutabilidad: Prohibido modificar o eliminar un SupplierPayment existente.
        """
        po = PurchaseOrder.objects.create(
            organization=self.org,
            number='OC-2026-0003',
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            status=PurchaseOrder.Status.RECEIVED,
            currency_code='NIO',
            currency_symbol='C$',
            exchange_rate=Decimal('36.6243'),
            apply_tax=True,
            tax_rate=Decimal('15.00'),
            ir_withholding_rate=Decimal('1.00'),
            imi_withholding_rate=Decimal('1.00'),
            created_by=self.commercial_mgr,
        )
        PurchaseOrderItem.objects.create(
            organization=self.org,
            purchase_order=po,
            inventory_item=self.cable_item,
            quantity=Decimal('5.00'),
            unit_cost=Decimal('20000.00'),
        )
        po.recalculate_totals()
        po.save()
        self.assertEqual(po.net_payable, Decimal('113000.00'))
        self.assertEqual(po.balance_due, Decimal('113000.00'))

        # Pago 1: Abono Parcial de C$ 50,000.00
        self.client.force_login(self.commercial_mgr)
        pay_url = reverse('purchasing:order_pay', kwargs={'pk': po.pk})
        resp1 = self.client.post(pay_url, {
            'amount': '50000.00',
            'currency_paid': 'NIO',
            'payment_method': SupplierPayment.PaymentMethod.TRANSFER_BAC,
            'reference_number': 'TRF-BAC-889123',
            'notes': 'Abono 1 por transferencia BAC',
        })
        self.assertEqual(resp1.status_code, 302)

        po.refresh_from_db()
        self.assertEqual(po.amount_paid, Decimal('50000.00'))
        self.assertEqual(po.balance_due, Decimal('63000.00'))
        self.assertEqual(po.status, PurchaseOrder.Status.PARTIAL_PAID)

        egr1 = po.payments.first()
        self.assertTrue(egr1.number.startswith('EGR-'))
        self.assertEqual(egr1.amount_applied_to_order, Decimal('50000.00'))

        # Pago 2: Cancelación del Saldo Restante de C$ 63,000.00
        resp2 = self.client.post(pay_url, {
            'amount': '63000.00',
            'currency_paid': 'NIO',
            'payment_method': SupplierPayment.PaymentMethod.TRANSFER_LAFISE,
            'reference_number': 'TRF-LAF-441209',
            'notes': 'Liquidación total del saldo',
        })
        self.assertEqual(resp2.status_code, 302)

        po.refresh_from_db()
        self.assertEqual(po.amount_paid, Decimal('113000.00'))
        self.assertEqual(po.balance_due, Decimal('0.00'))
        self.assertEqual(po.status, PurchaseOrder.Status.PAID)

        # Regla de Inmutabilidad
        egr1.amount_in_payment_currency = Decimal('75000.00')
        with self.assertRaises(ValidationError):
            egr1.save()

        with self.assertRaises(ValidationError):
            egr1.delete()

    def test_04_rbac_authorization_matrix(self):
        """
        Verifica la Matriz de Autorización RBAC en Compras y Cuentas por Pagar (/purchasing/*):
        - COMMERCIAL_MGR (85) & OWNER_ADMIN (100): Control total (ver, emitir, recibir mercadería, pagar CxP).
        - OPERATIONS_COORD (80): Puede ver órdenes, proveedores, e ingresar mercadería en bodega (HTTP 302),
          pero recibe HTTP 403 si intenta registrar pagos a proveedores (RegisterSupplierPaymentView).
        - ENGINEER (50) & TECHNICIAN (20): Bloqueo estricto HTTP 403 en todo el módulo.
        """
        po = PurchaseOrder.objects.create(
            organization=self.org,
            number='OC-2026-0004',
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            status=PurchaseOrder.Status.APPROVED,
            currency_code='NIO',
            created_by=self.commercial_mgr,
        )
        PurchaseOrderItem.objects.create(
            organization=self.org,
            purchase_order=po,
            inventory_item=self.cable_item,
            quantity=Decimal('1.00'),
            unit_cost=Decimal('20000.00'),
        )
        po.recalculate_totals()
        po.save()

        list_url = reverse('purchasing:order_list')
        supplier_url = reverse('purchasing:supplier_list')
        detail_url = reverse('purchasing:order_detail', kwargs={'pk': po.pk})
        receive_url = reverse('purchasing:order_receive', kwargs={'pk': po.pk})
        pay_url = reverse('purchasing:order_pay', kwargs={'pk': po.pk})
        cert_url = reverse('purchasing:retention_certificate_print', kwargs={'pk': po.pk})

        # 1. COMMERCIAL_MGR (85): Control total
        self.client.force_login(self.commercial_mgr)
        self.assertEqual(self.client.get(list_url).status_code, 200)
        self.assertEqual(self.client.get(supplier_url).status_code, 200)
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        self.assertEqual(self.client.get(cert_url).status_code, 200)
        resp_pay_mgr = self.client.post(pay_url, {'amount': '1000.00', 'currency_paid': 'NIO'})
        self.assertEqual(resp_pay_mgr.status_code, 302)

        # 2. OPERATIONS_COORD (80): Lectura y Recepción permitida, Pagos bloqueados (HTTP 403)
        self.client.force_login(self.ops_coord)
        self.assertEqual(self.client.get(list_url).status_code, 200)
        self.assertEqual(self.client.get(supplier_url).status_code, 200)
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        self.assertEqual(self.client.get(cert_url).status_code, 200)

        # Intento de Pago bloqueado con HTTP 403
        resp_pay_coord = self.client.post(pay_url, {'amount': '5000.00', 'currency_paid': 'NIO'})
        self.assertEqual(resp_pay_coord.status_code, 403)

        # Recepción de mercadería permitida
        po.refresh_from_db()
        po.stock_received = False
        po.save()
        resp_rec_coord = self.client.post(receive_url)
        self.assertEqual(resp_rec_coord.status_code, 302)

        # 3. ENGINEER (50) y TECHNICIAN (20): Bloqueo estricto HTTP 403
        for user in [self.engineer, self.technician]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(list_url).status_code, 403)
            self.assertEqual(self.client.get(supplier_url).status_code, 403)
            self.assertEqual(self.client.get(detail_url).status_code, 403)
            self.assertEqual(self.client.get(cert_url).status_code, 403)
            self.assertEqual(self.client.post(receive_url).status_code, 403)
            self.assertEqual(self.client.post(pay_url, {'amount': '100.00'}).status_code, 403)

    def test_05_multi_tenant_isolation(self):
        """
        Verifica el aislamiento multi-tenant estricto:
        Un usuario de la Organización B no puede ver ni modificar datos de proveedores
        u órdenes de compra de la Organización A.
        """
        po = PurchaseOrder.objects.create(
            organization=self.org,
            number='OC-2026-0005',
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            created_by=self.commercial_mgr,
        )

        self.client.force_login(self.other_user)
        detail_url = reverse('purchasing:order_detail', kwargs={'pk': po.pk})
        response = self.client.get(detail_url)
        # Debe responder 404 porque la consulta está acotada con .for_org(request.organization)
        self.assertEqual(response.status_code, 404)

        # Verificación en base de datos
        self.assertEqual(PurchaseOrder.objects.for_org(self.org_other).count(), 0)
        self.assertEqual(Supplier.objects.for_org(self.org_other).count(), 0)

    def test_06_withholding_certificate_print_view(self):
        """
        Verifica la generación y formato de impresión de la Constancia Oficial de Retención (Ley 822):
        El template renderiza datos fiscales de la Organización (Agente Retenedor), Proveedor Retenido,
        número de constancia RET-* y desglose de base e impuestos.
        """
        po = PurchaseOrder.objects.create(
            organization=self.org,
            number='OC-2026-0006',
            supplier=self.supplier,
            target_warehouse=self.warehouse,
            supplier_invoice_number='FAC-SIN-99125',
            status=PurchaseOrder.Status.RECEIVED,
            currency_code='NIO',
            currency_symbol='C$',
            exchange_rate=Decimal('36.6243'),
            apply_tax=True,
            tax_rate=Decimal('15.00'),
            ir_withholding_rate=Decimal('1.00'),
            imi_withholding_rate=Decimal('1.00'),
            created_by=self.commercial_mgr,
        )
        PurchaseOrderItem.objects.create(
            organization=self.org,
            purchase_order=po,
            inventory_item=self.cable_item,
            quantity=Decimal('5.00'),
            unit_cost=Decimal('20000.00'),
        )
        po.recalculate_totals()
        po.save()

        self.client.force_login(self.commercial_mgr)
        cert_url = reverse('purchasing:retention_certificate_print', kwargs={'pk': po.pk})
        response = self.client.get(cert_url)
        self.assertEqual(response.status_code, 200)

        # Verificar presencia de datos clave en el HTML
        content = response.content.decode('utf-8')
        self.assertIn(self.org.tax_id, content)  # RUC del Agente Retenedor
        self.assertIn(self.supplier.tax_id, content)  # RUC del Proveedor
        self.assertIn(po.withholding_certificate_number, content)  # Folio RET-
        self.assertIn('1000.00', content)  # Monto retenido IR e IMI
        self.assertIn('100000.00', content)  # Base imponible
