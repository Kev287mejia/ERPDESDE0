from django.urls import path
from apps.finance import views

app_name = 'finance'

urlpatterns = [
    # Consola Principal de Tesorería, Cajas Chicas y Bancos
    path('', views.FinanceDashboardView.as_view(), name='dashboard'),

    # Cuentas Bancarias
    path('bank-accounts/create/', views.BankAccountCreateView.as_view(), name='bank_account_create'),

    # Cajas Chicas y Fondos Fijos
    path('funds/create/', views.PettyCashFundCreateView.as_view(), name='fund_create'),
    path('funds/<uuid:pk>/', views.PettyCashFundDetailView.as_view(), name='fund_detail'),

    # Operaciones de Gastos y Desembolsos
    path('expenses/create/', views.PettyCashExpenseCreateView.as_view(), name='expense_create'),
    path('replenishments/submit/', views.PettyCashReplenishSubmitView.as_view(), name='replenish_submit'),
    path('replenishments/disburse/', views.PettyCashDisburseView.as_view(), name='replenish_disburse'),
]
