from django.urls import path
from apps.sst import views

app_name = 'sst'

urlpatterns = [
    # Dashboard SST, Checklists y Control de EPP
    path('', views.SSTDashboardAndChecklistsView.as_view(), name='index'),
    path('checklists/', views.SSTDashboardAndChecklistsView.as_view(), name='checklists_and_epp'),
    path('checklists/create/', views.SafetyChecklistCreateView.as_view(), name='checklist_create'),
    path('checklists/<uuid:pk>/review/', views.SafetyChecklistReviewView.as_view(), name='checklist_review'),

    # Asignación y Recepción de EPP
    path('epp/create/', views.EPPDeliveryCreateView.as_view(), name='epp_create'),
    path('epp/<uuid:pk>/acknowledge/', views.EPPAcknowledgeView.as_view(), name='epp_acknowledge'),

    # Flujo de Permisos Laborales y Reposos
    path('leaves/', views.LeaveRequestListView.as_view(), name='leave_list'),
    path('leaves/create/', views.LeaveRequestCreateView.as_view(), name='leave_create'),
    path('leaves/<uuid:pk>/review/', views.LeaveRequestReviewView.as_view(), name='leave_review'),
]
