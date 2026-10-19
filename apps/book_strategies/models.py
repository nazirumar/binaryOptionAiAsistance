# book_strategies/models.py
"""Persistent book-strategy knowledge and detection records (Phase 13)."""

from __future__ import annotations

import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.strategy_knowledge.models import StrategyVersion


class BookStrategy(TimeStampedModel):
    """One strategy extracted from the Binary Options Trading Bible.

    Rows are seeded from the immutable catalog in
    ``apps.book_strategies.constants``. A book strategy can influence live
    directional decisions ONLY after ``decision_use_approved`` is set - which
    requires documented validation and explicit human approval. Experimental
    entries stay visible for education and never affect trade decisions.
    """

    number = models.PositiveSmallIntegerField()
    key = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=160)
    chapter = models.CharField(max_length=8)
    pdf_pages = models.CharField(max_length=40)
    market_types = models.JSONField(default=list, blank=True)
    trade_type = models.CharField(max_length=20, blank=True)
    requirements = models.JSONField(default=list, blank=True)
    confirmation_rule = models.TextField(blank=True)
    invalidation_rules = models.JSONField(default=list, blank=True)
    mtg_policy = models.CharField(max_length=200, blank=True)
    ambiguities = models.JSONField(default=list, blank=True)
    contradictions = models.JSONField(default=list, blank=True)
    illustration_evidence = models.TextField(blank=True)
    #: Registered detector ("" = catalogued only, no deterministic detection).
    detector_key = models.CharField(max_length=32, blank=True, default="")
    priority = models.BooleanField(default=False)
    #: Furthest COMPLETED research stage; never skipped or fabricated.
    research_status = models.CharField(
        max_length=32,
        choices=[
            ("extracted", "Extracted from book"),
            ("implemented", "Implemented"),
            ("recognition_tested", "Recognition tested"),
            ("backtested", "Historically backtested"),
            ("oos_validated", "Out-of-sample validated"),
            ("approved", "Approved for decision use"),
        ],
        default="extracted",
    )
    #: Admin switch for whether this strategy appears in recognition runs.
    #: It never enables trading - it only controls recognition participation.
    recognition_enabled = models.BooleanField(default=False)
    #: The ONLY switch that could ever affect directional decisions, and it
    #: must stay False until documented validation + explicit approval.
    decision_use_approved = models.BooleanField(default=False)
    validation_notes = models.TextField(blank=True)
    version = models.ForeignKey(
        StrategyVersion,
        on_delete=models.PROTECT,
        related_name="book_strategies",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("chapter", "number", "key")

    def __str__(self) -> str:
        return f"{self.key} - {self.name}"

    @property
    def status_label(self) -> str:
        """Explicit human label; book entries are never 'approved knowledge'."""
        if self.decision_use_approved:
            return "Approved for decision use"
        return f"Book extraction ({self.get_research_status_display()})"


class BookStrategyDetection(TimeStampedModel):
    """One evaluation of a book strategy against candle/visual evidence.

    ``decision`` is always NO_TRADE and ``probability`` always None: a
    recognised pattern is an observation, never a prediction.
    """

    strategy = models.ForeignKey(
        BookStrategy, on_delete=models.CASCADE, related_name="detections"
    )
    #: Optional link to a screenshot analysis (book candidates from vision).
    analysis = models.ForeignKey(
        "chart_vision.ScreenshotAnalysis",
        on_delete=models.CASCADE,
        related_name="book_detections",
        null=True,
        blank=True,
    )
    state = models.CharField(max_length=32)
    direction = models.CharField(max_length=10, default="neutral")
    observed_evidence = models.JSONField(default=list, blank=True)
    missing_conditions = models.JSONField(default=list, blank=True)
    contradictions = models.JSONField(default=list, blank=True)
    candle_refs = models.JSONField(default=list, blank=True)
    reference_level = models.FloatField(null=True, blank=True)
    level_kind = models.CharField(max_length=60, blank=True)
    stochastic_supported = models.BooleanField(null=True, blank=True)
    data_verification = models.CharField(max_length=32)
    decision = models.CharField(max_length=16, default="NO_TRADE")
    probability = models.FloatField(null=True, blank=True)
    probability_status = models.CharField(
        max_length=40, default="UNAVAILABLE_UNCALIBRATED"
    )
    instrument = models.CharField(max_length=40, blank=True)
    timeframe = models.CharField(max_length=10, blank=True)
    market_type = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.strategy.key} [{self.state}]"


