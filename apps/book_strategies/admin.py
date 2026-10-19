"""Admin registration for book strategies.

``decision_use_approved`` is intentionally NOT exposed as a casual checkbox:
approval requires documented validation and explicit user authorization, so it
is only settable through a deliberate change here (never by seed/imports).
"""

from django.contrib import admin

from apps.book_strategies.models import (
    BookStrategy,
    BookStrategyDetection,
    PaperForwardPrediction,
)


@admin.register(BookStrategy)
class BookStrategyAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "number",
        "name",
        "chapter",
        "research_status",
        "recognition_enabled",
        "decision_use_approved",
    )
    list_filter = ("research_status", "recognition_enabled", "decision_use_approved")
    search_fields = ("key", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(BookStrategyDetection)
class BookStrategyDetectionAdmin(admin.ModelAdmin):
    list_display = ("strategy", "state", "direction", "data_verification", "decision", "created_at")
    list_filter = ("state", "decision")
    search_fields = ("strategy__key",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(PaperForwardPrediction)
class PaperForwardPredictionAdmin(admin.ModelAdmin):
    """Read-mostly view: prediction fields are immutable in the model itself."""

    list_display = (
        "strategy",
        "direction",
        "signal_candle_open_time",
        "status",
        "outcome_correct",
        "settlement_status",
        "created_at",
    )
    list_filter = ("status", "direction", "settlement_status")
    search_fields = ("strategy__key", "instrument")

    def has_add_permission(self, request):
        # Predictions are created by the paper service from live signals -
        # never hand-added after outcomes could be known.
        return False

    # Deliberately NOT editable in bulk: pre-outcome fields are frozen by the
    # model's save() guard and outcomes may only be written through resolve().
    readonly_fields = (
        "strategy",
        "instrument",
        "timeframe",
        "market_type",
        "source",
        "detector_key",
        "direction",
        "signal_candle_open_time",
        "signal_candle_close_time",
        "signal_close_price",
        "prediction_payload",
        "payload_sha256",
        "status",
        "outcome_candle_open_time",
        "outcome_close_price",
        "outcome_up",
        "outcome_correct",
        "outcome_basis",
        "resolved_at",
        "settlement_status",
        "settlement",
        "created_at",
        "updated_at",
    )
