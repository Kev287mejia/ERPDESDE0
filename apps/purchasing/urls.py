from django.urls import path
from apps.purchasing import views

app_name = 'purchasing'

urlpatterns = [
    # Monitor de Órdenes de Compra y Cuentas por Pagar (CxP)
    path('', views.PurchaseOrderListView.as_view(), name='order_list'),
    path('orders/create/', views.PurchaseOrderCreateView.as_view(), name='order_create'),
    path('orders/<uuid:pk>/', views.PurchaseOrderDetailView.as_view(), name='order_detail'),
    path('orders/<uuid:pk>/add-item/', views.PurchaseOrderAddItemView.as_view(), name='order_add_item'),
    path('orders/<uuid:pk>/receive/', views.ReceivePurchaseOrderView.as_view(), name='order_receive'),
    path('orders/<uuid:pk>/pay/', views.RegisterSupplierPaymentView.as_view(), name='order_pay'),
    path('orders/<uuid:pk>/retention-certificate/', views.WithholdingCertificatePrintView.as_view(), name='retention_certificate_print'),

    # Directorio de Proveedores
    path('suppliers/', views.SupplierListView.as_view(), name='supplier_list'),
]