def payload_digest(payload: dict) -> str:
    """Canonical SHA-256 of a prediction payload (sorted keys, ASCII-safe)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PredictionImmutableError(ValidationError):
    """Raised when an immutable prediction field would be changed.

    Pre-outcome fields are frozen the moment a paper prediction is written, so
    a prediction can never be rewritten after its outcome becomes known; and a
    resolved outcome (or a verified settlement) can never be rewritten either.
    """


class PaperForwardPrediction(TimeStampedModel):
    """Immutable pre-outcome paper prediction (Phase 13, requirement 8).

    Written while the outcome candle does not exist yet, then frozen: the
    prediction fields can never change, ``resolve()`` is the only transition
    out of ``pending``, and ``payload_sha256`` allows later tamper detection.
    These records are research only - they never change ``research_status``,
    ``decision_use_approved`` or any decision.
    """

    PENDING = "pending"
    RESOLVED = "resolved"
    STATUS_CHOICES = ((PENDING, "Awaiting outcome"), (RESOLVED, "Outcome recorded"))

    strategy = models.ForeignKey(
        BookStrategy, on_delete=models.CASCADE, related_name="paper_predictions"
    )
    instrument = models.CharField(max_length=32)
    timeframe = models.CharField(max_length=8)
    market_type = models.CharField(max_length=16, blank=True)
    #: Provenance of the candles the prediction was recorded from, e.g.
    #: "mt5:EURUSD:M5" or "historical_import:<name>".
    source = models.CharField(max_length=120)
    detector_key = models.CharField(max_length=32)

    direction = models.CharField(max_length=8, choices=(("bullish", "Bullish"), ("bearish", "Bearish")))
    signal_candle_open_time = models.DateTimeField()
    signal_candle_close_time = models.DateTimeField()
    signal_close_price = models.FloatField()
    prediction_payload = models.JSONField(default=dict, blank=True)
    payload_sha256 = models.CharField(max_length=64)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    outcome_candle_open_time = models.DateTimeField(null=True, blank=True)
    outcome_close_price = models.FloatField(null=True, blank=True)
    outcome_up = models.BooleanField(null=True, blank=True)
    outcome_correct = models.BooleanField(null=True, blank=True)
    outcome_basis = models.CharField(
        max_length=64, default="next_candle_close_vs_signal_close"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    #: Settlement is only ever filled from platform quotes (see settlement
    #: service); "not_evaluated" / "unverifiable" are the honest defaults.
    settlement_status = models.CharField(max_length=24, default="not_evaluated")
    settlement = models.JSONField(default=dict, blank=True)

    #: Not a field: skips the immutability guard while resolve() runs its
    #: single, validated pending -> resolved transition.
    _resolution_in_progress = False

    #: Frozen from creation: identity, provenance and the prediction itself.
    PROTECTED_FIELDS = (
        "strategy_id",
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
        "outcome_basis",
    )
    #: Frozen once the outcome is recorded.
    OUTCOME_FIELDS = (
        "status",
        "outcome_candle_open_time",
        "outcome_close_price",
        "outcome_up",
        "outcome_correct",
        "resolved_at",
    )
    #: Settlement becomes frozen once it is verified (WIN/LOSS/TIE); a
    #: non-verified record may be re-evaluated when quotes arrive later.
    VERIFIED_SETTLEMENT_STATES = ("win", "loss", "tie")

    class Meta:
        ordering = ("-signal_candle_open_time",)
        constraints = [
            models.UniqueConstraint(
                fields=("strategy", "signal_candle_open_time"),
                name="uniq_paper_prediction_per_signal_candle",
            )
        ]

    def __str__(self) -> str:
        return f"{self.strategy.key} {self.direction} @ {self.signal_candle_open_time:%Y-%m-%d %H:%M} [{self.status}]"

    def verify_integrity(self) -> bool:
        """True when the stored payload still matches its creation digest."""
        return self.payload_sha256 == payload_digest(self.prediction_payload)

    def resolve(
        self,
        *,
        outcome_candle: dict,
        resolved_at=None,
    ) -> None:
        """Record the outcome exactly once, from a completed outcome candle.

        The outcome candle must open exactly when the signal candle closes
        (the next candle of the same timeframe) and must be complete; nothing
        here accepts a forming candle or an off-by-one window.
        """
        if self.status != self.PENDING:
            raise PredictionImmutableError(
                "prediction already resolved; resolved outcomes are immutable"
            )
        if not outcome_candle.get("complete", outcome_candle.get("is_complete", False)):
            raise PredictionImmutableError(
                "outcome candle is not complete - outcomes are never read from a forming candle"
            )
        outcome_open = outcome_candle.get("open_time")
        if outcome_open is None or outcome_open != self.signal_candle_close_time:
            raise PredictionImmutableError(
                "outcome candle window mismatch: it must open exactly when the "
                "signal candle closes"
            )
        outcome_close = float(outcome_candle["close"])
        self._resolution_in_progress = True
        try:
            self.outcome_candle_open_time = outcome_open
            self.outcome_close_price = outcome_close
            self.outcome_up = outcome_close > self.signal_close_price
            self.outcome_correct = (self.direction == "bullish") == self.outcome_up
            self.resolved_at = resolved_at or timezone.now()
            self.status = self.RESOLVED
            self.save()
        finally:
            self._resolution_in_progress = False

    def save(self, *args, **kwargs):  # type: ignore[override]
        if self._resolution_in_progress:
            if (
                self.status != self.RESOLVED
                or self.outcome_up is None
                or self.outcome_candle_open_time is None
                or self.resolved_at is None
            ):
                raise PredictionImmutableError("incomplete resolution rejected")
            return super().save(*args, **kwargs)

        if not self.payload_sha256:
            self.payload_sha256 = payload_digest(self.prediction_payload)

        if self.pk is not None:
            previous = (
                PaperForwardPrediction.objects.filter(pk=self.pk)
                .values(*self.PROTECTED_FIELDS, *self.OUTCOME_FIELDS, "settlement_status")
                .first()
            )
            if previous is not None:
                for field_name in self.PROTECTED_FIELDS:
                    if previous[field_name] != getattr(self, field_name):
                        raise PredictionImmutableError(
                            f"{field_name} is immutable: paper predictions are "
                            "frozen before the outcome is known"
                        )
                if previous["status"] != self.status:
                    raise PredictionImmutableError(
                        "status may only change through resolve()"
                    )
                for field_name in self.OUTCOME_FIELDS:
                    if field_name == "status":
                        continue
                    if previous[field_name] != getattr(self, field_name):
                        raise PredictionImmutableError(
                            f"{field_name} is immutable: outcomes are recorded "
                            "once through resolve() and never rewritten"
                        )
                if (
                    previous["settlement_status"] in self.VERIFIED_SETTLEMENT_STATES
                    and previous["settlement_status"] != self.settlement_status
                ):
                    raise PredictionImmutableError(
                        "verified settlement is immutable; it may only be "
                        "written once from platform quotes"
                    )
        return super().save(*args, **kwargs)
