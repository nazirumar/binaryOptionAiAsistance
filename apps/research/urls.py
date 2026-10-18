# apps/research/urls.py
from __future__ import annotations

from django.urls import path

from apps.research import views

app_name = "research"

urlpatterns = [
    path("backtests/", views.BacktestListView.as_view(), name="backtest-list"),
    path("backtests/<int:pk>/", views.BacktestDetailView.as_view(), name="backtest-detail"),
    path("performance/", views.PerformanceView.as_view(), name="performance"),
    path("calibration/", views.CalibrationView.as_view(), name="calibration"),
    path("models/", views.ModelRegistryView.as_view(), name="models"),
]
