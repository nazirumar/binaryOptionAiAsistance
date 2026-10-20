# live_signals/models.py
"""Persistent state for the Phase 15 live-signals monitor.

Design rules enforced here:

* A :class:`LiveSignal` is **immutable** once written: its identity, provenance,
  direction and evidence are frozen exactly as detected. Only the outcome
  fields may be filled later, and only once, through :meth:`LiveSignal.record_outcome`.
* Every monitor record is **owner-scoped** where it belongs to a user; the
  system monitors themselves are owner-null (shared) so they can run without a
  logged-in user present.
* Approval is never inferred: a directional signal can only exist when the
  originating ``BookStrategy.decision_use_approved`` was True at detection time,
  and that flag is copied onto the row for audit.
"""

from __future__ import annotations

import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.live_signals.constants import (
    DEFAULT_EXPIRY_CANDLES,
    PROBABILITY_STATUS,
    FeedState,
    MonitorState,
    OutcomeStatus,
    SignalCategory,
    SignalDirection,
    SignalStatus,
)


def payload_digest(payload: dict) -> str:
    """Canonical SHA-256 of a signal payload (sorted keys, ASCII-safe)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SignalImmutableError(ValidationError):
    """Raised when a frozen signal field would be changed after creation."""


class InstrumentMonitor(TimeStampedModel):
    """One instrument/timeframe the system watches for fresh closed candles.

    Monitors are deduplicated by ``(canonical_instrument, timeframe, market_type)``
    so two users watching the same market share one row; ownership lives on the
    per-user :class:`UserMonitorSettings` row instead.
    """

    canonical_instrument = models.CharField(max_length=32, db_index=True)
    timeframe = models.CharField(max_length=4, db_index=True)
    #: ``regular`` or ``otc`` — never interchanged (see market_data symbol_mapper).
    market_type = models.CharField(max_length=16, default="regular")
    #: Broker symbol the feed actually serves (e.g. ``EURUSDm``). Blank until mapped.
    broker_symbol = models.CharField(max_length=64, blank=True)
    provider = models.CharField(max_length=32, default="db")
    is_otc = models.BooleanField(default=False)

    enabled = models.BooleanField(default=True)
    state = models.CharField(
        max_length=16, choices=MonitorState.CHOICES, default=MonitorState.IDLE
    )
    feed_state = models.CharField(
        max_length=16, choices=FeedState.CHOICES, default=FeedState.UNAVAILABLE
    )

    #: Tracking for duplicate prevention and restart recovery.
    last_evaluated_candle_open_time = models.DateTimeField(null=True, blank=True)
    last_successful_candle_update = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    consecutive_failures = models.PositiveSmallIntegerField(default=0)
    signals_detected = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("canonical_instrument", "timeframe", "market_type")
        constraints = [
            models.UniqueConstraint(
                fields=("canonical_instrument", "timeframe", "market_type"),
                name="uniq_monitor_instrument_timeframe_market",
            )
        ]

    def __str__(self) -> str:
        return f"{self.canonical_instrument}/{self.timeframe} ({self.market_type})"


class LiveSignal(TimeStampedModel):
    """One detected setup, frozen at detection time.

    The row records *what was observed*, never a probability and never a trade.
    ``direction`` is only populated for ``RESEARCH_VALIDATED`` signals whose
    strategy was approved at detection time.
    """

    #: Identity / provenance (frozen).
    monitor = models.ForeignKey(
        InstrumentMonitor,
        on_delete=models.CASCADE,
        related_name="signals",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="live_signals",
        help_text="Null for a shared/system-detected signal.",
    )
    instrument = models.CharField(max_length=32, db_index=True)
    timeframe = models.CharField(max_length=4, db_index=True)
    market_type = models.CharField(max_length=16, default="regular")
    provider = models.CharField(max_length=32, default="db")

    strategy_key = models.CharField(max_length=32, db_index=True)
    strategy_name = models.CharField(max_length=160, blank=True)
    strategy_version = models.CharField(max_length=32, blank=True)
    detector_key = models.CharField(max_length=32, blank=True)

    category = models.CharField(
        max_length=32, choices=SignalCategory.CHOICES, db_index=True
    )
    status = models.CharField(max_length=32, choices=SignalStatus.CHOICES, db_index=True)
    #: Only ever bullish/bearish for approved directional signals.
    direction = models.CharField(max_length=8, choices=SignalDirection.CHOICES, default=SignalDirection.NONE)

    #: Candle bookkeeping (frozen).
    signal_candle_open_time = models.DateTimeField()
    signal_candle_close_time = models.DateTimeField()
    confirmation_candle_open_time = models.DateTimeField(null=True, blank=True)
    candle_refs = models.JSONField(default=list, blank=True)

    #: Evidence (frozen).
    observed_evidence = models.JSONField(default=list, blank=True)
    missing_conditions = models.JSONField(default=list, blank=True)
    invalidation_evidence = models.JSONField(default=list, blank=True)
    reference_level = models.FloatField(null=True, blank=True)
    level_kind = models.CharField(max_length=60, blank=True)

    #: Governance (frozen).
    approval_status = models.CharField(max_length=32, default="not_approved")
    decision_use_approved = models.BooleanField(default=False)
    feed_compatibility = models.CharField(max_length=24, default="unverified")
    data_verification = models.CharField(max_length=32, blank=True)
    #: Human-readable expiry rule, e.g. "expires 1 M5 candle after confirmation".
    expiry_rule = models.CharField(max_length=160, blank=True)
    expires_after_candles = models.PositiveSmallIntegerField(default=DEFAULT_EXPIRY_CANDLES)
    #: Exactly what the engine would have decided; always NO_TRADE for patterns.
    decision = models.CharField(max_length=16, default="NO_TRADE")
    probability_status = models.CharField(max_length=40, default=PROBABILITY_STATUS)

    payload_sha256 = models.CharField(max_length=64, blank=True)
    detected_at = models.DateTimeField(default=timezone.now, db_index=True)

    #: Outcome (the ONLY mutable part, filled once).
    outcome_status = models.CharField(
        max_length=24, choices=OutcomeStatus.CHOICES, default=OutcomeStatus.PENDING
    )
    outcome_candle_open_time = models.DateTimeField(null=True, blank=True)
    outcome_candle_close_price = models.FloatField(null=True, blank=True)
    outcome_correct = models.BooleanField(null=True, blank=True)
    outcome_note = models.CharField(max_length=160, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    #: Not a field: skips the immutability guard during record_outcome().
    _outcome_in_progress = False

    #: Frozen from creation.
    PROTECTED_FIELDS = (
        "monitor_id",
        "owner_id",
        "instrument",
        "timeframe",
        "market_type",
        "provider",
        "strategy_key",
        "strategy_name",
        "strategy_version",
        "detector_key",
        "category",
        "status",
        "direction",
        "signal_candle_open_time",
        "signal_candle_close_time",
        "confirmation_candle_open_time",
        "candle_refs",
        "observed_evidence",
        "missing_conditions",
        "invalidation_evidence",
        "reference_level",
        "level_kind",
        "approval_status",
        "decision_use_approved",
        "feed_compatibility",
        "data_verification",
        "expiry_rule",
        "expires_after_candles",
        "decision",
        "probability_status",
        "payload_sha256",
        "detected_at",
    )
    #: Frozen once an outcome is recorded.
    OUTCOME_FIELDS = (
        "outcome_status",
        "outcome_candle_open_time",
        "outcome_candle_close_price",
        "outcome_correct",
        "outcome_note",
        "resolved_at",
    )
    #: Outcome states that are final and may not be rewritten.
    FINAL_OUTCOME_STATES = (
        OutcomeStatus.VERIFIED_CORRECT,
        OutcomeStatus.VERIFIED_INCORRECT,
        OutcomeStatus.TIE,
        OutcomeStatus.UNVERIFIABLE,
    )

    class Meta:
        ordering = ("-detected_at", "-id")
        constraints = [
            # Duplicate prevention: one signal per
            # (monitor, strategy, signal candle, status).
            models.UniqueConstraint(
                fields=("monitor", "strategy_key", "signal_candle_open_time", "status"),
                name="uniq_live_signal_per_monitor_strategy_candle_status",
            )
        ]
        indexes = [
            models.Index(fields=("owner", "-detected_at")),
            models.Index(fields=("category", "-detected_at")),
            models.Index(fields=("instrument", "timeframe", "-detected_at")),
            models.Index(fields=("outcome_status", "signal_candle_close_time")),
        ]

    def __str__(self) -> str:
        return f"{self.strategy_key} {self.status} {self.instrument}/{self.timeframe}"

    @property
    def is_directional(self) -> bool:
        return (
            self.category == SignalCategory.RESEARCH_VALIDATED
            and self.direction in (SignalDirection.BULLISH, SignalDirection.BEARISH)
        )

    def verify_integrity(self) -> bool:
        """True when the stored payload still matches its creation digest."""
        return self.payload_sha256 == payload_digest(self._integrity_payload())

    def _integrity_payload(self) -> dict:
        """The canonical subset hashed at creation (provenance + evidence)."""
        return {
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "market_type": self.market_type,
            "strategy_key": self.strategy_key,
            "detector_key": self.detector_key,
            "category": self.category,
            "direction": self.direction,
            "signal_candle_open_time": str(self.signal_candle_open_time),
            "observed_evidence": self.observed_evidence,
            "candle_refs": self.candle_refs,
        }

    def record_outcome(
        self,
        *,
        outcome_status: str,
        outcome_candle_open_time=None,
        outcome_candle_close_price: float | None = None,
        outcome_correct: bool | None = None,
        outcome_note: str = "",
        resolved_at=None,
    ) -> None:
        """Record the paper outcome exactly once.

        A final outcome (verified/tie/unverifiable) can never be rewritten.
        """
        if self.outcome_status in self.FINAL_OUTCOME_STATES:
            raise SignalImmutableError(
                "outcome already recorded; final outcomes are immutable"
            )
        self._outcome_in_progress = True
        try:
            self.outcome_status = outcome_status
            self.outcome_candle_open_time = outcome_candle_open_time
            self.outcome_candle_close_price = outcome_candle_close_price
            self.outcome_correct = outcome_correct
            self.outcome_note = outcome_note
            self.resolved_at = resolved_at or timezone.now()
            self.save()
        finally:
            self._outcome_in_progress = False

    def save(self, *args, **kwargs):  # type: ignore[override]
        if self._outcome_in_progress:
            return super().save(*args, **kwargs)

        if not self.payload_sha256:
            self.payload_sha256 = payload_digest(self._integrity_payload())

        if self.pk is not None:
            previous = (
                LiveSignal.objects.filter(pk=self.pk)
                .values(*self.PROTECTED_FIELDS, *self.OUTCOME_FIELDS)
                .first()
            )
            if previous is not None:
                for field_name in self.PROTECTED_FIELDS:
                    if previous[field_name] != getattr(self, field_name):
                        raise SignalImmutableError(
                            f"{field_name} is immutable: a detected signal is "
                            "frozen at detection time and never rewritten"
                        )
                for field_name in self.OUTCOME_FIELDS:
                    if previous[field_name] != getattr(self, field_name):
                        raise SignalImmutableError(
                            "outcome fields may only change through record_outcome()"
                        )
        return super().save(*args, **kwargs)


class UserMonitorSettings(TimeStampedModel):
    """Owner-scoped monitoring preferences.

    These preferences shape *which of the already-safe signals a user sees*.
    They can never widen the approval gate: ``only_approved`` can hide pattern
    alerts, and ``show_experimental`` can reveal them, but no setting can turn
    an unapproved strategy into a directional signal.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="live_signal_settings",
    )
    #: Canonical instruments to watch (empty = use the system default set).
    instruments = models.JSONField(default=list, blank=True)
    #: Timeframes to watch, restricted to MONITORABLE_TIMEFRAMES.
    timeframes = models.JSONField(default=list, blank=True)
    #: Enabled strategy keys (empty = all recognition-enabled strategies).
    enabled_strategies = models.JSONField(default=list, blank=True)

    #: Alert preferences.
    alerts_enabled = models.BooleanField(default=True)
    browser_notifications = models.BooleanField(default=False)
    #: Show experimental (unapproved) pattern detections in the feed.
    show_experimental = models.BooleanField(default=True)
    #: Show ONLY research-validated directional signals.
    only_approved = models.BooleanField(default=False)

    class Meta:
        verbose_name = "live signal settings"
        verbose_name_plural = "live signal settings"

    def __str__(self) -> str:
        return f"Live-signal settings for {self.user}"


class SignalAlert(TimeStampedModel):
    """In-app notification for one confirmed event, deduplicated per event.

    The natural key ``(user, signal)`` guarantees a single alert per confirmed
    event even if the detector runs many times.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="signal_alerts",
    )
    signal = models.ForeignKey(
        LiveSignal,
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    title = models.CharField(max_length=160)
    body = models.CharField(max_length=300, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    #: Set when the browser-notification bridge reported it (best-effort).
    delivered_browser = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "signal"), name="uniq_alert_per_user_signal"
            )
        ]
        indexes = [models.Index(fields=("user", "read_at", "-created_at"))]

    def __str__(self) -> str:
        return f"Alert({self.user_id}, signal={self.signal_id})"

    @property
    def is_unread(self) -> bool:
        return self.read_at is None


__all__ = [
    "InstrumentMonitor",
    "LiveSignal",
    "SignalAlert",
    "SignalImmutableError",
    "UserMonitorSettings",
    "payload_digest",
]
