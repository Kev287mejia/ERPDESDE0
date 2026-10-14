from decimal import Decimal
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import TemplateView

from apps.tenancy.models import RoleLevel
from apps.tenancy.permissions import ModuleAccessRequiredMixin, render_403_rbac
from apps.operations.models import WorkOrder
from apps.inventory.models import Warehouse, InventoryItem, StockBalance, StockMovement
from apps.inventory.forms import (
    WarehouseForm,
    InventoryItemForm,
    StockEntryForm,
    StockTransferForm,
    StockDispatchForm,
)
from apps.inventory.services import (
    record_stock_entry,
    transfer_stock_between_warehouses,
    dispatch_stock_to_work_order,
)


class InventoryDashboardView(ModuleAccessRequiredMixin, TemplateView):
    """
    Consola Integral de Inventarios, Bodegas Físicas, Furgonetas Móviles y Kardex.
    Accesible a partir de Nivel ENGINEER (50).
    Confidencialidad Financiera:
    - Ingenieros (50) y Oficiales SST (70): Ven cantidades físicas y ubicaciones, cero costos unitarios.
    - Coordinadores (80) y Owners (100): Acceso a valorización total y costos unitarios promedios.
    """
    template_name = 'inventory/dashboard.html'
    required_module = 'inventory'
    min_role_level = RoleLevel.ENGINEER

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        org = self.request.organization
        role_level = getattr(self.request, 'role_level', 0)
        can_view_financials = role_level >= RoleLevel.OPERATIONS_COORD

        warehouses = list(Warehouse.objects.for_org(org).select_related('linked_crew'))
        items = list(InventoryItem.objects.for_org(org).prefetch_related('balances', 'balances__warehouse'))
        movements = list(
            StockMovement.objects.for_org(org)
            .select_related('warehouse', 'target_warehouse', 'item', 'work_order', 'performed_by')
            [:60]
        )

        low_stock_count = sum(1 for item in items if item.is_low_stock())
        total_valuation = sum(item.total_stock() * item.unit_cost for item in items)

        # Mapeo de existencias por ítem para display rápido
        item_rows = []
        for it in items:
            total_qty = it.total_stock()
            balances_dict = {b.warehouse_id: b.quantity for b in it.balances.all()}
            item_rows.append({
                'item': it,
                'total_qty': total_qty,
                'is_low_stock': total_qty <= it.min_stock_level,
                'balances_dict': balances_dict,
            })

        context.update({
            'warehouses': warehouses,
            'items': items,
            'item_rows': item_rows,
            'movements': movements,
            'low_stock_count': low_stock_count,
            'total_valuation': total_valuation,
            'can_view_financials': can_view_financials,
            'can_manage_inventory': role_level >= RoleLevel.OPERATIONS_COORD,
            'warehouse_form': WarehouseForm(organization=org),
            'item_form': InventoryItemForm(),
            'entry_form': StockEntryForm(organization=org),
            'transfer_form': StockTransferForm(organization=org),
            'dispatch_form': StockDispatchForm(organization=org),
        })
        return context


class WarehouseCreateView(ModuleAccessRequiredMixin, View):
    """
    Alta de Bodega Física o Unidad Móvil de Cuadrilla.
    Exige min_role_level = RoleLevel.OPERATIONS_COORD (80).
    """
    required_module = 'inventory'
    min_role_level = RoleLevel.OPERATIONS_COORD

    @transaction.atomic
    def post(self, request):
        org = request.organization
        form = WarehouseForm(request.POST, organization=org)

        if form.is_valid():
            wh = form.save(commit=False)
            wh.organization = org
            wh.save()
            messages.success(request, f"Bodega {wh.code} ({wh.name}) registrada exitosamente.")
        else:
            messages.error(request, "Error al registrar bodega. Verifique los datos ingresados.")

        return redirect('inventory:dashboard')


class InventoryItemCreateView(ModuleAccessRequiredMixin, View):
    """
    Alta de Material, Insumo o Herramienta en el Catálogo Maestro.
    Exige min_role_level = RoleLevel.OPERATIONS_COORD (80).
    """
    required_module = 'inventory'
    min_role_level = RoleLevel.OPERATIONS_COORD

    @transaction.atomic
    def post(self, request):
        org = request.organization
        form = InventoryItemForm(request.POST)

        if form.is_valid():
            item = form.save(commit=False)
            item.organization = org
            item.save()
            messages.success(request, f"Ítem {item.sku} ({item.name}) registrado en el catálogo maestro.")
        else:
            messages.error(request, "Error al registrar ítem de inventario. Verifique el SKU y campos obligatorios.")

        return redirect('inventory:dashboard')


