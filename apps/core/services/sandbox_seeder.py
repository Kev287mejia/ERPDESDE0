"""
Motor Transaccional de Escenario Industrial - Eternal Labs.
Generador e inicializador idempotente de datos operacionales de demostración
para evaluación de producto, diseño y experiencia de usuario (UX).
"""
import datetime
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.core.models import CountryConfig
from apps.crm.models import Account, AccountContact, Opportunity, Quote, QuoteItem
from apps.finance.models import (
    BankAccount,
    FinancialTransaction,
    PettyCashExpense,
    PettyCashFund,
    PettyCashReplenishment,
)
from apps.inventory.models import InventoryItem, StockBalance, StockMovement, Warehouse
from apps.operations.models import (
    Crew,
    WorkOrder,
    WorkOrderEvidence,
    WorkOrderItem,
    WorkOrderTimelineLog,
)
from apps.sst.models import EPPDelivery, LeaveRequest, SafetyChecklist
from apps.tenancy.models import (
    BloodType,
    ContractType,
    Department,
    Organization,
    OrganizationMembership,
    RoleLevel,
)

User = get_user_model()


class SandboxScenarioSeeder:
    """
    Servicio corporativo de poblamiento y limpieza de escenarios industriales para Nicaragua.
    Diseñado para pruebas de producto, evaluación de marketing y auditoría de interfaz.
    """

    @classmethod
    @transaction.atomic
    def reset_organization_data(cls, organization: Organization):
        """
        Elimina de forma limpia y segura todos los registros transaccionales y operativos
        de la organización indicada, preservando únicamente la entidad Organization
        y la membresía Nivel 100 del Owner/Admin actual.
        """
        # 1. Finanzas y Tesorería
        FinancialTransaction.objects.filter(organization=organization).delete()
        PettyCashExpense.objects.filter(organization=organization).delete()
        PettyCashReplenishment.objects.filter(organization=organization).delete()
        PettyCashFund.objects.filter(organization=organization).delete()
        BankAccount.objects.filter(organization=organization).delete()

        # 2. Inventario, Bodegas y Kardex
        StockMovement.objects.filter(organization=organization).delete()
        StockBalance.objects.filter(organization=organization).delete()
        InventoryItem.objects.filter(organization=organization).delete()
        Warehouse.objects.filter(organization=organization).delete()

        # 3. Seguridad y Salud en el Trabajo (SST Ley 618)
        SafetyChecklist.objects.filter(organization=organization).delete()
        EPPDelivery.objects.filter(organization=organization).delete()
        LeaveRequest.objects.filter(organization=organization).delete()

        # 4. Operaciones, Cuadrillas y Órdenes de Trabajo
        WorkOrderEvidence.objects.filter(organization=organization).delete()
        WorkOrderTimelineLog.objects.filter(organization=organization).delete()
        WorkOrderItem.objects.filter(organization=organization).delete()
        WorkOrder.objects.filter(organization=organization).delete()
        Crew.objects.filter(organization=organization).delete()

        # 5. Comercial, Pipeline y Cotizador Bimonetario
        QuoteItem.objects.filter(organization=organization).delete()
        Quote.objects.filter(organization=organization).delete()
        Opportunity.objects.filter(organization=organization).delete()
        AccountContact.objects.filter(organization=organization).delete()
        Account.objects.filter(organization=organization).delete()

        # 6. Miembros subordinados del equipo
        OrganizationMembership.objects.filter(
            organization=organization
        ).exclude(role_level=RoleLevel.OWNER_ADMIN).delete()

    @classmethod
    @transaction.atomic
    def populate_for_organization(cls, organization: Organization, owner_user=None):
        """
        Siembra un escenario operativo industrial completo para Nicaragua en una organización dada.
        La ejecución es estrictamente idempotente.
        """
        # Habilitar los 5 módulos operativos contratados
        all_modules = ['crm', 'operations', 'sst', 'inventory', 'finance']
        organization.enabled_modules = all_modules
        organization.onboarding_completed = True
        organization.save(update_fields=['enabled_modules', 'onboarding_completed'])

        # Limpiar datos previos manteniendo solo el Owner
        cls.reset_organization_data(organization)

        if not owner_user:
            owner_membership = OrganizationMembership.objects.filter(
                organization=organization,
                role_level=RoleLevel.OWNER_ADMIN,
                is_active=True,
            ).first()
            if owner_membership:
                owner_user = owner_membership.user
            else:
                owner_user = User.objects.filter(is_active=True).first()

        # =========================================================================
        # 1. PERSONAL Y CADENA DE MANDO RBAC (apps/tenancy)
        # =========================================================================
        team_specs = [
            {
                'email': 'vjarquin@imesa.ni',
                'full_name': 'Lic. Valentina Jarquín Rivas',
                'personal_id_number': '001-140288-0004Y',
                'phone': '+505 8844-1234',
                'role_level': RoleLevel.COMMERCIAL_MGR,
                'job_title': 'Gerente de Licitaciones & Contratos',
                'department': Department.COMMERCIAL,
                'contract_type': ContractType.PERMANENT,
                'social_security_number': '4589123-1',
                'hire_date': datetime.date(2024, 1, 15),
                'blood_type': BloodType.O_POS,
                'emergency_contact_name': 'Ernesto Jarquín (Padre)',
                'emergency_contact_phone': '+505 8877-2233',
            },
            {
                'email': 'mfonseca@imesa.ni',
                'full_name': 'Ing. Marcos Antonio Fonseca',
                'personal_id_number': '001-220785-0002A',
                'phone': '+505 8455-9876',
                'role_level': RoleLevel.OPERATIONS_COORD,
                'job_title': 'Coordinador General de Operaciones',
                'department': Department.OPERATIONS,
                'contract_type': ContractType.PERMANENT,
                'social_security_number': '3891456-8',
                'hire_date': datetime.date(2023, 6, 1),
                'blood_type': BloodType.A_POS,
                'emergency_contact_name': 'Lucía Fonseca (Esposa)',
                'emergency_contact_phone': '+505 8622-4411',
            },
            {
                'email': 'hgomez@imesa.ni',
                'full_name': 'Lic. Hazel Gómez Blandón',
                'personal_id_number': '081-190490-0003K',
                'phone': '+505 8933-7722',
                'role_level': RoleLevel.SST_OFFICER,
                'job_title': 'Oficial de Seguridad Industrial & Salud MITRAB',
                'department': Department.SST,
                'contract_type': ContractType.PERMANENT,
                'social_security_number': '5123984-4',
                'hire_date': datetime.date(2024, 3, 10),
                'blood_type': BloodType.O_NEG,
                'emergency_contact_name': 'Ramiro Blandón (Hermano)',
                'emergency_contact_phone': '+505 8711-5588',
            },
            {
                'email': 'cchamorro@imesa.ni',
                'full_name': 'Ing. Carlos Eduardo Chamorro',
                'personal_id_number': '001-051189-0006L',
                'phone': '+505 8366-2244',
                'role_level': RoleLevel.ENGINEER,
                'job_title': 'Ingeniero Residente de Subestaciones',
                'department': Department.OPERATIONS,
                'contract_type': ContractType.PERMANENT,
                'social_security_number': '4712039-2',
                'hire_date': datetime.date(2024, 2, 1),
                'blood_type': BloodType.B_POS,
                'emergency_contact_name': 'Silvia Morales (Cónyuge)',
                'emergency_contact_phone': '+505 8833-9900',
            },
            {
                'email': 'jespinoza@imesa.ni',
                'full_name': 'Téc. Josué David Espinoza',
                'personal_id_number': '001-300895-0008F',
                'phone': '+505 8511-3322',
                'role_level': RoleLevel.TECHNICIAN,
                'job_title': 'Técnico Liniero de Alta Tensión',
                'department': Department.OPERATIONS,
                'contract_type': ContractType.PROJECT,
                'social_security_number': '6294810-7',
                'hire_date': datetime.date(2024, 5, 15),
                'blood_type': BloodType.O_POS,
                'emergency_contact_name': 'Marta Espinoza (Madre)',
                'emergency_contact_phone': '+505 8422-7711',
            },
            {
                'email': 'rruiz@auditoria-externa.ni',
                'full_name': 'Aud. Rodolfo Ruiz Mendoza',
                'personal_id_number': '001-180378-0001P',
                'phone': '+505 8922-6633',
                'role_level': RoleLevel.OBSERVER,
                'job_title': 'Auditor Externo de Cumplimiento Financiero & SST',
                'department': Department.MANAGEMENT,
                'contract_type': ContractType.SERVICES,
                'social_security_number': '2109438-5',
                'hire_date': datetime.date(2024, 6, 1),
                'blood_type': BloodType.AB_POS,
                'emergency_contact_name': 'Oficina Central Ruiz & Asociados',
                'emergency_contact_phone': '+505 2270-1122',
            },
        ]

        created_users = {}
        for spec in team_specs:
            user, created = User.objects.get_or_create(
                email=spec['email'],
                defaults={
                    'full_name': spec['full_name'],
                    'personal_id_number': spec['personal_id_number'],
                    'phone': spec['phone'],
                }
            )
            if created or not user.check_password('Eternal2026*'):
                user.set_password('Eternal2026*')
                user.save()

            OrganizationMembership.objects.update_or_create(
                user=user,
                organization=organization,
                defaults={
                    'role_level': spec['role_level'],
                    'job_title': spec['job_title'],
                    'department': spec['department'],
                    'contract_type': spec['contract_type'],
                    'social_security_number': spec['social_security_number'],
                    'hire_date': spec['hire_date'],
                    'blood_type': spec['blood_type'],
                    'emergency_contact_name': spec['emergency_contact_name'],
                    'emergency_contact_phone': spec['emergency_contact_phone'],
                    'is_active': True,
                }
            )
            created_users[spec['role_level']] = user

        commercial_mgr = created_users[RoleLevel.COMMERCIAL_MGR]
        ops_coord = created_users[RoleLevel.OPERATIONS_COORD]
        sst_officer = created_users[RoleLevel.SST_OFFICER]
        resident_eng = created_users[RoleLevel.ENGINEER]
        field_tech = created_users[RoleLevel.TECHNICIAN]

        # =========================================================================
        # 2. DIRECTORIO COMERCIAL, PIPELINE Y COTIZACIONES (apps/crm)
        # =========================================================================
        accounts_data = [
            {
                'code': 'CLI-001',
                'commercial_name': 'ENATREL - Transmisión Eléctrica',
                'legal_name': 'Empresa Nacional de Transmisión Eléctrica',
                'account_type': Account.AccountType.GOVERNMENT,
                'tax_id': 'J0310000000018',
                'email': 'licitaciones@enatrel.gob.ni',
                'phone': '+505 2222-4455',
                'address': 'Rotonda El Güegüense 2c abajo, Managua',
                'city': 'Managua',
                'default_currency': 'NIO',
                'payment_terms_days': 30,
                'contact_name': 'Ing. Fernando Rivas',
                'contact_title': 'Gerente de Subestaciones y Líneas',
            },
            {
                'commercial_name': 'CEMEX Nicaragua S.A.',
                'code': 'CLI-002',
                'legal_name': 'CEMEX de Nicaragua Sociedad Anónima',
                'account_type': Account.AccountType.CORPORATE,
                'tax_id': 'J0310000012459',
                'email': 'adquisiciones@cemex.com',
                'phone': '+505 2269-8000',
                'address': 'Km 35 Carretera a San Rafael del Sur',
                'city': 'San Rafael del Sur',
                'default_currency': 'USD',
                'payment_terms_days': 30,
                'contact_name': 'Ing. Gabriela Somarriba',
                'contact_title': 'Jefa de Mantenimiento de Planta',
            },
            {
                'commercial_name': 'Ingenio San Antonio',
                'code': 'CLI-003',
                'legal_name': 'Nicaragua Sugar Estates Limited',
                'account_type': Account.AccountType.CORPORATE,
                'tax_id': 'J0310000005423',
                'email': 'compras.industriales@nicaraguasugar.com',
                'phone': '+505 2342-9100',
                'address': 'Plantel Industrial Ingenio San Antonio',
                'city': 'Chichigalpa',
                'default_currency': 'USD',
                'payment_terms_days': 15,
                'contact_name': 'Ing. Alejandro Pellas Chamorro',
                'contact_title': 'Director de Operaciones Energéticas',
            },
            {
                'commercial_name': 'Hospital Metropolitano Vivian Pellas',
                'code': 'CLI-004',
                'legal_name': 'Hospital Metropolitano Vivian Pellas S.A.',
                'account_type': Account.AccountType.CORPORATE,
                'tax_id': 'J0310000078129',
                'email': 'ingenieria@metropolitano.com.ni',
                'phone': '+505 2255-6900',
                'address': 'Km 9.8 Carretera a Masaya 250m al este',
                'city': 'Managua',
                'default_currency': 'USD',
                'payment_terms_days': 30,
                'contact_name': 'Lic. Carlos Lacayo',
                'contact_title': 'Director de Infraestructura y Biomédica',
            },
            {
                'commercial_name': 'Holcim Nicaragua S.A.',
                'code': 'CLI-005',
                'legal_name': 'Holcim (Nicaragua) Sociedad Anónima',
                'account_type': Account.AccountType.CORPORATE,
                'tax_id': 'J0310000034901',
                'email': 'compras@holcim.com.ni',
                'phone': '+505 2311-2244',
                'address': 'Km 42 Carretera Nueva a León',
                'city': 'Nagarote',
                'default_currency': 'NIO',
                'payment_terms_days': 45,
                'contact_name': 'Ing. Mauricio Baltodano',
                'contact_title': 'Superintendente Eléctrico',
            },
        ]

        accounts = {}
        for acc_spec in accounts_data:
            contact_name = acc_spec.pop('contact_name')
            contact_title = acc_spec.pop('contact_title')
            acc = Account.objects.create(
                organization=organization,
                lifecycle_stage=Account.LifecycleStage.ACTIVE,
                assigned_to=commercial_mgr,
                **acc_spec
            )
            AccountContact.objects.create(
                organization=organization,
                account=acc,
                full_name=contact_name,
                job_title=contact_title,
                email=acc.email,
                phone=acc.phone,
                is_primary=True,
            )
            accounts[acc.code] = acc

        # Oportunidades en distintas fases del pipeline
        opp_specs = [
            {
                'code': 'OP-2026-0001',
                'account': accounts['CLI-001'],
                'title': 'Modernización de Transformador de Potencia 230kV Subestación Tipitapa',
                'currency': 'USD',
                'estimated_value': Decimal('85000.00'),
                'stage': Opportunity.Stage.NEGOTIATION,
                'expected_close_date': timezone.now().date() + datetime.timedelta(days=20),
            },
            {
                'code': 'OP-2026-0002',
                'account': accounts['CLI-002'],
                'title': 'Mantenimiento Predictivo Termográfico de Tableros Planta San Rafael',
                'currency': 'NIO',
                'estimated_value': Decimal('345000.00'),
                'stage': Opportunity.Stage.PROPOSAL,
                'expected_close_date': timezone.now().date() + datetime.timedelta(days=15),
            },
            {
                'code': 'OP-2026-0003',
                'account': accounts['CLI-003'],
                'title': 'Automatización SCADA de Turbogenerador Zafra 2026',
                'currency': 'USD',
                'estimated_value': Decimal('120000.00'),
                'stage': Opportunity.Stage.QUALIFIED,
                'expected_close_date': timezone.now().date() + datetime.timedelta(days=45),
            },
            {
                'code': 'OP-2026-0004',
                'account': accounts['CLI-004'],
                'title': 'Suministro de Sistema Ininterrumpido UPS Grado Quirófanos',
                'currency': 'USD',
                'estimated_value': Decimal('48000.00'),
                'stage': Opportunity.Stage.WON,
                'expected_close_date': timezone.now().date() - datetime.timedelta(days=5),
            },
            {
                'code': 'OP-2026-0005',
                'account': accounts['CLI-005'],
                'title': 'Instalación de Banco de Capacitores 13.8kV Planta Molinos',
                'currency': 'NIO',
                'estimated_value': Decimal('580000.00'),
                'stage': Opportunity.Stage.WON,
                'expected_close_date': timezone.now().date() - datetime.timedelta(days=10),
            },
            {
                'code': 'OP-2026-0006',
                'account': accounts['CLI-001'],
                'title': 'Inspección de Línea de Transmisión 138kV Corredor Norte',
                'currency': 'NIO',
                'estimated_value': Decimal('420000.00'),
                'stage': Opportunity.Stage.NEW,
                'expected_close_date': timezone.now().date() + datetime.timedelta(days=60),
            },
        ]

        opportunities = []
        for opp in opp_specs:
            o = Opportunity.objects.create(
                organization=organization,
                assigned_to=commercial_mgr,
                **opp
            )
            opportunities.append(o)

        # Cotizaciones Bimonetarias con Desglose de Partidas e IVA 15%
        # 1. COT-2026-0001 (USD - Aprobada - Hospital Vivian Pellas)
        q1 = Quote.objects.create(
            organization=organization,
            number='COT-2026-0001',
            account=accounts['CLI-004'],
            opportunity=opportunities[3],
            title='Suministro e Instalación de Sistema UPS Grado Quirófano 40kVA',
            status=Quote.Status.APPROVED,
            currency_code='USD',
            currency_symbol='$',
            exchange_rate=Decimal('36.6243'),
            tax_rate=Decimal('15.00'),
            apply_tax=True,
            valid_until=timezone.now().date() + datetime.timedelta(days=30),
            created_by=commercial_mgr,
        )
        QuoteItem.objects.create(
            organization=organization,
            quote=q1,
            item_type=QuoteItem.ItemType.SERVICE,
            code='SRV-ING-01',
            description='Montaje, conexionado de fuerza y puesta en marcha de UPS modular',
            unit='GLB',
            quantity=Decimal('1.00'),
            unit_price=Decimal('8500.00'),
        )
        QuoteItem.objects.create(
            organization=organization,
            quote=q1,
            item_type=QuoteItem.ItemType.MATERIAL,
            code='MAT-BAT-01',
            description='Banco de baterías selladas AGM de alta descarga 12V 100Ah',
            unit='UND',
            quantity=Decimal('32.00'),
            unit_price=Decimal('350.00'),
        )
        QuoteItem.objects.create(
            organization=organization,
            quote=q1,
            item_type=QuoteItem.ItemType.SERVICE,
            code='SRV-PRU-02',
            description='Pruebas de conmutación en carga y certificación de onda senoidal',
            unit='GLB',
            quantity=Decimal('1.00'),
            unit_price=Decimal('2500.00'),
        )

        # 2. COT-2026-0002 (NIO - Aprobada - Holcim Nicaragua)
        q2 = Quote.objects.create(
            organization=organization,
            number='COT-2026-0002',
            account=accounts['CLI-005'],
            opportunity=opportunities[4],
            title='Suministro y Montaje de Banco de Capacitores Automático 13.8kV',
            status=Quote.Status.APPROVED,
            currency_code='NIO',
            currency_symbol='C$',
            exchange_rate=Decimal('36.6243'),
            tax_rate=Decimal('15.00'),
            apply_tax=True,
            valid_until=timezone.now().date() + datetime.timedelta(days=25),
            created_by=commercial_mgr,
        )
        QuoteItem.objects.create(
            organization=organization,
            quote=q2,
            item_type=QuoteItem.ItemType.MATERIAL,
            code='MAT-CAP-01',
            description='Celdas capacitivas trifásicas de media tensión 300 kVAR 13.8kV',
            unit='UND',
            quantity=Decimal('4.00'),
            unit_price=Decimal('85000.00'),
        )
        QuoteItem.objects.create(
            organization=organization,
            quote=q2,
            item_type=QuoteItem.ItemType.SERVICE,
            code='SRV-EST-01',
            description='Fabricación de estructura metálica galvanizada y barras colectoras',
            unit='GLB',
            quantity=Decimal('1.00'),
            unit_price=Decimal('65000.00'),
        )
        QuoteItem.objects.create(
            organization=organization,
            quote=q2,
            item_type=QuoteItem.ItemType.SERVICE,
            code='SRV-IZA-01',
            description='Maniobra de izaje con grúa y conexión en celda de media tensión',
            unit='HRS',
            quantity=Decimal('2.00'),
            unit_price=Decimal('42000.00'),
        )

        # 3. COT-2026-0003 (USD - Enviada - CEMEX)
        q3 = Quote.objects.create(
            organization=organization,
            number='COT-2026-0003',
            account=accounts['CLI-002'],
            opportunity=opportunities[1],
            title='Servicio de Termografía Infrarroja y Análisis de Calidad de Energía',
            status=Quote.Status.SENT,
            currency_code='USD',
            currency_symbol='$',
            exchange_rate=Decimal('36.6243'),
            tax_rate=Decimal('15.00'),
            apply_tax=True,
            valid_until=timezone.now().date() + datetime.timedelta(days=15),
            created_by=commercial_mgr,
        )
        QuoteItem.objects.create(
            organization=organization,
            quote=q3,
            item_type=QuoteItem.ItemType.SERVICE,
            code='SRV-TER-01',
            description='Inspección termográfica FLIR en 48 CCMs de planta y transformadores',
            unit='GLB',
            quantity=Decimal('1.00'),
            unit_price=Decimal('4800.00'),
        )
        QuoteItem.objects.create(
            organization=organization,
            quote=q3,
            item_type=QuoteItem.ItemType.SERVICE,
            code='SRV-ARM-01',
            description='Monitoreo de armónicos y factor de potencia con analizador Fluke',
            unit='JRN',
            quantity=Decimal('3.00'),
            unit_price=Decimal('1200.00'),
        )

        # 4. COT-2026-0004 (NIO - Borrador - ENATREL)
        q4 = Quote.objects.create(
            organization=organization,
            number='COT-2026-0004',
            account=accounts['CLI-001'],
            opportunity=opportunities[0],
            title='Reemplazo de Aisladores de Porcelana en Pórtico 138kV Subestación León',
            status=Quote.Status.DRAFT,
            currency_code='NIO',
            currency_symbol='C$',
            exchange_rate=Decimal('36.6243'),
            tax_rate=Decimal('15.00'),
            apply_tax=True,
            valid_until=timezone.now().date() + datetime.timedelta(days=30),
            created_by=commercial_mgr,
        )
        QuoteItem.objects.create(
            organization=organization,
            quote=q4,
            item_type=QuoteItem.ItemType.MATERIAL,
            code='MAT-AIS-01',
            description='Cadena de aisladores poliméricos tipo suspensión 138kV ANSI 52-3',
            unit='UND',
            quantity=Decimal('18.00'),
            unit_price=Decimal('8200.00'),
        )
        QuoteItem.objects.create(
            organization=organization,
            quote=q4,
            item_type=QuoteItem.ItemType.SERVICE,
            code='SRV-LIN-01',
            description='Cuadrilla técnica liniera especializada con camión canasta aislada',
            unit='HRS',
            quantity=Decimal('40.00'),
            unit_price=Decimal('2100.00'),
        )

        # =========================================================================
        # 3. OPERACIONES, CUADRILLAS Y ÓRDENES DE TRABAJO (apps/operations)
        # =========================================================================
        crew1 = Crew.objects.create(
            organization=organization,
            code='BRIG-01',
            name='Cuadrilla Alfa · Alta Tensión & Subestaciones',
            specialty='Media y Alta Tensión, Subestaciones 138/230kV',
            leader=field_tech,
            vehicle_plate='M 312-890',
            vehicle_description='Toyota Hilux 4x4 Doble Cabina 2024 con Winche',
            is_active=True,
        )
        crew2 = Crew.objects.create(
            organization=organization,
            code='BRIG-02',
            name='Cuadrilla Beta · Mantenimiento Electromecánico Industrial',
            specialty='Mantenimiento de Motores, Transformadores y Tableros',
            leader=resident_eng,
            vehicle_plate='M 298-114',
            vehicle_description='Isuzu D-Max 4x4 2023 con Caja de Herramientas Aislada',
            is_active=True,
        )
        crew3 = Crew.objects.create(
            organization=organization,
            code='BRIG-03',
            name='Cuadrilla Gamma · Servicios de Emergencia & Calidad Eléctrica',
            specialty='Termografía, Calidad de Energía y Análisis de Vibraciones',
            leader=ops_coord,
            vehicle_plate='M 345-671',
            vehicle_description='Ford Ranger 4x4 2023 con Laboratorio Móvil',
            is_active=True,
        )

        # Órdenes de Trabajo en distintas fases
        # OT-1: En Ejecución (desde COT-2026-0001 Vivian Pellas)
        wo1 = WorkOrder.objects.create(
            organization=organization,
            number='OT-2026-0001',
            account=accounts['CLI-004'],
            source_quote=q1,
            title='Instalación y Pruebas en Vacío Sistema UPS Quirófano Central',
            technical_scope='Montaje mecánico de gabinete UPS, conexión de barraje DC y banco de 32 baterías AGM.',
            site_address='Hospital Vivian Pellas, Módulo Quirúrgico Torre B, Sótano Eléctrico',
            priority=WorkOrder.Priority.CRITICAL,
            phase=WorkOrder.Phase.IN_PROGRESS,
            is_high_risk=True,
            sst_cleared=True,
            assigned_engineer=resident_eng,
            assigned_crew=crew2,
            scheduled_start=timezone.now().date() - datetime.timedelta(days=2),
            scheduled_end=timezone.now().date() + datetime.timedelta(days=3),
            created_by=ops_coord,
        )
        WorkOrderItem.objects.create(
            organization=organization,
            work_order=wo1,
            item_type=WorkOrderItem.ItemType.SERVICE,
            code='SRV-ING-01',
            description='Montaje mecánico y anclaje antisísmico de módulo UPS',
            unit='GLB',
            planned_quantity=Decimal('1.00'),
            executed_quantity=Decimal('1.00'),
            is_completed=True,
        )
        WorkOrderItem.objects.create(
            organization=organization,
            work_order=wo1,
            item_type=WorkOrderItem.ItemType.MATERIAL,
            code='MAT-BAT-01',
            description='Instalación de banco de baterías selladas 12V 100Ah',
            unit='UND',
            planned_quantity=Decimal('32.00'),
            executed_quantity=Decimal('32.00'),
            is_completed=True,
        )
        WorkOrderItem.objects.create(
            organization=organization,
            work_order=wo1,
            item_type=WorkOrderItem.ItemType.SERVICE,
            code='SRV-PRU-02',
            description='Pruebas de transferencia y descarga con banco resistivo',
            unit='GLB',
            planned_quantity=Decimal('1.00'),
            executed_quantity=Decimal('0.50'),
            is_completed=False,
        )
        WorkOrderTimelineLog.objects.create(
            organization=organization,
            work_order=wo1,
            event_type='CREATED',
            summary='Orden de trabajo generada desde cotización aprobada COT-2026-0001',
            details='Asignación inicial a Cuadrilla Beta liderada por Ing. Carlos Chamorro.',
            actor=ops_coord,
        )
        WorkOrderTimelineLog.objects.create(
            organization=organization,
            work_order=wo1,
            event_type='SST_CLEARANCE',
            summary='Aval técnico emitido por Oficial SST Ley 618 MITRAB',
            details='Checklist CHK-2026-0001 aprobado sin observaciones.',
            actor=sst_officer,
        )
        WorkOrderEvidence.objects.create(
            organization=organization,
            work_order=wo1,
            evidence_type=WorkOrderEvidence.EvidenceType.PHOTO_PROGRESS,
            title='Conexión de terminales de potencia en gabinete de baterías',
            notes='Torque verificado según especificación de fabricante a 12 Nm.',
            file_reference='evidencias/ot_001_baterias.jpg',
            uploaded_by=resident_eng,
        )

        # OT-2: Borrador (desde COT-2026-0002 Holcim)
        wo2 = WorkOrder.objects.create(
            organization=organization,
            number='OT-2026-0002',
            account=accounts['CLI-005'],
            source_quote=q2,
            title='Obras Civiles y Anclaje de Banco de Capacitores 13.8kV',
            technical_scope='Fundación de losa de concreto, anclaje de celdas capacitivas e interconexión.',
            site_address='Holcim Planta Nagarote, Celda de Molienda #03',
            priority=WorkOrder.Priority.HIGH,
            phase=WorkOrder.Phase.DRAFT,
            is_high_risk=True,
            sst_cleared=False,
            assigned_engineer=resident_eng,
            assigned_crew=crew1,
            scheduled_start=timezone.now().date() + datetime.timedelta(days=5),
            scheduled_end=timezone.now().date() + datetime.timedelta(days=12),
            created_by=ops_coord,
        )

        # OT-3: Bloqueada por SST (ENATREL)
        wo3 = WorkOrder.objects.create(
            organization=organization,
            number='OT-2026-0003',
            account=accounts['CLI-001'],
            title='Maniobra de Mantenimiento en Seccionadores de Línea 138kV',
            technical_scope='Desconexión y apertura de cuchillas, limpieza criogénica y ajuste de contactos.',
            site_address='Subestación Tipitapa 230/138kV, Bahía de Línea Masaya',
            priority=WorkOrder.Priority.CRITICAL,
            phase=WorkOrder.Phase.SCHEDULED,
            is_high_risk=True,
            sst_cleared=False,
            assigned_engineer=resident_eng,
            assigned_crew=crew1,
            scheduled_start=timezone.now().date() + datetime.timedelta(days=2),
            scheduled_end=timezone.now().date() + datetime.timedelta(days=4),
            created_by=ops_coord,
        )
        WorkOrderTimelineLog.objects.create(
            organization=organization,
            work_order=wo3,
            event_type='SST_LOCK',
            summary='Frente de obra retenido: falta validación de permiso LOTO en seccionador',
            details='Oficial SST detectó que la línea paralela no cuenta con puesta a tierra temporal.',
            actor=sst_officer,
        )

        # OT-4: Finalizada (CEMEX)
        wo4 = WorkOrder.objects.create(
            organization=organization,
            number='OT-2026-0004',
            account=accounts['CLI-002'],
            title='Inspección Termográfica y Corrección de Puntos Calientes en CCM Molino #2',
            technical_scope='Termografía con cámara FLIR T540, reapriete con torquímetro aislado y entrega de informe.',
            site_address='CEMEX Planta San Rafael del Sur, Sala Eléctrica #4',
            priority=WorkOrder.Priority.NORMAL,
            phase=WorkOrder.Phase.COMPLETED,
            is_high_risk=False,
            sst_cleared=True,
            assigned_engineer=ops_coord,
            assigned_crew=crew3,
            scheduled_start=timezone.now().date() - datetime.timedelta(days=8),
            scheduled_end=timezone.now().date() - datetime.timedelta(days=6),
            completed_at=timezone.now() - datetime.timedelta(days=6),
            created_by=ops_coord,
        )
        WorkOrderTimelineLog.objects.create(
            organization=organization,
            work_order=wo4,
            event_type='COMPLETED',
            summary='Obra finalizada y entregada a satisfacción de la jefatura de planta CEMEX',
            details='Informe técnico firmado por Ing. Gabriela Somarriba.',
            actor=ops_coord,
        )

        # =========================================================================
        # 4. SEGURIDAD LABORAL LEY 618 MITRAB (apps/sst)
        # =========================================================================
        chk1 = SafetyChecklist.objects.create(
            organization=organization,
            number='CHK-2026-0001',
            work_order=wo1,
            crew=crew2,
            submitted_by=resident_eng,
            work_type=SafetyChecklist.WorkType.ELECTRICAL,
            epp_verified=True,
            loto_verified=True,
            tools_inspected=True,
            area_signaled=True,
            risk_briefing_done=True,
            hazard_notes='Riesgo de arco eléctrico mitigado con traje de protección Arc Flash 40 cal/cm2.',
            status=SafetyChecklist.Status.APPROVED,
            reviewed_by=sst_officer,
            reviewed_at=timezone.now() - datetime.timedelta(days=2),
            review_comments='Checklist verificado conforme a Ley 618. Labor autorizada.',
        )

        chk2 = SafetyChecklist.objects.create(
            organization=organization,
            number='CHK-2026-0002',
            work_order=wo3,
            crew=crew1,
            submitted_by=field_tech,
            work_type=SafetyChecklist.WorkType.HEIGHTS,
            epp_verified=True,
            loto_verified=False,
            tools_inspected=True,
            area_signaled=True,
            risk_briefing_done=True,
            hazard_notes='Pendiente confirmación de consignación formal de línea por despacho de carga.',
            status=SafetyChecklist.Status.PENDING,
            reviewed_by=None,
        )

        # Dotaciones de EPP
        EPPDelivery.objects.create(
            organization=organization,
            code='EPP-2026-0001',
            collaborator=field_tech,
            category=EPPDelivery.Category.HEAD,
            item_name='Casco Dieléctrico Tipo II Clase E 20kV MSA V-Gard',
            serial_or_batch='LOT-MSA-2026-01',
            quantity=1,
            delivery_date=timezone.now().date() - datetime.timedelta(days=30),
            expiration_date=timezone.now().date() + datetime.timedelta(days=335),
            status=EPPDelivery.Status.ACTIVE,
            acknowledged_by_worker=True,
            delivered_by=sst_officer,
        )
        EPPDelivery.objects.create(
            organization=organization,
            code='EPP-2026-0002',
            collaborator=field_tech,
            category=EPPDelivery.Category.HANDS,
            item_name='Guantes Dieléctricos de Alta Tensión Salisbury Clase 2 17kV',
            serial_or_batch='LOT-SAL-8891',
            quantity=1,
            delivery_date=timezone.now().date() - datetime.timedelta(days=30),
            expiration_date=timezone.now().date() + datetime.timedelta(days=150),
            status=EPPDelivery.Status.ACTIVE,
            acknowledged_by_worker=True,
            delivered_by=sst_officer,
        )
        EPPDelivery.objects.create(
            organization=organization,
            code='EPP-2026-0003',
            collaborator=resident_eng,
            category=EPPDelivery.Category.FALL,
            item_name='Arnés de Cuerpo Completo Miller Titan con Doble Eslinga Dieléctrica',
            serial_or_batch='LOT-MIL-9421',
            quantity=1,
            delivery_date=timezone.now().date() - datetime.timedelta(days=45),
            expiration_date=timezone.now().date() + datetime.timedelta(days=320),
            status=EPPDelivery.Status.ACTIVE,
            acknowledged_by_worker=True,
            delivered_by=sst_officer,
        )

        # Solicitudes de Permiso / Reposo Laboral
        LeaveRequest.objects.create(
            organization=organization,
            number='PER-2026-0001',
            requester=field_tech,
            requester_role_level=RoleLevel.TECHNICIAN,
            leave_type=LeaveRequest.LeaveType.MEDICAL,
            start_date=timezone.now().date() - datetime.timedelta(days=12),
            end_date=timezone.now().date() - datetime.timedelta(days=10),
            days_requested=3,
            reason='Constancia de reposo médico por lumbago emitida por Policlínico Central INSS.',
            status=LeaveRequest.Status.APPROVED,
            reviewed_by=ops_coord,
            reviewed_at=timezone.now() - datetime.timedelta(days=12),
            resolution_notes='Subsidio INSS justificado. Reingreso con aptitud médica confirmada.',
        )
        LeaveRequest.objects.create(
            organization=organization,
            number='PER-2026-0002',
            requester=resident_eng,
            requester_role_level=RoleLevel.ENGINEER,
            leave_type=LeaveRequest.LeaveType.TRAINING,
            start_date=timezone.now().date() + datetime.timedelta(days=15),
            end_date=timezone.now().date() + datetime.timedelta(days=16),
            days_requested=2,
            reason='Certificación Oficial NFPA 70E sobre Seguridad Eléctrica en Lugares de Trabajo.',
            status=LeaveRequest.Status.APPROVED,
            reviewed_by=owner_user,
            reviewed_at=timezone.now() - datetime.timedelta(days=1),
            resolution_notes='Capacitación estratégica autorizada para el frente de subestaciones.',
        )

        # =========================================================================
        # 5. ALMACÉN, BODEGAS Y KARDEX (apps/inventory)
        # =========================================================================
        bod1 = Warehouse.objects.create(
            organization=organization,
            code='BOD-01',
            name='Bodega Central Managua (Km 7.5 Carretera Norte)',
            warehouse_type=Warehouse.WarehouseType.CENTRAL,
            address='Parque Industrial Las Mercedes, Módulo 4',
            is_active=True,
        )
        bod2 = Warehouse.objects.create(
            organization=organization,
            code='BOD-02',
            name='Unidad Móvil Hilux #04 (Cuadrilla Alfa)',
            warehouse_type=Warehouse.WarehouseType.MOBILE_CREW,
            linked_crew=crew1,
            address='Móvil asignado a brigada de alta tensión',
            is_active=True,
        )
        bod3 = Warehouse.objects.create(
            organization=organization,
            code='BOD-03',
            name='Frente de Obra Subestación Tipitapa',
            warehouse_type=Warehouse.WarehouseType.PROJECT,
            address='Subestación Tipitapa ENATREL',
            is_active=True,
        )

        items_data = [
            {
                'sku': 'MAT-CAB-01',
                'name': 'Cable de Cobre THHN Calibre 4 AWG 600V Negro',
                'category': InventoryItem.Category.ELECTRICAL,
                'unit': 'MTS',
                'min_stock_level': Decimal('100.00'),
                'unit_cost': Decimal('85.00'),
            },
            {
                'sku': 'MAT-CAB-02',
                'name': 'Cable de Potencia XLP 15kV Calibre 2/0 AWG Apantallado',
                'category': InventoryItem.Category.ELECTRICAL,
                'unit': 'MTS',
                'min_stock_level': Decimal('50.00'),
                'unit_cost': Decimal('420.00'),
            },
            {
                'sku': 'MAT-AIS-01',
                'name': 'Aislador Polimérico tipo Suspensión 138kV ANSI 52-3',
                'category': InventoryItem.Category.ELECTRICAL,
                'unit': 'UND',
                'min_stock_level': Decimal('12.00'),
                'unit_cost': Decimal('3850.00'),
            },
            {
                'sku': 'MAT-TER-01',
                'name': 'Terminal Termocontráctil para Media Tensión 15kV Exterior 3M',
                'category': InventoryItem.Category.ELECTRICAL,
                'unit': 'JGO',
                'min_stock_level': Decimal('8.00'),
                'unit_cost': Decimal('2450.00'),
            },
            {
                'sku': 'HER-MUL-01',
                'name': 'Multímetro Digital Industrial True-RMS Fluke 87V Calibrado',
                'category': InventoryItem.Category.TOOL,
                'unit': 'UND',
                'min_stock_level': Decimal('2.00'),
                'unit_cost': Decimal('18900.00'),
            },
            {
                'sku': 'SEG-CAS-01',
                'name': 'Casco Dieléctrico con Barboquejo Clase E 20kV MSA V-Gard',
                'category': InventoryItem.Category.SAFETY_EPP,
                'unit': 'UND',
                'min_stock_level': Decimal('10.00'),
                'unit_cost': Decimal('750.00'),
            },
            {
                'sku': 'SEG-GUA-01',
                'name': 'Guantes Dieléctricos de Alta Tensión Clase 2 17kV Salisbury',
                'category': InventoryItem.Category.SAFETY_EPP,
                'unit': 'PAR',
                'min_stock_level': Decimal('6.00'),
                'unit_cost': Decimal('4200.00'),
            },
            {
                'sku': 'MAT-CON-01',
                'name': 'Cinta Autofundente de Goma Alta Tensión 3M Scotch 23',
                'category': InventoryItem.Category.CONSUMABLE,
                'unit': 'RLL',
                'min_stock_level': Decimal('20.00'),
                'unit_cost': Decimal('380.00'),
            },
        ]

        items = {}
        for item_spec in items_data:
            item = InventoryItem.objects.create(
                organization=organization,
                is_active=True,
                **item_spec
            )
            items[item.sku] = item

        # Saldos Físicos de Stock en Bodega Central y Móvil
        StockBalance.objects.create(
            organization=organization,
            warehouse=bod1,
            item=items['MAT-CAB-01'],
            quantity=Decimal('450.00'),
        )
        StockBalance.objects.create(
            organization=organization,
            warehouse=bod1,
            item=items['MAT-CAB-02'],
            quantity=Decimal('180.00'),
        )
        StockBalance.objects.create(
            organization=organization,
            warehouse=bod1,
            item=items['MAT-AIS-01'],
            quantity=Decimal('24.00'),
        )
        StockBalance.objects.create(
            organization=organization,
            warehouse=bod1,
            item=items['HER-MUL-01'],
            quantity=Decimal('4.00'),
        )
        StockBalance.objects.create(
            organization=organization,
            warehouse=bod2,
            item=items['MAT-CON-01'],
            quantity=Decimal('15.00'),
        )
        StockBalance.objects.create(
            organization=organization,
            warehouse=bod2,
            item=items['SEG-GUA-01'],
            quantity=Decimal('4.00'),
        )
        StockBalance.objects.create(
            organization=organization,
            warehouse=bod3,
            item=items['MAT-TER-01'],
            quantity=Decimal('6.00'),
        )
        StockBalance.objects.create(
            organization=organization,
            warehouse=bod1,
            item=items['SEG-CAS-01'],
            quantity=Decimal('10.00'),
        )

        # Movimientos de Kardex
        StockMovement.objects.create(
            organization=organization,
            number='KDX-2026-0001',
            movement_type=StockMovement.MovementType.IN_PURCHASE,
            warehouse=bod1,
            item=items['MAT-CAB-01'],
            quantity=Decimal('500.00'),
            unit_cost_snapshot=Decimal('85.00'),
            balance_after=Decimal('500.00'),
            reference_note='Recepción de lote según Factura Comercial Ferretería Roberto Morales #4891',
            performed_by=ops_coord,
        )
        StockMovement.objects.create(
            organization=organization,
            number='KDX-2026-0002',
            movement_type=StockMovement.MovementType.TRANSFER_OUT,
            warehouse=bod1,
            target_warehouse=bod2,
            item=items['MAT-CON-01'],
            quantity=Decimal('15.00'),
            unit_cost_snapshot=Decimal('380.00'),
            balance_after=Decimal('35.00'),
            reference_note='Dotación inicial de consumibles a Unidad Móvil Hilux #04',
            performed_by=ops_coord,
        )
        StockMovement.objects.create(
            organization=organization,
            number='KDX-2026-0003',
            movement_type=StockMovement.MovementType.OUT_WORKORDER,
            warehouse=bod1,
            item=items['MAT-CAB-01'],
            quantity=Decimal('50.00'),
            unit_cost_snapshot=Decimal('85.00'),
            balance_after=Decimal('450.00'),
            work_order=wo1,
            reference_note='Despacho de cable de fuerza para interconexión de tablero UPS',
            performed_by=resident_eng,
        )
        StockMovement.objects.create(
            organization=organization,
            number='KDX-2026-0004',
            movement_type=StockMovement.MovementType.OUT_WORKORDER,
            warehouse=bod3,
            item=items['MAT-TER-01'],
            quantity=Decimal('2.00'),
            unit_cost_snapshot=Decimal('2450.00'),
            balance_after=Decimal('6.00'),
            work_order=wo3,
            reference_note='Imputación de terminales termocontráctiles al transformador de potencia T-01',
            performed_by=resident_eng,
        )

        # =========================================================================
        # 6. TESORERÍA, CAJAS CHICAS Y BANCOS (apps/finance)
        # =========================================================================
        bank_nio = BankAccount.objects.create(
            organization=organization,
            bank_name=BankAccount.BankName.BAC,
            account_number='001-348921-04',
            currency='NIO',
            account_type=BankAccount.AccountType.CHECKING,
            current_balance=Decimal('485250.00'),
            description='Cuenta Principal de Operaciones y Nómina - BAC Credomatic',
        )
        bank_usd = BankAccount.objects.create(
            organization=organization,
            bank_name=BankAccount.BankName.BANPRO,
            account_number='100-204589-12',
            currency='USD',
            account_type=BankAccount.AccountType.CHECKING,
            current_balance=Decimal('34800.00'),
            description='Cuenta Corporativa en Dólares para Suministros Importados - Banpro',
        )

        petty_fund = PettyCashFund.objects.create(
            organization=organization,
            code='CAJ-01',
            name='Caja Chica Frentes de Obra Managua & Tipitapa',
            custodian=resident_eng,
            linked_crew=crew1,
            currency='NIO',
            allocated_amount=Decimal('25000.00'),
            current_balance=Decimal('16850.00'),
        )

        # Asiento inicial de asignación de fondo fijo
        FinancialTransaction.objects.create(
            organization=organization,
            transaction_type=FinancialTransaction.TransactionType.PETTY_CASH_ALLOCATION,
            bank_account=bank_nio,
            petty_cash_fund=petty_fund,
            amount=Decimal('25000.00'),
            balance_after=petty_fund.current_balance,
            concept='Apertura y dotación de fondo fijo para Ing. Carlos Chamorro',
            reference_code='CHQ-BAC-4812',
            performed_by=owner_user,
        )
        FinancialTransaction.objects.create(
            organization=organization,
            transaction_type=FinancialTransaction.TransactionType.CLIENT_COLLECTION,
            bank_account=bank_nio,
            amount=Decimal('185000.00'),
            balance_after=bank_nio.current_balance,
            concept='Cobro anticipo 30% Licitación ENATREL según Factura #0129',
            reference_code='TRANSF-ACH-98214',
            performed_by=commercial_mgr,
        )
        FinancialTransaction.objects.create(
            organization=organization,
            transaction_type=FinancialTransaction.TransactionType.PETTY_CASH_REPLENISH,
            bank_account=bank_nio,
            petty_cash_fund=petty_fund,
            amount=Decimal('8150.00'),
            balance_after=petty_fund.allocated_amount,
            concept='Desembolso por reposición y liquidación de arqueo REP-2026-0001',
            reference_code='DEB-BAC-7741',
            performed_by=owner_user,
        )

        # Comprobantes de Gastos de Campo
        exp1 = PettyCashExpense.objects.create(
            organization=organization,
            voucher_number='REC-2026-0001',
            fund=petty_fund,
            work_order=wo1,
            expense_category=PettyCashExpense.Category.FUEL,
            vendor_name='Estación Puma Energy Tipitapa',
            vendor_tax_id='J0310000041289',
            invoice_number='FAC-89124',
            amount=Decimal('3450.00'),
            description='Abastecimiento de Diesel 85 galones para vehículo Hilux M 312-890 frente Tipitapa',
            spent_at=timezone.now().date() - datetime.timedelta(days=2),
            created_by=resident_eng,
            is_replenished=False,
        )
        exp2 = PettyCashExpense.objects.create(
            organization=organization,
            voucher_number='REC-2026-0002',
            fund=petty_fund,
            work_order=wo1,
            expense_category=PettyCashExpense.Category.EMERGENCY_HARDWARE,
            vendor_name='Ferretería Richardson S.A.',
            vendor_tax_id='J0310000011456',
            invoice_number='FAC-12498',
            amount=Decimal('2800.00'),
            description='Compra de pernos de anclaje de acero inoxidable y brocas SDS para concreto',
            spent_at=timezone.now().date() - datetime.timedelta(days=1),
            created_by=resident_eng,
            is_replenished=False,
        )
        exp3 = PettyCashExpense.objects.create(
            organization=organization,
            voucher_number='REC-2026-0003',
            fund=petty_fund,
            work_order=wo1,
            expense_category=PettyCashExpense.Category.PER_DIEM,
            vendor_name='Restaurante El Cortijo Tipitapa',
            vendor_tax_id='001-150682-0003N',
            invoice_number='FAC-4412',
            amount=Decimal('1900.00'),
            description='Alimentación y viáticos para cuadrilla de 6 técnicos en maniobra nocturna',
            spent_at=timezone.now().date() - datetime.timedelta(days=1),
            created_by=resident_eng,
            is_replenished=False,
        )

        # Solicitud de Reposición (Arqueo de Caja)
        rep = PettyCashReplenishment.objects.create(
            organization=organization,
            code='REP-2026-0001',
            fund=petty_fund,
            status=PettyCashReplenishment.Status.APPROVED,
            total_expenses_amount=Decimal('8150.00'),
            requested_amount=Decimal('8150.00'),
            notes='Arqueo quincenal verificado. Comprobantes fiscales válidos adjuntos.',
            submitted_by=resident_eng,
            approved_by=ops_coord,
            approved_at=timezone.now() - datetime.timedelta(hours=4),
        )

        return {
            'organization': organization,
            'members_count': 7,
            'accounts_count': 5,
            'quotes_count': 4,
            'crews_count': 3,
            'work_orders_count': 4,
            'checklists_count': 2,
            'warehouses_count': 3,
            'inventory_items_count': 8,
            'bank_accounts_count': 2,
            'petty_cash_funds_count': 1,
            'expenses_count': 3,
        }
