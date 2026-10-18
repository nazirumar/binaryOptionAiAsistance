"""Django admin for chart-vision models."""

from __future__ import annotations

from django.contrib import admin

from apps.chart_vision.models import (
    ChartScreenshot,
    DetectedPattern,
    DetectedPriceZone,
    ScreenshotAnalysis,
    VisionObservation,
    VisionProcessingEvent,
)


@admin.register(ChartScreenshot)
class ChartScreenshotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "owner",
        "image_format",
        "width",
        "height",
        "size_bytes",
        "status",
        "created_at",
    )
    list_filter = ("status", "image_format")
    search_fields = ("original_filename", "sha256", "owner__username")
    readonly_fields = (
        "sha256",
        "size_bytes",
        "width",
        "height",
        "created_at",
        "updated_at",
    )


class VisionObservationInline(admin.TabularInline):
    model = VisionObservation
    extra = 0
    fields = ("kind", "label", "confidence", "confirmed")
    readonly_fields = fields


class DetectedPatternInline(admin.TabularInline):
    model = DetectedPattern
    extra = 0
    fields = ("name", "category", "direction", "confidence", "confirmed")
    readonly_fields = fields


class DetectedPriceZoneInline(admin.TabularInline):
    model = DetectedPriceZone
    extra = 0
    fields = ("zone_type", "approx_location", "price_hint", "confidence", "broken")
    readonly_fields = fields


@admin.register(ScreenshotAnalysis)
class ScreenshotAnalysisAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "owner",
        "status",
        "provider",
        "model_name",
        "prompt_version",
        "candle_count",
        "observation_confidence",
        "created_at",
    )
    list_filter = ("status", "provider", "prompt_version", "schema_version")
    search_fields = ("idempotency_key", "model_name", "owner__username", "error_code")
    readonly_fields = ("created_at", "updated_at", "idempotency_key")
    inlines = [
        VisionObservationInline,
        DetectedPatternInline,
        DetectedPriceZoneInline,
    ]


@admin.register(VisionObservation)
class VisionObservationAdmin(admin.ModelAdmin):
    list_display = ("id", "analysis", "kind", "label", "confidence", "confirmed")
    list_filter = ("kind", "confirmed")
    search_fields = ("label", "summary")


@admin.register(DetectedPattern)
class DetectedPatternAdmin(admin.ModelAdmin):
    list_display = ("id", "analysis", "name", "category", "direction", "confidence")
    list_filter = ("category", "direction", "confirmed")
    search_fields = ("name", "description")


@admin.register(DetectedPriceZone)
class DetectedPriceZoneAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "analysis",
        "zone_type",
        "approx_location",
        "price_hint",
        "broken",
        "confidence",
    )
    list_filter = ("zone_type", "broken", "repeated_rejection")
    search_fields = ("approx_location", "price_hint", "description")


@admin.register(VisionProcessingEvent)
class VisionProcessingEventAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "kind", "severity", "message", "analysis", "screenshot")
    list_filter = ("kind", "severity")
    search_fields = ("message",)
