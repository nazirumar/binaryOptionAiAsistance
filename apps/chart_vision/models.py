"""Chart-vision models: screenshots, analyses and structured observations.

Design notes
------------
* Large vision payloads are stored **once** on :attr:`ScreenshotAnalysis.result`
  (the validated, versioned structured output). Derived rows
  (:class:`VisionObservation`, :class:`DetectedPattern`,
  :class:`DetectedPriceZone`) carry compact, queryable summaries plus evidence
  *references* (candle indices / result paths) rather than duplicating payloads.
* :attr:`ScreenshotAnalysis.idempotency_key` is unique, so repeated analyse
  requests cannot create uncontrolled duplicate processing jobs.
* Screenshot bytes live in private storage (see
  :mod:`apps.chart_vision.storage`) and are never exposed via a public URL.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.chart_vision.constants import (
    AnalysisStatus,
    EventKind,
    ImageFormat,
    ObservationKind,
    PatternCategory,
    PatternDirection,
    ScreenshotQuality,
    Severity,
    UploadStatus,
    ZoneType,
)
from apps.chart_vision.storage import private_screenshot_storage, screenshot_upload_path
from apps.core.models import TimeStampedModel


class ChartScreenshot(TimeStampedModel):
    """An uploaded chart screenshot owned by a user.

    The ``image`` bytes live in private storage. ``sha256`` enables duplicate
    detection; ``status`` tracks upload validation independently of analysis.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chart_screenshots",
    )
    image = models.ImageField(
        upload_to=screenshot_upload_path,
        storage=private_screenshot_storage,
        max_length=300,
    )
    original_filename = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=64, blank=True)
    image_format = models.CharField(
        max_length=10, choices=ImageFormat.choices, blank=True, default=""
    )
    size_bytes = models.PositiveBigIntegerField(default=0)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField(
        max_length=16, choices=UploadStatus.choices, default=UploadStatus.PENDING
    )
    rejection_reason = models.CharField(max_length=255, blank=True)
    #: Small, non-payload metadata (validation summary, EXIF notes, ...).
    metadata = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["owner", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Screenshot #{self.pk} ({self.image_format or 'unknown'})"

    @property
    def is_accepted(self) -> bool:
        return self.status == UploadStatus.ACCEPTED


class ScreenshotAnalysis(TimeStampedModel):
    """A single vision-model analysis run over a screenshot.

    ``result`` holds the complete, schema-validated structured output (stored
    once). Scalar columns duplicate only small, frequently queried values.
    """

    screenshot = models.ForeignKey(
        ChartScreenshot,
        on_delete=models.CASCADE,
        related_name="analyses",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="screenshot_analyses",
    )
    status = models.CharField(
        max_length=24, choices=AnalysisStatus.choices, default=AnalysisStatus.QUEUED
    )
    #: Stable per (screenshot, prompt version, schema version) to deduplicate jobs.
    idempotency_key = models.CharField(max_length=120, unique=True)

    provider = models.CharField(max_length=40, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    prompt_version = models.CharField(max_length=20, blank=True)
    schema_version = models.CharField(max_length=20, blank=True)

    #: Complete validated structured output (single authoritative copy).
    result = models.JSONField(default=dict, blank=True)
    #: Normalised chart metadata (small convenience copy for the UI/history).
    chart_metadata = models.JSONField(default=dict, blank=True)
    candle_count = models.PositiveIntegerField(default=0)
    observation_confidence = models.FloatField(null=True, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    missing_information = models.JSONField(default=list, blank=True)

    error_code = models.CharField(max_length=60, blank=True)
    error_message = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)

    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    provider_latency_ms = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["screenshot", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Analysis #{self.pk} [{self.status}]"

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            AnalysisStatus.COMPLETED,
            AnalysisStatus.PARTIAL,
            AnalysisStatus.INSUFFICIENT,
            AnalysisStatus.FAILED,
        }

    @property
    def is_in_flight(self) -> bool:
        return self.status in {AnalysisStatus.QUEUED, AnalysisStatus.RUNNING}

    @property
    def quality(self) -> str:
        quality = (self.chart_metadata or {}).get("screenshot_quality") or {}
        if isinstance(quality, dict):
            return quality.get("rating", ScreenshotQuality.UNKNOWN)
        return ScreenshotQuality.UNKNOWN


class VisionObservation(TimeStampedModel):
    """A compact, queryable observation derived from an analysis result.

    ``evidence`` holds references (e.g. ``{"result_path": "...", "candles": [1, 2]}``)
    rather than a copy of the full structured payload.
    """

    analysis = models.ForeignKey(
        ScreenshotAnalysis, on_delete=models.CASCADE, related_name="observations"
    )
    kind = models.CharField(max_length=32, choices=ObservationKind.choices)
    label = models.CharField(max_length=120)
    summary = models.TextField(blank=True)
    confidence = models.FloatField(null=True, blank=True)
    #: ``None`` = unknown, ``True`` = confirmed visual observation, ``False`` = uncertain.
    confirmed = models.BooleanField(null=True, blank=True)
    evidence = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("kind", "label")
        indexes = [models.Index(fields=["analysis", "kind"])]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.label}"


class DetectedPattern(TimeStampedModel):
    """A candidate candlestick/sequence/advanced-course pattern.

    A candidate pattern is an *observation*, never proof of a future move.
    """

    analysis = models.ForeignKey(
        ScreenshotAnalysis, on_delete=models.CASCADE, related_name="patterns"
    )
    name = models.CharField(max_length=80)
    category = models.CharField(max_length=20, choices=PatternCategory.choices)
    direction = models.CharField(
        max_length=10, choices=PatternDirection.choices, default=PatternDirection.UNKNOWN
    )
    #: Candle indices (left-to-right) that support the candidate.
    candle_refs = models.JSONField(default=list, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    confirmed = models.BooleanField(null=True, blank=True)
    description = models.TextField(blank=True)
    evidence = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("category", "name")
        indexes = [models.Index(fields=["analysis", "category"])]

    def __str__(self) -> str:
        return f"{self.get_category_display()} pattern: {self.name}"


class DetectedPriceZone(TimeStampedModel):
    """A candidate support/resistance zone read from the screenshot."""

    analysis = models.ForeignKey(
        ScreenshotAnalysis, on_delete=models.CASCADE, related_name="price_zones"
    )
    zone_type = models.CharField(max_length=16, choices=ZoneType.choices)
    #: Qualitative location (e.g. ``"upper-third"``); never a fabricated price.
    approx_location = models.CharField(max_length=60, blank=True)
    #: A price string only when a visible axis label supports it; else blank.
    price_hint = models.CharField(max_length=60, blank=True)
    supporting_candles = models.JSONField(default=list, blank=True)
    repeated_rejection = models.BooleanField(default=False)
    broken = models.BooleanField(default=False)
    #: ``"support_to_resistance"`` / ``"resistance_to_support"`` / ``""``.
    flip = models.CharField(max_length=40, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    description = models.TextField(blank=True)
    evidence = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("zone_type", "-confidence")
        indexes = [models.Index(fields=["analysis", "zone_type"])]

    def __str__(self) -> str:
        return f"{self.get_zone_type_display()} zone ({self.approx_location or 'n/a'})"


class VisionProcessingEvent(TimeStampedModel):
    """Structured, timestamped audit trail for a screenshot/analysis.

    Events record upload validation, provider requests/responses, schema
    outcomes and failures without ever storing provider secrets.
    """

    analysis = models.ForeignKey(
        ScreenshotAnalysis,
        on_delete=models.CASCADE,
        related_name="events",
        null=True,
        blank=True,
    )
    screenshot = models.ForeignKey(
        ChartScreenshot,
        on_delete=models.CASCADE,
        related_name="events",
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=24, choices=EventKind.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.INFO)
    message = models.CharField(max_length=255, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ("-occurred_at",)
        indexes = [models.Index(fields=["analysis", "occurred_at"])]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.kind}: {self.message}"


__all__ = [
    "ChartScreenshot",
    "DetectedPattern",
    "DetectedPriceZone",
    "ScreenshotAnalysis",
    "VisionObservation",
    "VisionProcessingEvent",
]
