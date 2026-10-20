# screenshot_eval/models.py
"""Phase 14 models: screenshot dataset, recognition, annotations, predictions.

Design notes
------------
* Every model here is *research* machinery. It never approves a strategy, never
  enables trading and never changes ``decision_use_approved``.
* :class:`ForwardPaperPrediction` is the screenshot-driven sibling of Phase 13's
  candle-driven ``PaperForwardPrediction`` and reuses the exact same
  immutability discipline (``payload_sha256`` + frozen fields + a single
  ``verify_outcome`` transition).
* Outcome verification never substitutes feeds: an OTC case with only MT5 data
  is refused (``INCOMPATIBLE_FEEDS``) or left unverifiable, never assumed
  correct.
"""

from __future__ import annotations

import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.chart_vision.models import ChartScreenshot, ScreenshotAnalysis
from apps.core.models import TimeStampedModel
from apps.screenshot_eval.constants import (
    AnnotationStatus,
    CaseKind,
    MarketType,
    OutcomeVerdict,
    PredictionDirection,
    PredictionStatus,
    Provenance,
    ReviewState,
    ScreenshotQuality,
)


def case_payload_digest(payload: dict) -> str:
    """Canonical SHA-256 of a payload (sorted keys, ASCII-safe)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PredictionLockedError(ValidationError):
    """Raised when a locked forward prediction would be rewritten."""


class ScreenshotCase(TimeStampedModel):
    """A curated, human-reviewed screenshot for evaluation (Checkpoint 1).

    A case wraps an existing :class:`~apps.chart_vision.models.ChartScreenshot`
    and records everything a reproducible evaluation needs: instrument,
    timeframe, capture timestamp, market type, quality, the visible candle
    count, the *expected* human label, provenance and the reviewer verdict.

    The ``expected_*`` fields are the human ground truth used for recognition
    precision/recall - they are reviewer-supplied, never model-guessed.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="screenshot_cases",
    )
    screenshot = models.ForeignKey(
        ChartScreenshot,
        on_delete=models.CASCADE,
        related_name="eval_cases",
    )
    label = models.CharField(max_length=200)
    notes = models.TextField(blank=True)

    instrument = models.CharField(max_length=32)
    timeframe = models.CharField(max_length=8)
    screenshot_timestamp = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the chart was captured (from the visible clock or the upload).",
    )
    market_type = models.CharField(
        max_length=16, choices=MarketType.CHOICES, default=MarketType.UNKNOWN
    )
    quality = models.CharField(
        max_length=16, choices=ScreenshotQuality.CHOICES, default=ScreenshotQuality.UNKNOWN
    )
    #: How many closed candles the reviewer counted on the visible panel.
    visible_candle_count = models.PositiveIntegerField(default=0)

    case_kind = models.CharField(
        max_length=16, choices=CaseKind.CHOICES, default=CaseKind.UNLABELLED
    )
    #: Human-expected book strategy keys, e.g. ["SS1"] or [] for a negative.
    expected_strategy_keys = models.JSONField(default=list, blank=True)
    expected_direction = models.CharField(max_length=8, blank=True)

    #: Reviewer-set annotation flags (Checkpoint 3): whether the screenshot
    #: carries reliable pixel coordinates that could be annotated.
    coordinates_reliable = models.BooleanField(default=False)

    source = models.CharField(
        max_length=24, choices=Provenance.CHOICES, default=Provenance.UNKNOWN
    )
    provenance = models.JSONField(default=dict, blank=True)

    review_state = models.CharField(
        max_length=16, choices=ReviewState.CHOICES, default=ReviewState.UNREVIEWED
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_screenshot_cases",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["owner", "review_state"]),
            models.Index(fields=["label"]),
            models.Index(fields=["market_type", "instrument", "timeframe"]),
        ]

    def __str__(self) -> str:
        return f"Case #{self.pk} {self.label} [{self.case_kind}]"

    @property
    def is_labelled(self) -> bool:
        """A case counts as ground truth only once a reviewer accepted it."""
        return self.review_state in (ReviewState.CONFIRMED, ReviewState.CORRECTED)


