"""Application configuration for market synchronization."""

from __future__ import annotations

from django.apps import AppConfig


class MarketSyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.market_sync"
    verbose_name = "Market synchronization"
