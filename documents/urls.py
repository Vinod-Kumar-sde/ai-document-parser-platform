from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# API Router
router = DefaultRouter()
router.register(r'documents', views.DocumentViewSet, basename='document')
router.register(r'processing-jobs', views.ProcessingJobViewSet, basename='processingjob')

app_name = 'documents'

from django.shortcuts import redirect

def redirect_to_login(request):
    """Redirect unauthenticated users to admin login"""
    if request.user.is_authenticated:
        return views.dashboard(request)
    else:
        return redirect('admin:login')

urlpatterns = [
    # API URLs
    path('api/', include(router.urls)),
    path('api/documents/<uuid:document_id>/status/', views.document_status, name='document_status_api'),
    path('api/health/', views.health_check, name='health_check'),
    
    # Web Interface URLs
    path('', redirect_to_login, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('documents/', views.document_list, name='document_list'),
    path('documents/<uuid:document_id>/', views.document_detail, name='document_detail'),
    path('upload/', views.upload_document, name='upload_document'),
]