class ScreenshotRecognitionRun(TimeStampedModel):
    """One recognition pass over a case's analysis (Checkpoint 2).

    Runs the deterministic :class:`~apps.book_strategies.services.recognition.BookStrategyRecognizer`
    over any OHLC the analysis can be matched to (via the sync session), plus
    the fixed vision->book mapper. Every result is persisted; nothing is
    recomputed on page load.
    """

    case = models.ForeignKey(
        ScreenshotCase,
        on_delete=models.CASCADE,
        related_name="recognition_runs",
    )
    analysis = models.ForeignKey(
        ScreenshotAnalysis,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eval_recognition_runs",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="screenshot_recognition_runs",
    )
    #: Which strategies were evaluated (keys overall) and with what data source.
    strategies_evaluated = models.JSONField(default=list, blank=True)
    ohlc_available = models.BooleanField(default=False)
    data_source = models.CharField(max_length=120, blank=True)
    market_type = models.CharField(max_length=16, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    disclaimer = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["case", "created_at"])]

    def __str__(self) -> str:
        return f"Recognition run #{self.pk} for case #{self.case_id}"


class ScreenshotRecognition(TimeStampedModel):
    """One strategy's recognition result within a run (Checkpoint 2).

    Carries exactly what the requirement asks for: strategy id, recognition
    state, visible evidence, missing conditions, invalidation evidence and data
    verification status. ``decision`` is always ``NO_TRADE`` and ``probability``
    always ``None`` - a recognised pattern is an observation, not a trade.
    """

    run = models.ForeignKey(
        ScreenshotRecognitionRun,
        on_delete=models.CASCADE,
        related_name="recognitions",
    )
    strategy_key = models.CharField(max_length=16)
    strategy_id = models.CharField(max_length=24)
    strategy_name = models.CharField(max_length=160, blank=True)
    book_number = models.PositiveSmallIntegerField(default=0)

    recognition_state = models.CharField(max_length=24)
    direction = models.CharField(max_length=8, default="neutral")
    observed_evidence = models.JSONField(default=list, blank=True)
    missing_conditions = models.JSONField(default=list, blank=True)
    invalidation_evidence = models.JSONField(default=list, blank=True)
    contradictions = models.JSONField(default=list, blank=True)
    candle_refs = models.JSONField(default=list, blank=True)
    reference_level = models.FloatField(null=True, blank=True)
    data_verification = models.CharField(max_length=24)
    #: Whether this recognition agrees with the case's human label (only
    #: meaningful for reviewed cases; ``None`` when no label exists).
    matches_label = models.BooleanField(null=True, blank=True)

    decision = models.CharField(max_length=16, default="NO_TRADE")
    probability = models.FloatField(null=True, blank=True)
    probability_status = models.CharField(max_length=32, default="UNAVAILABLE_UNCALIBRATED")

    class Meta:
        ordering = ("book_number", "strategy_key")
        indexes = [
            models.Index(fields=["run", "strategy_key"]),
            models.Index(fields=["recognition_state"]),
        ]

    def __str__(self) -> str:
        return f"{self.strategy_id}: {self.recognition_state}"


