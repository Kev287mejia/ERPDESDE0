from django.urls import path
from . import views

app_name = 'tickets'

urlpatterns = [
    path('', views.TicketListView.as_view(), name='ticket_list'),
    path('create/', views.TicketCreateView.as_view(), name='ticket_create'),
    path('<uuid:pk>/', views.TicketDetailView.as_view(), name='ticket_detail'),
    path('<uuid:pk>/comment/', views.TicketCommentCreateView.as_view(), name='ticket_comment_create'),
    path('<uuid:pk>/resolve/', views.TicketResolveView.as_view(), name='ticket_resolve'),
]
