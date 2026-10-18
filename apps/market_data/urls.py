"""Market data API URLs (mounted under ``/api/market/``)."""

from __future__ import annotations

from django.urls import path

from apps.market_data import views

app_name = "market_data"

urlpatterns = [
    path("health/", views.MarketHealthAPIView.as_view(), name="health"),
    path("symbols/", views.MarketSymbolListAPIView.as_view(), name="symbols"),
    path("candles/", views.MarketCandleListAPIView.as_view(), name="candles"),
    path("tick/", views.MarketTickAPIView.as_view(), name="tick"),
    path("connection/", views.MarketConnectionAPIView.as_view(), name="connection"),
    path("sync/", views.SyncTriggerAPIView.as_view(), name="sync"),
    path("ingest/candles/", views.IngestCandlesAPIView.as_view(), name="ingest-candles"),
    path("ingest/ticks/", views.IngestTicksAPIView.as_view(), name="ingest-ticks"),
    path("worker/heartbeat/", views.WorkerHeartbeatAPIView.as_view(), name="worker-heartbeat"),
]
