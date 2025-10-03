"""
URL configuration for AI Document Processor project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required

def redirect_to_dashboard(request):
    """Redirect root URL to dashboard"""
    if request.user.is_authenticated:
        return redirect('documents:dashboard')
    else:
        return redirect('admin:login')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('documents.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Admin site customization
admin.site.site_header = "AI Document Processor Admin"
admin.site.site_title = "AI Document Processor"
admin.site.index_title = "Welcome to AI Document Processor Administration"
