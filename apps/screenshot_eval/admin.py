# screenshot_eval/admin.py
"""Read-mostly admin for Phase 14 evaluation records.

These are research records; the admin exposes them for inspection but does not
provide bulk editing affordances that could rewrite a locked prediction.
"""

from __future__ import annotations

from django.contrib import admin

from apps.screenshot_eval.models import (
    ChartAnnotation,
    ForwardPaperPrediction,
    OutcomeVerification,
    ReviewQueueItem,
    ScreenshotCase,
    ScreenshotRecognition,
    ScreenshotRecognitionRun,
)


@admin.register(ScreenshotCase)
class ScreenshotCaseAdmin(admin.ModelAdmin):
    list_display = ("label", "case_kind", "instrument", "timeframe", "market_type",
                    "review_state", "owner", "created_at")
    list_filter = ("case_kind", "market_type", "review_state", "quality")
    search_fields = ("label", "instrument", "notes")
    readonly_fields = ("created_at", "updated_at")

    def has_add_permission(self, request):
        # Cases are created through the review workflow, not by hand in admin.
        return False


@admin.register(ScreenshotRecognitionRun)
class ScreenshotRecognitionRunAdmin(admin.ModelAdmin):
    list_display = ("pk", "case", "ohlc_available", "data_source", "created_at")
    readonly_fields = ("created_at", "updated_at", "summary")

    def has_add_permission(self, request):
        return False


@admin.register(ScreenshotRecognition)
class ScreenshotRecognitionAdmin(admin.ModelAdmin):
    list_display = ("strategy_id", "recognition_state", "data_verification",
                    "decision", "matches_label")
    list_filter = ("recognition_state", "data_verification", "decision")
    readonly_fields = ("created_at", "updated_at")

    def has_add_permission(self, request):
        return False


@admin.register(ChartAnnotation)
class ChartAnnotationAdmin(admin.ModelAdmin):
    list_display = ("kind", "status", "strategy_key", "case", "created_at")
    list_filter = ("kind", "status")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ForwardPaperPrediction)
class ForwardPaperPredictionAdmin(admin.ModelAdmin):
    list_display = ("strategy_id", "direction", "status", "instrument", "timeframe",
                    "decision_timestamp")
    list_filter = ("direction", "status", "market_type")
    search_fields = ("strategy_id", "strategy_key", "instrument")
    readonly_fields = ("created_at", "updated_at", "payload_sha256")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Locked records are immutable by design; view only.
        return False


@admin.register(OutcomeVerification)
class OutcomeVerificationAdmin(admin.ModelAdmin):
    list_display = ("prediction", "verdict", "status", "feed", "verified_at")
    list_filter = ("verdict", "status")
    readonly_fields = ("created_at", "updated_at", "evidence")

    def has_add_permission(self, request):
        return False


@admin.register(ReviewQueueItem)
class ReviewQueueItemAdmin(admin.ModelAdmin):
    list_display = ("kind", "state", "summary", "owner", "created_at")
    list_filter = ("kind", "state")
    search_fields = ("summary",)
    readonly_fields = ("created_at", "updated_at")
