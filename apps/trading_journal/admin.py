# apps/trading_journal/admin.py
"""Admin registration for the trading journal."""

from __future__ import annotations

from django.contrib import admin

from apps.trading_journal.models import JournalTrade


@admin.register(JournalTrade)
class JournalTradeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "owner",
        "instrument",
        "direction",
        "trade_type",
        "result",
        "stake",
        "profit_loss",
        "entry_timestamp",
    )
    list_filter = ("trade_type", "result", "direction", "strategy_family")
    search_fields = ("instrument", "notes", "owner__username")
    date_hierarchy = "entry_timestamp"
