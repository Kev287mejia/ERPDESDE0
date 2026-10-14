from django.urls import path
from apps.billing import views

app_name = 'billing'

urlpatterns = [
    # Directorio de Facturas y Cartera
    path('', views.InvoiceListView.as_view(), name='invoice_list'),
    path('invoices/<uuid:pk>/', views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/<uuid:pk>/print/', views.InvoicePrintView.as_view(), name='invoice_print'),

    # Conversión en 1 Clic
    path('from-quote/<uuid:quote_pk>/', views.ConvertQuoteToInvoiceView.as_view(), name='from_quote'),
    path('from-workorder/<uuid:wo_pk>/', views.ConvertWorkOrderToInvoiceView.as_view(), name='from_workorder'),

    # Operaciones de Retenciones, Caja y Anulación
    path('invoices/<uuid:pk>/apply-retentions/', views.InvoiceApplyRetentionsView.as_view(), name='apply_retentions'),
    path('invoices/<uuid:pk>/register-payment/', views.InvoiceRegisterPaymentView.as_view(), name='register_payment'),
    path('invoices/<uuid:pk>/void/', views.InvoiceVoidView.as_view(), name='invoice_void'),
]
