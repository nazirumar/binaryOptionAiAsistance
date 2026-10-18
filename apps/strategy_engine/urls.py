# apps/strategy_engine/urls.py
"""Strategy engine API URLs."""

from __future__ import annotations

from django.urls import path

from apps.strategy_engine import views

app_name = "strategy_engine"

urlpatterns = [
    path("evaluate/", views.EvaluateAPIView.as_view(), name="evaluate"),
    path(
        "evaluations/<int:pk>/", views.EvaluationDetailAPIView.as_view(), name="evaluation-detail"
    ),
    path("history/", views.EvaluationHistoryAPIView.as_view(), name="history"),
    path("rules/", views.StrategyRulesAPIView.as_view(), name="rules"),
]
