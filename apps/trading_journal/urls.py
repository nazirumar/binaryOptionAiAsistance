# apps/trading_journal/urls.py
"""Trading-journal API URLs (mounted under ``/api/journal/``)."""

from __future__ import annotations

from django.urls import path

from apps.trading_journal import views

app_name = "trading_journal"

urlpatterns = [
    path("trades/", views.TradeListCreateView.as_view(), name="trade-list"),
    path("trades/<int:pk>/", views.TradeDetailView.as_view(), name="trade-detail"),
    path("performance/", views.PerformanceView.as_view(), name="performance"),
]
