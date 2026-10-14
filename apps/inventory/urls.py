from django.urls import path
from apps.inventory import views

app_name = 'inventory'

urlpatterns = [
    # Dashboard Maestro de Inventarios, Bodegas y Kardex
    path('', views.InventoryDashboardView.as_view(), name='dashboard'),

    # Altas de Bodegas y Catálogo Maestro
    path('warehouses/create/', views.WarehouseCreateView.as_view(), name='warehouse_create'),
    path('items/create/', views.InventoryItemCreateView.as_view(), name='item_create'),

    # Operaciones Transaccionales de Kardex
    path('movements/entry/', views.StockEntryCreateView.as_view(), name='movement_entry'),
    path('movements/entry/action/', views.StockEntryCreateView.as_view(), name='stock_entry'),
    path('movements/transfer/', views.StockTransferCreateView.as_view(), name='movement_transfer'),
    path('movements/transfer/action/', views.StockTransferCreateView.as_view(), name='stock_transfer'),
    path('movements/dispatch-ot/', views.StockDispatchToOTView.as_view(), name='movement_dispatch_ot'),
    path('movements/dispatch-ot/action/', views.StockDispatchToOTView.as_view(), name='stock_dispatch_ot'),
]
