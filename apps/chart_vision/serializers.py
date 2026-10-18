"""Serializers for the chart-vision API.

Read serializers expose ownership-scoped representations; ``image_url`` points at
the authenticated image endpoint (never a public media URL).
"""

from __future__ import annotations

from django.urls import NoReverseMatch, reverse
from rest_framework import serializers

from apps.chart_vision.constants import AnalysisStatus
from apps.chart_vision.models import (
    ChartScreenshot,
    DetectedPattern,
    DetectedPriceZone,
    ScreenshotAnalysis,
    VisionObservation,
    VisionProcessingEvent,
)


class ChartScreenshotSerializer(serializers.ModelSerializer):
    """Metadata for an uploaded screenshot (no file bytes)."""

    image_url = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ChartScreenshot
        fields = (
            "id",
            "original_filename",
            "content_type",
            "image_format",
            "size_bytes",
            "width",
            "height",
            "sha256",
            "status",
            "status_display",
            "rejection_reason",
            "metadata",
            "expires_at",
            "created_at",
            "updated_at",
            "image_url",
        )
        read_only_fields = fields

    def get_image_url(self, obj: ChartScreenshot) -> str:
        try:
            return reverse("chart_vision:screenshot-image", args=[obj.pk])
        except NoReverseMatch:  # pragma: no cover - defensive
            return ""


class ScreenshotUploadSerializer(serializers.Serializer):
    """Validates a screenshot upload request (multipart)."""

    image = serializers.FileField(help_text="PNG, JPEG or WebP candlestick-chart screenshot.")


class VisionObservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisionObservation
        fields = ("id", "kind", "label", "summary", "confidence", "confirmed", "evidence")
        read_only_fields = fields


class DetectedPatternSerializer(serializers.ModelSerializer):
    class Meta:
        model = DetectedPattern
        fields = (
            "id",
            "name",
            "category",
            "direction",
            "candle_refs",
            "confidence",
            "confirmed",
            "description",
            "evidence",
        )
        read_only_fields = fields


class DetectedPriceZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = DetectedPriceZone
        fields = (
            "id",
            "zone_type",
            "approx_location",
            "price_hint",
            "supporting_candles",
            "repeated_rejection",
            "broken",
            "flip",
            "confidence",
            "description",
            "evidence",
        )
        read_only_fields = fields


class VisionProcessingEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisionProcessingEvent
        fields = ("id", "kind", "severity", "message", "detail", "occurred_at")
        read_only_fields = fields


class ScreenshotAnalysisSerializer(serializers.ModelSerializer):
    """Full analysis representation, including the validated structured result."""

    screenshot = ChartScreenshotSerializer(read_only=True)
    observations = VisionObservationSerializer(many=True, read_only=True)
    patterns = DetectedPatternSerializer(many=True, read_only=True)
    price_zones = DetectedPriceZoneSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ScreenshotAnalysis
        fields = (
            "id",
            "screenshot",
            "status",
            "status_display",
            "provider",
            "model_name",
            "prompt_version",
            "schema_version",
            "chart_metadata",
            "candle_count",
            "observation_confidence",
            "warnings",
            "missing_information",
            "result",
            "observations",
            "patterns",
            "price_zones",
            "error_code",
            "error_message",
            "attempts",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "provider_latency_ms",
            "started_at",
            "finished_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ScreenshotAnalysisSummarySerializer(serializers.ModelSerializer):
    """Compact analysis representation for the history list (no big payload)."""

    screenshot_id = serializers.IntegerField(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ScreenshotAnalysis
        fields = (
            "id",
            "screenshot_id",
            "status",
            "status_display",
            "provider",
            "model_name",
            "prompt_version",
            "schema_version",
            "candle_count",
            "observation_confidence",
            "warnings",
            "missing_information",
            "error_code",
            "created_at",
            "finished_at",
        )
        read_only_fields = fields


class VisionStatusSerializer(serializers.ModelSerializer):
    """Minimal polling representation of an analysis."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_terminal = serializers.BooleanField(read_only=True)

    class Meta:
        model = ScreenshotAnalysis
        fields = (
            "id",
            "status",
            "status_display",
            "is_terminal",
            "error_code",
            "error_message",
            "started_at",
            "finished_at",
        )
        read_only_fields = fields


class HistoryQuerySerializer(serializers.Serializer):
    """Validates ``GET /api/vision/history/`` query parameters."""

    status = serializers.ChoiceField(choices=AnalysisStatus.choices, required=False)
    ordering = serializers.ChoiceField(
        choices=["-created_at", "created_at", "-finished_at"], required=False
    )


__all__ = [
    "ChartScreenshotSerializer",
    "DetectedPatternSerializer",
    "DetectedPriceZoneSerializer",
    "HistoryQuerySerializer",
    "ScreenshotAnalysisSerializer",
    "ScreenshotAnalysisSummarySerializer",
    "ScreenshotUploadSerializer",
    "VisionObservationSerializer",
    "VisionProcessingEventSerializer",
    "VisionStatusSerializer",
]
