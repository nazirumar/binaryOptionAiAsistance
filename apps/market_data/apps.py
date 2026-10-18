"""Market data application: MetaTrader 5 live/historical market data."""

from __future__ import annotations

from django.apps import AppConfig


class MarketDataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.market_data"
    label = "market_data"
    verbose_name = "Market Data"
