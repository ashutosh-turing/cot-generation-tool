# processor/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('upload/', views.upload_csv, name='upload_csv'),
    path('logs/', views.get_logs, name='get_logs'),
]