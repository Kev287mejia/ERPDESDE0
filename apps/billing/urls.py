from django.urls import path
from apps.billing import views
from apps.billing import views_vet_dgi

app_name = 'billing'

urlpatterns = [
    # Terminal de Punto de Venta Rápido de Mostrador (POS)
    path('pos/', views.PointOfSaleTerminalView.as_view(), name='pos_terminal'),
    path('pos/shifts/', views.PosShiftConsoleView.as_view(), name='pos_shifts'),
    path('pos/shifts/<str:pk>/print-z/', views.PosShiftZReportPrintView.as_view(), name='pos_shift_print_z'),

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

    # Arqueo de Caja Z Bimonetario (Corte Z con Sello Criptográfico SHA-256)
    path('cash-sessions/', views.CashSessionListView.as_view(), name='cash_session_list'),
    path('cash-sessions/open/', views.CashSessionOpenView.as_view(), name='cash_session_open'),
    path('cash-sessions/<uuid:pk>/close/', views.CashSessionCloseView.as_view(), name='cash_session_close'),
    path('cash-sessions/<uuid:pk>/print/', views.CashSessionPrintView.as_view(), name='cash_session_print'),

    # Centro Tributario VET-DGI Nicaragua & Exportador CSV
    path('vet-dgi/', views_vet_dgi.VETDGITaxCenterView.as_view(), name='vet_dgi_center'),
    path('vet-dgi/export/<str:report_type>/', views_vet_dgi.VETDGIExportCSVView.as_view(), name='vet_dgi_export_csv'),
    path('vet-dgi/sync-ledger/', views_vet_dgi.VETDGISyncLedgerView.as_view(), name='vet_dgi_sync_ledger'),
]

