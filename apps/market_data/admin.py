"""Django admin for market data models."""

from __future__ import annotations

from django.contrib import admin

from apps.market_data.models import (
    MarketCandle,
    MarketDataHealthEvent,
    MarketDataSyncLog,
    MarketSymbol,
    MarketTick,
    MT5ConnectionProfile,
    WorkerHeartbeat,
)


@admin.register(MT5ConnectionProfile)
class MT5ConnectionProfileAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "broker",
        "server",
        "masked_login",
        "is_active",
        "is_default",
        "state",
    )
    list_filter = ("is_active", "is_default", "state")
    search_fields = ("name", "broker", "server", "terminal_path")
    readonly_fields = ("created_at", "updated_at", "last_connected_at")
    # ``credential_ref`` names a secret; the secret itself is never stored here.
    exclude = ()


@admin.register(MarketSymbol)
class MarketSymbolAdmin(admin.ModelAdmin):
    list_display = (
        "canonical",
        "broker_symbol",
        "profile",
        "category",
        "is_otc",
        "is_active",
        "mapping_status",
    )
    list_filter = ("category", "is_otc", "is_active", "mapping_status")
    search_fields = ("canonical", "broker_symbol", "description")
    readonly_fields = ("created_at", "updated_at", "last_validated_at")


@admin.register(MarketCandle)
class MarketCandleAdmin(admin.ModelAdmin):
    list_display = (
        "symbol",
        "timeframe",
        "open_time",
        "close",
        "tick_volume",
        "is_complete",
        "quality_status",
    )
    list_filter = ("timeframe", "is_complete", "quality_status", "source")
    search_fields = ("symbol__canonical", "symbol__broker_symbol")
    date_hierarchy = "open_time"
    readonly_fields = ("created_at", "updated_at", "collected_at")


@admin.register(MarketTick)
class MarketTickAdmin(admin.ModelAdmin):
    list_display = ("symbol", "time", "bid", "ask", "last", "volume", "source")
    list_filter = ("source",)
    search_fields = ("symbol__canonical", "symbol__broker_symbol")
    date_hierarchy = "time"
    readonly_fields = ("created_at", "updated_at", "collected_at")


@admin.register(MarketDataSyncLog)
class MarketDataSyncLogAdmin(admin.ModelAdmin):
    list_display = (
        "kind",
        "status",
        "symbol",
        "timeframe",
        "started_at",
        "finished_at",
        "rows_inserted",
    )
    list_filter = ("kind", "status", "timeframe")
    search_fields = ("collector", "error_message")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MarketDataHealthEvent)
class MarketDataHealthEventAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "kind", "severity", "message", "symbol", "collector")
    list_filter = ("kind", "severity")
    search_fields = ("message", "collector")
    readonly_fields = ("created_at", "updated_at")


@admin.register(WorkerHeartbeat)
class WorkerHeartbeatAdmin(admin.ModelAdmin):
    list_display = ("worker_id", "status", "last_seen")
    list_filter = ("status",)
    search_fields = ("worker_id",)
    readonly_fields = ("created_at", "updated_at")