class ChartAnnotation(TimeStampedModel):
    """A chart annotation for a case (Checkpoint 3).

    Annotations are only written when the coordinates are *reliable*;
    otherwise the record is stored with ``status = skipped`` and a reason, and
    nothing is drawn. The original screenshot is never modified.
    """

    case = models.ForeignKey(
        ScreenshotCase,
        on_delete=models.CASCADE,
        related_name="annotations",
    )
    run = models.ForeignKey(
        ScreenshotRecognitionRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="annotations",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chart_annotations",
    )
    kind = models.CharField(max_length=32)
    strategy_key = models.CharField(max_length=16, blank=True)
    label = models.CharField(max_length=160, blank=True)
    status = models.CharField(
        max_length=16, choices=AnnotationStatus.CHOICES, default=AnnotationStatus.SKIPPED
    )
    #: Coordinates are recorded as *relative* [x0, y0, x1, y1] fractions of the
    #: image (0..1) and only when a reviewer/geometry step supplied them. They
    #: are never invented from a model's description.
    relative_coordinates = models.JSONField(null=True, blank=True)
    candle_refs = models.JSONField(default=list, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    evidence = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("kind", "strategy_key")
        indexes = [models.Index(fields=["case", "kind"])]

    def __str__(self) -> str:
        return f"{self.kind} ({self.status}) for case #{self.case_id}"


class ForwardPaperPrediction(TimeStampedModel):
    """An immutable screenshot-driven forward prediction (Checkpoint 4).

    Written *before* the outcome is known, then locked: the prediction fields
    are frozen at creation, ``payload_sha256`` detects tampering, and
    :meth:`verify_outcome` is the only transition out of ``locked``.
    ``probability`` is only ever set when the caller supplies a calibrated,
    approved value; recognition alone never produces one.
    """

    case = models.ForeignKey(
        ScreenshotCase,
        on_delete=models.CASCADE,
        related_name="forward_predictions",
    )
    recognition_run = models.ForeignKey(
        ScreenshotRecognitionRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="forward_predictions",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="forward_paper_predictions",
    )
    strategy_key = models.CharField(max_length=16)
    strategy_id = models.CharField(max_length=24)
    #: The strategy definition version in force at decision time (audit trail).
    strategy_version = models.CharField(max_length=40, blank=True)

    instrument = models.CharField(max_length=32)
    timeframe = models.CharField(max_length=8)
    market_type = models.CharField(max_length=16)
    source = models.CharField(max_length=120, blank=True)

    direction = models.CharField(max_length=8, choices=PredictionDirection.CHOICES)
    #: The exact moment the decision was taken (before the outcome window).
    decision_timestamp = models.DateTimeField()
    entry_price = models.FloatField(null=True, blank=True)

    probability = models.FloatField(null=True, blank=True)
    probability_status = models.CharField(max_length=32, default="UNAVAILABLE_UNCALIBRATED")

    prediction_payload = models.JSONField(default=dict, blank=True)
    payload_sha256 = models.CharField(max_length=64)

    status = models.CharField(
        max_length=16, choices=PredictionStatus.CHOICES, default=PredictionStatus.LOCKED
    )

    class Meta:
        ordering = ("-decision_timestamp",)
        constraints = [
            models.UniqueConstraint(
                fields=("case", "strategy_key"),
                name="uniq_forward_prediction_per_case_strategy",
            )
        ]
        indexes = [models.Index(fields=["owner", "status"])]

    def __str__(self) -> str:
        return f"{self.strategy_id} {self.direction} @ {self.decision_timestamp:%Y-%m-%d %H:%M}"

    #: Frozen from creation.
    PROTECTED_FIELDS = (
        "case_id",
        "recognition_run_id",
        "strategy_key",
        "strategy_id",
        "strategy_version",
        "instrument",
        "timeframe",
        "market_type",
        "source",
        "direction",
        "decision_timestamp",
        "entry_price",
        "probability",
        "probability_status",
        "prediction_payload",
        "payload_sha256",
    )
    #: Frozen once the outcome is verified.
    OUTCOME_FIELDS = ("status",)

    _verification_in_progress = False

    def verify_integrity(self) -> bool:
        """True when the stored payload still matches its creation digest."""
        return self.payload_sha256 == case_payload_digest(self.prediction_payload)

    def verify_outcome(self, *, verdict: str) -> None:
        """Move out of ``locked`` exactly once, to a terminal status.

        Only the verification service calls this, after an outcome has been
        independently checked against the correct feed. A ``locked`` record can
        only ever transition once.
        """
        if self.status != PredictionStatus.LOCKED:
            raise PredictionLockedError(
                "prediction is already terminal; verified outcomes are immutable"
            )
        if verdict not in (
            PredictionStatus.VERIFIED,
            PredictionStatus.UNVERIFIED,
            PredictionStatus.TIE,
        ):
            raise PredictionLockedError(f"invalid terminal verdict: {verdict!r}")
        self._verification_in_progress = True
        try:
            self.status = verdict
            self.save(update_fields=["status", "updated_at"])
        finally:
            self._verification_in_progress = False

    def save(self, *args, **kwargs):  # type: ignore[override]
        if self._verification_in_progress:
            return super().save(*args, **kwargs)

        if not self.payload_sha256:
            self.payload_sha256 = case_payload_digest(self.prediction_payload)

        if self.pk is not None:
            previous = (
                ForwardPaperPrediction.objects.filter(pk=self.pk)
                .values(*self.PROTECTED_FIELDS, *self.OUTCOME_FIELDS)
                .first()
            )
            if previous is not None:
                for field_name in self.PROTECTED_FIELDS:
                    if previous[field_name] != getattr(self, field_name):
                        raise PredictionLockedError(
                            f"{field_name} is immutable: forward predictions are "
                            "locked before the outcome is known"
                        )
                if previous["status"] != self.status:
                    raise PredictionLockedError(
                        "status may only change through verify_outcome()"
                    )
        return super().save(*args, **kwargs)

    @property
    def is_locked(self) -> bool:
        return self.status == PredictionStatus.LOCKED


class OutcomeVerification(TimeStampedModel):
    """Independent outcome verification for a forward prediction (Checkpoint 5).

    Written by :class:`~apps.screenshot_eval.services.outcome_verification.OutcomeVerificationService`.
    The verdict is ``verified`` only when the exact matching feed supplied a
    settlement quote; an OTC prediction checked with MT5/regular data is
    ``refused`` (``INCOMPATIBLE_FEEDS``) and never coerced. Ties and unresolved
    outcomes are recorded as themselves and excluded from verified accuracy.
    """

    prediction = models.OneToOneField(
        ForwardPaperPrediction,
        on_delete=models.CASCADE,
        related_name="outcome",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="outcome_verifications",
    )
    verdict = models.CharField(max_length=16, choices=OutcomeVerdict.CHOICES)
    status = models.CharField(max_length=16, choices=PredictionStatus.CHOICES)

    feed = models.CharField(max_length=120, blank=True)
    feed_market_type = models.CharField(max_length=16, blank=True)
    entry_quote = models.FloatField(null=True, blank=True)
    settlement_quote = models.FloatField(null=True, blank=True)
    outcome_timestamp = models.DateTimeField(null=True, blank=True)

    reason_code = models.CharField(max_length=40, blank=True)
    reason = models.CharField(max_length=240, blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    verified_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["verdict"])]

    def __str__(self) -> str:
        return f"{self.prediction_id}: {self.verdict}"

    @property
    def counts_as_verified(self) -> bool:
        """Only CORRECT/INCORRECT/TIE verdicts may enter accuracy figures."""
        return self.verdict in (
            OutcomeVerdict.CORRECT,
            OutcomeVerdict.INCORRECT,
            OutcomeVerdict.TIE,
        )


