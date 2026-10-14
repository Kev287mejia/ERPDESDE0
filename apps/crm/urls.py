from django.urls import path
from apps.crm import views

app_name = 'crm'

urlpatterns = [
    # Directorio de Cuentas / Clientes
    path('accounts/', views.AccountListView.as_view(), name='account_list'),
    path('accounts/create/', views.AccountCreateView.as_view(), name='account_create'),
    path('accounts/<uuid:pk>/', views.AccountDetailView.as_view(), name='account_detail'),
    path('accounts/<uuid:pk>/contacts/create/', views.AccountContactCreateView.as_view(), name='account_contact_create'),

    # Pipeline Kanban de Oportunidades
    path('pipeline/', views.OpportunityKanbanView.as_view(), name='opportunity_kanban'),
    path('pipeline/create/', views.OpportunityCreateView.as_view(), name='opportunity_create'),
    path('pipeline/<uuid:pk>/stage/', views.OpportunityStageUpdateView.as_view(), name='opportunity_stage_update'),

    # Cotizador Bimonetario
    path('quotes/', views.QuoteListView.as_view(), name='quote_list'),
    path('quotes/create/', views.QuoteCreateView.as_view(), name='quote_create'),
    path('quotes/<uuid:pk>/', views.QuoteDetailView.as_view(), name='quote_detail'),
    path('quotes/<uuid:pk>/items/add/', views.QuoteAddItemView.as_view(), name='quote_add_item'),
    path('quotes/<uuid:quote_pk>/items/<uuid:item_pk>/delete/', views.QuoteRemoveItemView.as_view(), name='quote_remove_item'),
    path('quotes/<uuid:pk>/transition/', views.QuoteStatusTransitionView.as_view(), name='quote_status_transition'),
    path('quotes/<uuid:pk>/print/', views.QuotePrintView.as_view(), name='quote_print'),
]
