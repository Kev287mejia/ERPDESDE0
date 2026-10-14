from django.urls import path
from apps.operations import views

app_name = 'operations'

urlpatterns = [
    # Listado Maestro / Mis Tareas de Hoy
    path('', views.WorkOrderListView.as_view(), name='workorder_list_root'),
    path('orders/', views.WorkOrderListView.as_view(), name='workorder_list'),
    path('orders/create/', views.WorkOrderCreateView.as_view(), name='workorder_create'),
    path('orders/<uuid:pk>/', views.WorkOrderDetailView.as_view(), name='workorder_detail'),

    # Acciones y Transiciones en la OT
    path('orders/<uuid:pk>/phase/', views.WorkOrderPhaseTransitionView.as_view(), name='workorder_phase_transition'),
    path('orders/<uuid:pk>/sst-clearance/', views.WorkOrderSSTClearanceView.as_view(), name='workorder_sst_clearance'),
    path('orders/<uuid:pk>/items/add/', views.WorkOrderAddItemView.as_view(), name='workorder_add_item'),
    path('orders/<uuid:wo_pk>/items/<uuid:item_pk>/execute/', views.WorkOrderItemExecuteView.as_view(), name='workorder_item_execute'),
    path('orders/<uuid:pk>/evidences/add/', views.WorkOrderEvidenceCreateView.as_view(), name='workorder_evidence_create'),
    path('orders/<uuid:pk>/evidence/add/', views.WorkOrderEvidenceCreateView.as_view(), name='workorder_evidence_add'),

    # Conversión en 1 Clic desde Cotización Aprobada
    path('from-quote/<uuid:quote_pk>/', views.ConvertQuoteToWorkOrderView.as_view(), name='convert_quote'),
    path('from-quote/<uuid:quote_pk>/convert/', views.ConvertQuoteToWorkOrderView.as_view(), name='convert_from_quote'),

    # Firma Digital Táctil, Acta de Entrega y Sincronización Offline PWA
    path('orders/<uuid:pk>/sign/', views.WorkOrderSignCaptureView.as_view(), name='workorder_sign'),
    path('orders/<uuid:pk>/certificate/', views.WorkOrderCertificatePrintView.as_view(), name='workorder_certificate_print'),
    path('orders/<uuid:pk>/print/', views.WorkOrderCertificatePrintView.as_view(), name='workorder_print_alias'),
    path('workorders/<uuid:pk>/print/', views.WorkOrderCertificatePrintView.as_view(), name='workorder_print'),
    path('field-sync/', views.FieldOfflineSyncEndpointView.as_view(), name='field_offline_sync'),

    # Planeación de Cuadrillas y Vehículos
    path('crews/', views.CrewPlanningMatrixView.as_view(), name='crew_planning'),
    path('crews/create/', views.CrewCreateView.as_view(), name='crew_create'),
]
