# apps/trading_journal/apps.py
from __future__ import annotations

from django.apps import AppConfig


class TradingJournalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.trading_journal"
    label = "trading_journal"
    verbose_name = "Trading Journal"
