# live_signals/admin.py
"""Admin registration for the live-signals monitor.

Signals are read-only: a detected signal is frozen at detection time and its
outcome may only be written by the monitor service. ``decision_use_approved``
(NOT exposed here) stays the single approval switch on ``BookStrategy``.
"""

from django.contrib import admin

from apps.live_signals.models import (
    InstrumentMonitor,
    LiveSignal,
    SignalAlert,
    UserMonitorSettings,
)


@admin.register(InstrumentMonitor)
class InstrumentMonitorAdmin(admin.ModelAdmin):
    list_display = (
        "canonical_instrument",
        "timeframe",
        "market_type",
        "feed_state",
        "state",
        "enabled",
        "last_evaluated_candle_open_time",
        "signals_detected",
    )
    list_filter = ("enabled", "feed_state", "state", "market_type", "timeframe")
    search_fields = ("canonical_instrument", "broker_symbol")
    readonly_fields = (
        "last_evaluated_candle_open_time",
        "last_successful_candle_update",
        "last_run_at",
        "last_error",
        "consecutive_failures",
        "signals_detected",
        "created_at",
        "updated_at",
    )


@admin.register(LiveSignal)
class LiveSignalAdmin(admin.ModelAdmin):
    list_display = (
        "strategy_key",
        "instrument",
        "timeframe",
        "category",
        "status",
        "direction",
        "outcome_status",
        "detected_at",
    )
    list_filter = ("category", "status", "direction", "outcome_status", "timeframe")
    search_fields = ("strategy_key", "instrument")
    date_hierarchy = "detected_at"

    def has_add_permission(self, request):
        # Signals are detected by the monitor - never hand-added.
        return False

    # The model freezes provenance and only permits outcome writes through
    # record_outcome(); the admin mirrors that by showing everything read-only.
    readonly_fields = [f.name for f in LiveSignal._meta.fields]


@admin.register(SignalAlert)
class SignalAlertAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "read_at", "delivered_browser", "created_at")
    list_filter = ("delivered_browser", "read_at")
    search_fields = ("user__username", "title")


@admin.register(UserMonitorSettings)
class UserMonitorSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "alerts_enabled",
        "browser_notifications",
        "show_experimental",
        "only_approved",
    )
    list_filter = ("alerts_enabled", "only_approved", "show_experimental")
    search_fields = ("user__username",)