class StockEntryCreateView(ModuleAccessRequiredMixin, View):
    """
    Recepción / Entrada de Materiales a Bodega por Compra o Ajuste.
    Exige min_role_level = RoleLevel.OPERATIONS_COORD (80).
    """
    required_module = 'inventory'
    min_role_level = RoleLevel.OPERATIONS_COORD

    def post(self, request):
        org = request.organization
        form = StockEntryForm(request.POST, organization=org)

        if form.is_valid():
            warehouse = form.cleaned_data['warehouse']
            item = form.cleaned_data['item']
            quantity = form.cleaned_data['quantity']
            unit_cost = form.cleaned_data['unit_cost']
            reference_note = form.cleaned_data['reference_note']

            try:
                mov = record_stock_entry(
                    organization=org,
                    warehouse=warehouse,
                    item=item,
                    quantity=quantity,
                    unit_cost=unit_cost,
                    reference_note=reference_note,
                    user=request.user,
                )
                messages.success(
                    request,
                    f"Entrada registrada: Folio {mov.number}. +{quantity} {item.unit} ingresados a {warehouse.name}."
                )
            except ValidationError as e:
                messages.error(request, f"Error de validación: {e.message if hasattr(e, 'message') else str(e)}")
        else:
            messages.error(request, "Error en los datos de entrada a bodega. Verifique los campos.")

        return redirect('inventory:dashboard')


class StockTransferCreateView(ModuleAccessRequiredMixin, View):
    """
    Traslado entre Bodegas o Carga a Furgoneta Móvil de Cuadrilla.
    Exige min_role_level = RoleLevel.OPERATIONS_COORD (80).
    """
    required_module = 'inventory'
    min_role_level = RoleLevel.OPERATIONS_COORD

    def post(self, request):
        org = request.organization
        form = StockTransferForm(request.POST, organization=org)

        if form.is_valid():
            source_wh = form.cleaned_data['source_warehouse']
            target_wh = form.cleaned_data['target_warehouse']
            item = form.cleaned_data['item']
            quantity = form.cleaned_data['quantity']
            reference_note = form.cleaned_data['reference_note']

            try:
                mov_out, mov_in = transfer_stock_between_warehouses(
                    organization=org,
                    source_warehouse=source_wh,
                    target_warehouse=target_wh,
                    item=item,
                    quantity=quantity,
                    reference_note=reference_note,
                    user=request.user,
                )
                messages.success(
                    request,
                    f"Traslado completado ({mov_out.number} & {mov_in.number}): "
                    f"{quantity} {item.unit} trasladados de {source_wh.name} a {target_wh.name}."
                )
            except ValidationError as e:
                messages.error(request, f"Error en traslado: {e.message if hasattr(e, 'message') else str(e)}")
        else:
            messages.error(request, "Error en datos del traslado. Verifique que las bodegas y cantidad sean válidas.")

        return redirect('inventory:dashboard')


class StockDispatchToOTView(ModuleAccessRequiredMixin, View):
    """
    Despacho de Materiales desde Bodega o Unidad Móvil directamente a una Orden de Trabajo (OT).
    Accesible para Ingenieros (50) y Coordinadores (80+).
    Segregación de funciones: Bloquea con HTTP 403 al Oficial SST (70).
    """
    required_module = 'inventory'
    min_role_level = RoleLevel.ENGINEER

    def post(self, request):
        org = request.organization
        role_level = getattr(request, 'role_level', 0)

        # Regla de segregación de funciones: el Oficial SST supervisa seguridad pero no despacha materiales
        if role_level == RoleLevel.SST_OFFICER:
            return render_403_rbac(
                request,
                required_module='inventory',
                min_role_level=RoleLevel.ENGINEER,
                reason="Segregación de funciones: El Oficial SST no está facultado para realizar despachos o consumos de materiales hacia OTs."
            )

        form = StockDispatchForm(request.POST, organization=org)

        if form.is_valid():
            warehouse = form.cleaned_data['warehouse']
            work_order = form.cleaned_data['work_order']
            item = form.cleaned_data['item']
            quantity = form.cleaned_data['quantity']

            try:
                mov = dispatch_stock_to_work_order(
                    organization=org,
                    warehouse=warehouse,
                    item=item,
                    work_order=work_order,
                    quantity=quantity,
                    user=request.user,
                )
                messages.success(
                    request,
                    f"Despacho a OT completado ({mov.number}): "
                    f"{quantity} {item.unit} de {item.name} despachados a {work_order.number} desde {warehouse.name}."
                )
            except ValidationError as e:
                messages.error(request, f"Error en despacho a OT: {e.message if hasattr(e, 'message') else str(e)}")
        else:
            messages.error(request, "Error en datos del despacho. Verifique la bodega, OT y cantidad.")

        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
        return redirect('inventory:dashboard')
