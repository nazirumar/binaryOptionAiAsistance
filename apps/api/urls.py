"""API URL configuration (namespaced under ``/api/``)."""

from __future__ import annotations

from django.urls import path

from apps.api import views

app_name = "api"

urlpatterns = [
    path("health/", views.HealthAPIView.as_view(), name="health"),
    path("me/", views.MeView.as_view(), name="me"),
]
