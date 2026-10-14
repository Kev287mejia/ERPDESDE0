from django.urls import path
from apps.accounts_auth import views

app_name = 'accounts_auth'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('register/', views.CorporateRegisterView.as_view(), name='register'),
    path('logout/', views.logout_view, name='logout'),
]
