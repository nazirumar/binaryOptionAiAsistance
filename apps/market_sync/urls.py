"""Market-synchronization API URLs (mounted under ``/api/sync/``)."""

from __future__ import annotations

from django.urls import path

from apps.market_sync import views

app_name = "market_sync"

urlpatterns = [
    path("verify/", views.SyncVerifyAPIView.as_view(), name="verify"),
    path("results/<int:pk>/", views.SyncResultAPIView.as_view(), name="result"),
    path("history/", views.SyncHistoryAPIView.as_view(), name="history"),
    path("health/", views.SyncHealthAPIView.as_view(), name="health"),
]
