"""Market-synchronization models (Step 13).

Evidence is preserved for later audits:

* :class:`MarketSyncSession` stores the overall comparison, its configuration
  version and a compact MT5 snapshot reference (not a duplicate of the candles).
* :class:`CandleAlignment` stores the per-candle comparison.
* :class:`FeedCompatibilityAssessment` stores the instrument/OTC assessment.
* :class:`MarketSyncIssue` stores mismatch reasons.
* :class:`SynchronizationAuditLog` stores the processing trail.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.market_data.constants import Timeframe
from apps.market_sync.constants import (
    AlignmentSource,
    AuditKind,
    ComparisonMethod,
    FeedCompatibilityStatus,
    FreshnessStatus,
    MappingSource,
    PriceComparisonMethod,
    SessionStatus,
    Severity,
    StructureAgreement,
    SyncStatus,
)


class MarketSyncSession(TimeStampedModel):
    """One verification run comparing a screenshot analysis against MT5 data."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="market_sync_sessions",
    )
    screenshot = models.ForeignKey(
        "chart_vision.ChartScreenshot",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_sessions",
    )
    analysis = models.ForeignKey(
        "chart_vision.ScreenshotAnalysis",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_sessions",
    )
    profile = models.ForeignKey(
        "market_data.MT5ConnectionProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_sessions",
    )
    reference_symbol = models.ForeignKey(
        "market_data.MarketSymbol",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_sessions",
    )

    status = models.CharField(
        max_length=16, choices=SessionStatus.choices, default=SessionStatus.PENDING
    )
    outcome = models.CharField(max_length=32, choices=SyncStatus.choices, blank=True, default="")
    comparison_method = models.CharField(
        max_length=32,
        choices=ComparisonMethod.choices,
        default=ComparisonMethod.QUALITATIVE_RELATIVE,
    )
    config_version = models.CharField(max_length=16, blank=True)
    idempotency_key = models.CharField(max_length=160, null=True, blank=True, unique=True)

    # Instrument mapping
    screenshot_instrument = models.CharField(max_length=64, blank=True)
    canonical_instrument = models.CharField(max_length=24, blank=True)
    mt5_broker_symbol = models.CharField(max_length=64, blank=True)
    broker = models.CharField(max_length=120, blank=True)
    market_type = models.CharField(max_length=16, blank=True)
    mapping_source = models.CharField(
        max_length=24, choices=MappingSource.choices, default=MappingSource.NONE
    )
    mapping_status = models.CharField(max_length=16, blank=True)
    mapping_verified = models.BooleanField(default=False)

    # Timeframe comparison
    screenshot_timeframe = models.CharField(max_length=4, blank=True)
    mt5_timeframe = models.CharField(max_length=4, choices=Timeframe.choices, blank=True)

    # Timestamp alignment
    alignment_anchor = models.DateTimeField(null=True, blank=True)
    alignment_source = models.CharField(
        max_length=24, choices=AlignmentSource.choices, default=AlignmentSource.NONE
    )
    alignment_confidence = models.FloatField(null=True, blank=True)
    alignment_uncertain = models.BooleanField(default=True)

    # Comparison tallies
    screenshot_candle_count = models.PositiveIntegerField(default=0)
    completed_candle_count = models.PositiveIntegerField(default=0)
    aligned_candle_count = models.PositiveIntegerField(default=0)
    matched_candle_count = models.PositiveIntegerField(default=0)
    mismatched_candle_count = models.PositiveIntegerField(default=0)
    unaligned_candle_count = models.PositiveIntegerField(default=0)
    direction_agreement = models.FloatField(null=True, blank=True)

    structure_agreement = models.CharField(
        max_length=24, choices=StructureAgreement.choices, default=StructureAgreement.INSUFFICIENT
    )
    feed_compatibility = models.CharField(
        max_length=24,
        choices=FeedCompatibilityStatus.choices,
        default=FeedCompatibilityStatus.UNKNOWN,
    )
    freshness_status = models.CharField(
        max_length=24, choices=FreshnessStatus.choices, default=FreshnessStatus.UNKNOWN
    )
    price_comparison_method = models.CharField(
        max_length=24,
        choices=PriceComparisonMethod.choices,
        default=PriceComparisonMethod.NOT_AVAILABLE,
    )

    # Evidence / summaries
    mt5_snapshot = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    reasons = models.JSONField(default=list, blank=True)

    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"]),
            models.Index(fields=["outcome"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"sync#{self.pk} [{self.outcome or self.status}]"

    @property
    def is_verified(self) -> bool:
        """Only a verified alignment may be presented as successful."""
        return self.outcome == SyncStatus.VERIFIED_ALIGNMENT

    @property
    def is_complete(self) -> bool:
        return self.status in (SessionStatus.COMPLETED, SessionStatus.FAILED)


class CandleAlignment(TimeStampedModel):
    """Comparison of one completed screenshot candle against an MT5 candle."""

    session = models.ForeignKey(
        MarketSyncSession, on_delete=models.CASCADE, related_name="alignments"
    )
    screenshot_index = models.IntegerField()
    screenshot_classification = models.CharField(max_length=16, blank=True)
    screenshot_body_size = models.CharField(max_length=16, blank=True)
    screenshot_upper_wick = models.CharField(max_length=16, blank=True)
    screenshot_lower_wick = models.CharField(max_length=16, blank=True)
    screenshot_position = models.CharField(max_length=24, blank=True)

    mt5_candle = models.ForeignKey(
        "market_data.MarketCandle",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_alignments",
    )
    mt5_open_time = models.DateTimeField(null=True, blank=True)
    mt5_direction = models.CharField(max_length=16, blank=True)
    mt5_body_ratio = models.FloatField(null=True, blank=True)
    mt5_upper_wick_ratio = models.FloatField(null=True, blank=True)
    mt5_lower_wick_ratio = models.FloatField(null=True, blank=True)

    match_result = models.CharField(max_length=16, blank=True)
    direction_match = models.BooleanField(null=True, blank=True)
    body_match = models.BooleanField(null=True, blank=True)
    wick_match = models.BooleanField(null=True, blank=True)
    local_extreme_match = models.BooleanField(null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)

    limitations = models.JSONField(default=list, blank=True)
    evidence = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["screenshot_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "screenshot_index"], name="uniq_alignment_index_per_session"
            ),
        ]

    def __str__(self) -> str:
        return f"align#{self.screenshot_index} [{self.match_result}]"


class FeedCompatibilityAssessment(TimeStampedModel):
    """Instrument/OTC/feed compatibility for one session (one-to-one)."""

    session = models.OneToOneField(
        MarketSyncSession, on_delete=models.CASCADE, related_name="feed_assessment"
    )
    screenshot_instrument = models.CharField(max_length=64, blank=True)
    canonical_instrument = models.CharField(max_length=24, blank=True)
    mt5_broker_symbol = models.CharField(max_length=64, blank=True)
    broker = models.CharField(max_length=120, blank=True)
    market_type = models.CharField(max_length=16, blank=True)
    mapping_source = models.CharField(max_length=24, blank=True)
    mapping_verification = models.CharField(max_length=16, blank=True)
    mapping_verified = models.BooleanField(default=False)
    screenshot_is_otc = models.BooleanField(null=True, blank=True)
    reference_is_otc = models.BooleanField(null=True, blank=True)
    compatibility = models.CharField(
        max_length=24,
        choices=FeedCompatibilityStatus.choices,
        default=FeedCompatibilityStatus.UNKNOWN,
    )
    reasons = models.JSONField(default=list, blank=True)
    evidence = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return f"feed[{self.compatibility}]"


class MarketSyncIssue(TimeStampedModel):
    """A mismatch or limitation recorded during verification."""

    session = models.ForeignKey(MarketSyncSession, on_delete=models.CASCADE, related_name="issues")
    code = models.CharField(max_length=64)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.INFO)
    message = models.CharField(max_length=400)
    candle_index = models.IntegerField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["severity", "id"]
        indexes = [models.Index(fields=["session", "severity"])]

    def __str__(self) -> str:
        return f"{self.code} [{self.severity}]"


class SynchronizationAuditLog(TimeStampedModel):
    """Ordered processing trail for a session (milestones and errors)."""

    session = models.ForeignKey(
        MarketSyncSession, on_delete=models.CASCADE, related_name="audit_logs"
    )
    kind = models.CharField(max_length=16, choices=AuditKind.choices)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.INFO)
    message = models.CharField(max_length=400)
    detail = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["occurred_at", "id"]
        indexes = [models.Index(fields=["session", "occurred_at"])]

    def __str__(self) -> str:
        return f"{self.kind} @ {self.occurred_at.isoformat()}"


__all__ = [
    "CandleAlignment",
    "FeedCompatibilityAssessment",
    "MarketSyncIssue",
    "MarketSyncSession",
    "SynchronizationAuditLog",
]
