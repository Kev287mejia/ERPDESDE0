from django.urls import path
from apps.payroll import views

app_name = 'payroll'

urlpatterns = [
    # Consola Ejecutiva y Directorio de Nómina (Exclusivo RoleLevel >= 85)
    path('', views.PayrollDashboardView.as_view(), name='dashboard'),
    path('contracts/create/', views.EmployeeContractCreateView.as_view(), name='contract_create'),
    path('periods/create/', views.PayrollPeriodCreateView.as_view(), name='period_create'),
    path('periods/<uuid:pk>/', views.PayrollPeriodDetailView.as_view(), name='period_detail'),
    path('periods/<uuid:pk>/recalculate/', views.PayrollPeriodRecalculateView.as_view(), name='period_recalculate'),
    path('periods/<uuid:pk>/close/', views.PayrollPeriodCloseView.as_view(), name='period_close'),

    # Autoservicio de Colillas de Pago (RoleLevel >= 20)
    path('my-payslips/', views.MyPayslipsSelfServiceView.as_view(), name='my_payslips'),
    path('payslips/<uuid:pk>/print/', views.PayslipPrintView.as_view(), name='payslip_print'),
]
