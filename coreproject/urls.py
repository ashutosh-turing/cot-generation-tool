from django.contrib import admin
from django.urls import path
from django.urls import include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('eval.urls')),
    path('processor/', include('processor.urls')),
    path('accounts/', include('allauth.urls')),  # django-allauth URLs
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
