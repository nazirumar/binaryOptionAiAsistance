# apps/dashboard/api_urls.py
"""Dashboard API URL configuration (mounted under ``/api/dashboard/``)."""

from __future__ import annotations

from django.urls import path

from apps.dashboard import api_views

app_name = "dashboard_api"

urlpatterns = [
    path("overview/", api_views.OverviewAPIView.as_view(), name="overview"),
    path("analytics/", api_views.AnalyticsAPIView.as_view(), name="analytics"),
    path("market-health/", api_views.MarketHealthAPIView.as_view(), name="market-health"),
    path("reports/", api_views.ReportsAPIView.as_view(), name="reports"),
]