class ReviewQueueItem(TimeStampedModel):
    """An error-review queue entry (Checkpoint 7).

    One row per detected problem (misidentified pattern, wrong breakout, false
    level, missing confirmation, wrong timeframe, contradictory evidence, wrong
    outcome, low vision confidence). A reviewer can *correct a label* here;
    the correction is stored on the queue item and never rewrites the original
    prediction or recognition record.
    """

    class Kind:
        MISIDENTIFIED_PATTERN = "misidentified_pattern"
        INCORRECT_BREAKOUT = "incorrect_breakout"
        FALSE_LEVEL = "false_support_resistance"
        MISSING_CONFIRMATION = "missing_confirmation_candle"
        WRONG_TIMEFRAME = "wrong_timeframe"
        CONTRADICTORY_EVIDENCE = "contradictory_evidence"
        INCORRECT_OUTCOME = "incorrect_outcome"
        VISION_UNCERTAINTY = "vision_model_uncertainty"
        INCOMPLETE_FORMATION = "incomplete_formation"

        CHOICES = (
            (MISIDENTIFIED_PATTERN, "Misidentified candlestick pattern"),
            (INCORRECT_BREAKOUT, "Incorrect breakout detection"),
            (FALSE_LEVEL, "False support/resistance level"),
            (MISSING_CONFIRMATION, "Missing confirmation candle"),
            (WRONG_TIMEFRAME, "Wrong timeframe interpretation"),
            (CONTRADICTORY_EVIDENCE, "Contradictory strategy evidence"),
            (INCORRECT_OUTCOME, "Incorrect outcome"),
            (VISION_UNCERTAINTY, "Vision-model uncertainty"),
            (INCOMPLETE_FORMATION, "Incomplete formation"),
        )

    class State:
        OPEN = "open"
        IN_REVIEW = "in_review"
        RESOLVED = "resolved"
        DISMISSED = "dismissed"

        CHOICES = (
            (OPEN, "Open"),
            (IN_REVIEW, "In review"),
            (RESOLVED, "Resolved"),
            (DISMISSED, "Dismissed"),
        )

    case = models.ForeignKey(
        ScreenshotCase,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="review_items",
    )
    recognition = models.ForeignKey(
        ScreenshotRecognition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review_items",
    )
    prediction = models.ForeignKey(
        ForwardPaperPrediction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review_items",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="review_queue_items",
    )
    kind = models.CharField(max_length=32, choices=Kind.CHOICES)
    state = models.CharField(max_length=16, choices=State.CHOICES, default=State.OPEN)
    summary = models.CharField(max_length=240)
    detail = models.JSONField(default=dict, blank=True)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_review_items",
    )
    #: Reviewer correction (e.g. a corrected label). Stored here only; the
    #: original prediction/recognition rows are never mutated.
    correction = models.JSONField(default=dict, blank=True)
    resolution_note = models.CharField(max_length=400, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_review_items",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["state", "kind"]),
            models.Index(fields=["owner", "state"]),
        ]

    def __str__(self) -> str:
        return f"[{self.state}] {self.kind}: {self.summary}"


__all__ = [
    "ChartAnnotation",
    "ForwardPaperPrediction",
    "OutcomeVerification",
    "PredictionLockedError",
    "ReviewQueueItem",
    "ScreenshotCase",
    "ScreenshotRecognition",
    "ScreenshotRecognitionRun",
    "case_payload_digest",
]
