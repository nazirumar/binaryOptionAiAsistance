# apps/strategy_knowledge/models.py
"""Versioned strategy knowledge base (Phase 12, CP1).

Design rules
------------
* A :class:`StrategyDefinition` is *data*, never code. Its conditions are
  structured rows (:class:`StrategyCondition`) validated against whitelisted
  schemas; ``detector_key`` only ever *references* a fixed registry of
  deterministic detectors, so database content cannot execute arbitrary logic.
* Unapproved/experimental definitions exist but are explicitly labelled and
  cannot be silently activated: the recognition services filter on
  ``enabled`` and report ``validation_status`` with every detection.
* Detections link back to the vision analysis that produced the candidates and
  to the definition version that was applied, so every recognition is auditable.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel
from apps.strategy_knowledge.constants import (
    DETECTOR_KEYS,
    ConditionKind,
    ConditionSource,
    DatasetSampleKind,
    DetectionStatus,
    EvidenceProvenance,
    LabelSource,
    StrategyVariant,
    ValidationStatus,
)


class StrategyCategory(TimeStampedModel):
    """Grouping for the strategy library (e.g. candlestick, S/R, ICT)."""

    slug = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "name")

    def __str__(self) -> str:
        return self.name


class StrategyVersion(TimeStampedModel):
    """A released knowledge-base version. Definitions point at exactly one."""

    version = models.CharField(max_length=24, unique=True)
    notes = models.TextField(blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.version


class StrategyDefinition(TimeStampedModel):
    """One strategy with structured, validated conditions.

    ``detector_key`` must be a member of :data:`~apps.strategy_knowledge.constants.
    DETECTOR_KEYS`; anything else is stored but inert (the definition renders in
    the library but no detection can be produced from it).
    """

    strategy_id = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=160)
    category = models.ForeignKey(
        StrategyCategory, on_delete=models.PROTECT, related_name="definitions"
    )
    description = models.TextField()
    #: When/where the setup is meaningful (trend, level, session…).
    market_context = models.TextField(blank=True)
    timeframe = models.CharField(max_length=40, blank=True, default="any")
    variant = models.CharField(
        max_length=10, choices=StrategyVariant.choices, default=StrategyVariant.NEUTRAL
    )
    #: Pattern-completion rules (structured list of sentences).
    completion_rules = models.JSONField(default=list, blank=True)
    #: What to look for in a screenshot (education, not detection logic).
    screenshot_guidance = models.TextField(blank=True)
    #: Reference into the deterministic detector registry ("" = knowledge only).
    detector_key = models.CharField(max_length=60, blank=True, default="")
    course_reference = models.CharField(max_length=200, blank=True)
    validation_status = models.CharField(
        max_length=16, choices=ValidationStatus.choices, default=ValidationStatus.DRAFT
    )
    version = models.ForeignKey(
        StrategyVersion, on_delete=models.PROTECT, related_name="definitions", null=True, blank=True
    )
    enabled = models.BooleanField(default=False)
    #: Honest disclaimer surfaced with every recognition.
    validation_notes = models.TextField(blank=True)

    class Meta:
        ordering = ("category__order", "name")
        indexes = [models.Index(fields=["validation_status", "enabled"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.strategy_id})"

    def clean(self) -> None:
        super().clean()
        if self.detector_key and self.detector_key not in DETECTOR_KEYS:
            raise ValidationError(
                {
                    "detector_key": (
                        "Unknown detector key. Only registry-backed deterministic "
                        "detectors may be referenced."
                    )
                }
            )

    @property
    def is_active(self) -> bool:
        return self.enabled and self.validation_status in (
            ValidationStatus.APPROVED,
            ValidationStatus.REVIEWED,
        )

    @property
    def status_label(self) -> str:
        """Human label used by the library UI — experimental is never hidden."""
        if not self.enabled:
            return "Disabled"
        if self.validation_status == ValidationStatus.EXPERIMENTAL:
            return "Experimental (not validated)"
        if self.validation_status == ValidationStatus.APPROVED:
            return "Approved"
        if self.validation_status == ValidationStatus.REVIEWED:
            return "Reviewed"
        if self.validation_status == ValidationStatus.RETIRED:
            return "Retired"
        return "Draft"


class StrategyCondition(TimeStampedModel):
    """A single structured condition; required/optional/contradiction/invalidation.

    ``params`` is a JSON object validated by
    :func:`apps.strategy_knowledge.schemas.validate_condition_params` — only
    whitelisted scalar keys are accepted (thresholds, windows, labels).
    """

    definition = models.ForeignKey(
        StrategyDefinition, on_delete=models.CASCADE, related_name="conditions"
    )
    order = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=16, choices=ConditionKind.choices)
    label = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    detector_key = models.CharField(max_length=60, blank=True, default="")
    params = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("kind", "order", "id")
        indexes = [models.Index(fields=["definition", "kind"])]

    def __str__(self) -> str:
        return f"{self.kind}: {self.label}"

    def clean(self) -> None:
        super().clean()
        if self.detector_key and self.detector_key not in DETECTOR_KEYS:
            raise ValidationError({"detector_key": "Unknown detector key."})
        from apps.strategy_knowledge.schemas import validate_condition_params

        errors = validate_condition_params(self.params)
        if errors:
            raise ValidationError({"params": "; ".join(errors)})


class StrategyPatternLabel(TimeStampedModel):
    """Canonical label mapping recognition vocabulary → a definition.

    Vision output and detector names are normalised through this table so the
    recognition layer never fuzzy-matches free text to strategies.
    """

    label = models.CharField(max_length=80, unique=True)
    definition = models.ForeignKey(
        StrategyDefinition, on_delete=models.CASCADE, related_name="pattern_labels"
    )
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ("label",)

    def __str__(self) -> str:
        return self.label


class StrategyExample(TimeStampedModel):
    """A bullish/bearish teaching example attached to a definition."""

    definition = models.ForeignKey(
        StrategyDefinition, on_delete=models.CASCADE, related_name="examples"
    )
    is_bullish = models.BooleanField(default=True)
    title = models.CharField(max_length=160)
    description = models.TextField()
    #: Optional screenshot reference (private storage; never re-hosted).
    screenshot = models.ForeignKey(
        "chart_vision.ChartScreenshot",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="strategy_examples",
    )
    candle_refs = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ("definition", "is_bullish", "title")

    def __str__(self) -> str:
        return self.title


class StrategyDetection(TimeStampedModel):
    """A verified recognition outcome for one strategy on one analysis.

    ``status`` is produced by
    :class:`apps.strategy_knowledge.services.PatternVerificationService`, never
    by an LLM naming a pattern. When OHLC confirmation was required but the
    feed is incompatible (e.g. OTC screenshot vs normal MT5 prices), the status
    is capped at ``possible`` with screenshot-only provenance.
    """

    analysis = models.ForeignKey(
        "chart_vision.ScreenshotAnalysis",
        on_delete=models.CASCADE,
        related_name="strategy_detections",
    )
    definition = models.ForeignKey(
        StrategyDefinition, on_delete=models.PROTECT, related_name="detections"
    )
    #: Definition version applied at verification time (auditable).
    definition_version = models.CharField(max_length=24, blank=True)
    status = models.CharField(max_length=24, choices=DetectionStatus.choices)
    direction = models.CharField(
        max_length=10, choices=StrategyVariant.choices, default=StrategyVariant.NEUTRAL
    )
    provenance = models.CharField(
        max_length=20, choices=EvidenceProvenance.choices, default=EvidenceProvenance.VISION
    )
    confidence = models.FloatField(null=True, blank=True)
    summary = models.TextField(blank=True)
    missing_conditions = models.JSONField(default=list, blank=True)
    contradictions = models.JSONField(default=list, blank=True)
    invalidation = models.JSONField(default=list, blank=True)
    #: True when precise prices are needed and only pixels were available.
    requires_ohlc_confirmation = models.BooleanField(default=False)
    ohlc_confirmed = models.BooleanField(default=False)
    otc_incompatible = models.BooleanField(default=False)
    deduped_from = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["analysis", "status"]),
            models.Index(fields=["definition", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.definition.strategy_id}: {self.status}"


class StrategyDetectionEvidence(TimeStampedModel):
    """One piece of evidence behind a detection (candles, levels, observations)."""

    detection = models.ForeignKey(
        StrategyDetection, on_delete=models.CASCADE, related_name="evidence_items"
    )
    condition_kind = models.CharField(max_length=16, choices=ConditionKind.choices)
    label = models.CharField(max_length=160)
    source = models.CharField(max_length=16, choices=ConditionSource.choices)
    satisfied = models.BooleanField(default=False)
    candle_refs = models.JSONField(default=list, blank=True)
    levels = models.JSONField(default=list, blank=True)
    detail = models.TextField(blank=True)
    confidence = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ("detection", "id")

    def __str__(self) -> str:
        mark = "[x]" if self.satisfied else "[ ]"
        return f"{mark} {self.label}"


class StrategyDatasetSample(TimeStampedModel):
    """A labelled dataset entry (CP14). Reviewer labels are ground truth; vision
    candidates are stored only as unverified candidates."""

    screenshot = models.ForeignKey(
        "chart_vision.ChartScreenshot",
        on_delete=models.CASCADE,
        related_name="dataset_samples",
    )
    instrument = models.CharField(max_length=40, blank=True)
    timeframe = models.CharField(max_length=20, blank=True)
    market_type = models.CharField(max_length=20, blank=True)
    definition = models.ForeignKey(
        StrategyDefinition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dataset_samples",
    )
    #: Free-text label kept when no definition matches (e.g. lookalike classes).
    label = models.CharField(max_length=80)
    sample_kind = models.CharField(max_length=16, choices=DatasetSampleKind.choices)
    label_source = models.CharField(max_length=20, choices=LabelSource.choices)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_strategy_samples",
    )
    #: True only when ``reviewer`` confirmed the label (ground truth flag).
    reviewer_approved = models.BooleanField(default=False)
    label_confidence = models.FloatField(null=True, blank=True)
    dataset_version = models.CharField(max_length=24, default="0")
    candle_refs = models.JSONField(default=list, blank=True)
    annotated_regions = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["dataset_version", "sample_kind"]),
            models.Index(fields=["label_source", "reviewer_approved"]),
        ]

    def __str__(self) -> str:
        return f"{self.label} [{self.sample_kind}]"


__all__ = [
    "StrategyCategory",
    "StrategyCondition",
    "StrategyDatasetSample",
    "StrategyDefinition",
    "StrategyDetection",
    "StrategyDetectionEvidence",
    "StrategyExample",
    "StrategyPatternLabel",
    "StrategyVersion",
]
