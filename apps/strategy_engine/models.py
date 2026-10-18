# apps/strategy_engine/models.py
"""Strategy evaluation models (Phase 6)."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.strategy_engine.constants import (
    CandidateStatus,
    EvaluationDirection,
    InvalidationReasonCode,
    MarketContextState,
    ProbabilityStatus,
    StrategyFamily,
    TimingValidity,
)


class StrategyEvaluation(TimeStampedModel):
    """Main strategy evaluation record."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="strategy_evaluations",
        null=True,
        blank=True,
    )
    screenshot_analysis = models.ForeignKey(
        "chart_vision.ScreenshotAnalysis",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="strategy_evaluations",
    )
    sync_session = models.ForeignKey(
        "market_sync.MarketSyncSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="strategy_evaluations",
    )

    # Input/output snapshots
    input_snapshot = models.JSONField(default=dict, blank=True)
    output_snapshot = models.JSONField(default=dict, blank=True)

    # Identification
    evaluation_id = models.CharField(max_length=64, blank=True, db_index=True)
    instrument = models.CharField(max_length=32, blank=True)
    canonical_instrument = models.CharField(max_length=24, blank=True)
    broker_symbol = models.CharField(max_length=64, blank=True)
    timeframe = models.CharField(max_length=4, blank=True)
    market_type = models.CharField(max_length=16, blank=True)

    # Decision
    direction = models.CharField(
        max_length=16,
        choices=EvaluationDirection.choices,
        default=EvaluationDirection.NO_TRADE,
    )
    strategy_family = models.CharField(
        max_length=32,
        choices=StrategyFamily.choices,
        default=StrategyFamily.UNKNOWN,
    )
    status = models.CharField(
        max_length=16,
        choices=CandidateStatus.choices,
        default=CandidateStatus.REJECTED,
    )

    # Context and confluence
    market_context = models.CharField(
        max_length=24,
        choices=MarketContextState.choices,
        default=MarketContextState.UNCERTAIN,
    )
    confluence_score = models.FloatField(null=True, blank=True)

    # Timing
    signal_candle_open_time = models.DateTimeField(null=True, blank=True)
    signal_candle_close_time = models.DateTimeField(null=True, blank=True)
    target_candle_open_time = models.DateTimeField(null=True, blank=True)
    target_candle_close_time = models.DateTimeField(null=True, blank=True)
    screenshot_capture_time = models.DateTimeField(null=True, blank=True)
    screenshot_upload_time = models.DateTimeField(null=True, blank=True)
    mt5_snapshot_time = models.DateTimeField(null=True, blank=True)
    analysis_completion_time = models.DateTimeField(null=True, blank=True)
    timing_validity = models.CharField(
        max_length=24,
        choices=TimingValidity.choices,
        default=TimingValidity.UNCERTAIN,
    )

    # Sync/data
    sync_status = models.CharField(max_length=32, blank=True)
    feed_compatibility = models.CharField(max_length=32, blank=True)
    data_quality = models.CharField(max_length=20, blank=True)
    data_freshness = models.CharField(max_length=16, blank=True)

    # Decision reasoning
    primary_reason_code = models.CharField(
        max_length=32,
        choices=InvalidationReasonCode.choices,
        blank=True,
    )
    reason_codes = models.JSONField(default=list, blank=True)
    explanation = models.TextField(blank=True)
    warnings = models.JSONField(default=list, blank=True)
    invalidation_conditions = models.JSONField(default=list, blank=True)

    # Versions
    schema_version = models.CharField(max_length=16, blank=True)
    engine_config_version = models.CharField(max_length=16, blank=True)
    rule_version = models.CharField(max_length=16, blank=True)
    price_action_result_version = models.CharField(max_length=16, blank=True)

    # Probability (must not hold fabricated numeric probability)
    probability_status = models.CharField(
        max_length=32,
        choices=ProbabilityStatus.choices,
        default=ProbabilityStatus.UNAVAILABLE_UNCALIBRATED,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"]),
            models.Index(fields=["direction", "created_at"]),
            models.Index(fields=["screenshot_analysis"]),
            models.Index(fields=["sync_session"]),
        ]

    def __str__(self) -> str:
        return f"eval#{self.pk} [{self.direction}]"


class StrategyCandidate(TimeStampedModel):
    """Bullish/bearish strategy candidate."""

    evaluation = models.ForeignKey(
        StrategyEvaluation, on_delete=models.CASCADE, related_name="candidates"
    )
    direction = models.CharField(max_length=16, choices=EvaluationDirection.choices)
    strategy_family = models.CharField(max_length=32, choices=StrategyFamily.choices)
    status = models.CharField(max_length=16, choices=CandidateStatus.choices)

    supporting_evidence = models.JSONField(default=list, blank=True)
    contradictory_evidence = models.JSONField(default=list, blank=True)
    required_conditions = models.JSONField(default=list, blank=True)
    missing_conditions = models.JSONField(default=list, blank=True)
    invalidation_conditions = models.JSONField(default=list, blank=True)

    candle_refs = models.JSONField(default=list, blank=True)
    price_levels = models.JSONField(default=list, blank=True)

    signal_timestamp = models.DateTimeField(null=True, blank=True)
    evaluation_timestamp = models.DateTimeField(null=True, blank=True)

    rule_versions = models.JSONField(default=list, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    confluence_score = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.direction}:{self.strategy_family}"


class EvaluationEvidence(TimeStampedModel):
    """Evidence linked to an evaluation."""

    evaluation = models.ForeignKey(
        StrategyEvaluation, on_delete=models.CASCADE, related_name="linked_evidence"
    )
    evidence_ref = models.CharField(max_length=128, blank=True)
    rule_id = models.CharField(max_length=120)
    detector = models.CharField(max_length=80)
    direction = models.CharField(max_length=16, blank=True)
    is_supporting = models.BooleanField(default=True)
    is_contradictory = models.BooleanField(default=False)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.rule_id


class EvaluationConflict(TimeStampedModel):
    """Conflict recorded during evaluation."""

    evaluation = models.ForeignKey(
        StrategyEvaluation, on_delete=models.CASCADE, related_name="conflicts"
    )
    conflict_type = models.CharField(max_length=64)
    severity = models.CharField(max_length=16)
    explanation = models.TextField(blank=True)
    rule_a = models.CharField(max_length=120, blank=True)
    rule_b = models.CharField(max_length=120, blank=True)
    candle_refs = models.JSONField(default=list, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.conflict_type


class DecisionAuditLog(TimeStampedModel):
    """Audit trail for evaluation decisions."""

    evaluation = models.ForeignKey(
        StrategyEvaluation, on_delete=models.CASCADE, related_name="audit_logs"
    )
    event_type = models.CharField(max_length=64)
    severity = models.CharField(max_length=16, default="info")
    message = models.CharField(max_length=400)
    detail = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["occurred_at", "id"]

    def __str__(self) -> str:
        return f"{self.event_type}"


class StrategyRuleConfiguration(TimeStampedModel):
    """Versioned strategy rule configuration."""

    name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=False)
    config_version = models.CharField(max_length=16)
    rule_version = models.CharField(max_length=16)
    config = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.name


__all__ = [
    "DecisionAuditLog",
    "EvaluationConflict",
    "EvaluationEvidence",
    "StrategyCandidate",
    "StrategyEvaluation",
    "StrategyRuleConfiguration",
]
