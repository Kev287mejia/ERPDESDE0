from django.urls import path
from apps.core import views_alerts_agenda

urlpatterns = [
    # Radar de Alertas Proactivas Multi-Giro
    path('alerts-radar/', views_alerts_agenda.AlertsRadarCenterView.as_view(), name='alerts_radar'),
    path('alerts-radar/dropdown/', views_alerts_agenda.TopbarAlertsDropdownPartialView.as_view(), name='alerts_dropdown_partial'),

    # Agenda Corporativa & Calendario Fiscal DGI/Alcaldía/INSS
    path('agenda/', views_alerts_agenda.CorporateAgendaView.as_view(), name='corporate_agenda'),
    path('agenda/create/', views_alerts_agenda.CorporateEventCreateView.as_view(), name='corporate_event_create'),
    path('agenda/<uuid:pk>/status/', views_alerts_agenda.CorporateEventStatusUpdateView.as_view(), name='corporate_event_status_update'),
    path('agenda/generate-fiscal-calendar/', views_alerts_agenda.GenerateFiscalCalendarView.as_view(), name='generate_fiscal_calendar'),
]
