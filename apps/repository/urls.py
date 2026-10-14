from django.urls import path
from . import views

app_name = 'repository'

urlpatterns = [
    path('', views.RepositoryBrowserView.as_view(), name='browser'),
    path('folders/create/', views.RepositoryFolderCreateView.as_view(), name='folder_create'),
    path('documents/create/', views.CorporateDocumentCreateView.as_view(), name='document_create'),
    path('documents/<uuid:pk>/', views.CorporateDocumentDetailView.as_view(), name='document_detail'),
    path('documents/<uuid:pk>/new-version/', views.CorporateDocumentNewVersionView.as_view(), name='document_new_version'),
    path('documents/<uuid:pk>/toggle-lock/', views.CorporateDocumentToggleLockView.as_view(), name='document_toggle_lock'),
]
