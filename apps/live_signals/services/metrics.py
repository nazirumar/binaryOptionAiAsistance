# live_signals/services/metrics.py
"""Paper-outcome metrics for live signals (Phase 15, checkpoint 7).

Two metric families are kept **strictly separate**, exactly as the brief
demands:

* *Recognition* metrics count how many patterns were detected and how many
  confirmed — these say nothing about correctness.
* *Directional* metrics score only ``RESEARCH_VALIDATED`` signals, using their
  next-candle paper outcomes, and are reported with a Wilson interval and an
  explicit insufficiency flag below the existing minimum-sample threshold.

No profitability is ever claimed. Unverifiable outcomes are counted separately
and never folded into the hit rate.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count, Q

from apps.book_strategies.services.validation import (
    DEFAULT_MIN_SIGNALS,
    wilson_interval,
)
from apps.live_signals.constants import (
    OutcomeStatus,
    SignalCategory,
    SignalStatus,
)
from apps.live_signals.models import LiveSignal


@dataclass(slots=True)
class RecognitionMetrics:
    """Detection counts — deliberately direction-free."""

    total_patterns: int = 0
    confirmed_patterns: int = 0
    forming: int = 0
    awaiting_confirmation: int = 0
    invalidated: int = 0
    expired: int = 0
    experimental: int = 0

    def as_dict(self) -> dict:
        return {
            "total_patterns": self.total_patterns,
            "confirmed_patterns": self.confirmed_patterns,
            "forming": self.forming,
            "awaiting_confirmation": self.awaiting_confirmation,
            "invalidated": self.invalidated,
            "expired": self.expired,
            "experimental": self.experimental,
        }


@dataclass(slots=True)
class DirectionalMetrics:
    """Paper performance of approved directional signals only."""

    total_eligible: int = 0
    resolved: int = 0
    confirmed_correct: int = 0
    confirmed_incorrect: int = 0
    ties: int = 0
    unverified: int = 0
    hit_rate: float | None = None
    wilson_low: float | None = None
    wilson_high: float | None = None
    insufficient: bool = True
    minimum_signals: int = DEFAULT_MIN_SIGNALS
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "total_eligible": self.total_eligible,
            "resolved": self.resolved,
            "confirmed_correct": self.confirmed_correct,
            "confirmed_incorrect": self.confirmed_incorrect,
            "ties": self.ties,
            "unverified": self.unverified,
            "hit_rate": self.hit_rate,
            "wilson_low": self.wilson_low,
            "wilson_high": self.wilson_high,
            "insufficient": self.insufficient,
            "minimum_signals": self.minimum_signals,
            "note": self.note,
        }


def _base_queryset(*, owner=None, monitor=None):
    qs = LiveSignal.objects.all()
    if owner is not None:
        qs = qs.filter(owner=owner)
    if monitor is not None:
        qs = qs.filter(monitor=monitor)
    return qs


def recognition_metrics(*, owner=None, monitor=None, queryset=None) -> RecognitionMetrics:
    """Count detections; never mixes in directional performance."""
    qs = queryset if queryset is not None else _base_queryset(owner=owner, monitor=monitor)
    counts = qs.aggregate(
        total=Count("id"),
        confirmed=Count("id", filter=Q(status=SignalStatus.CONFIRMED_PATTERN)),
        forming=Count("id", filter=Q(status=SignalStatus.FORMING)),
        awaiting=Count("id", filter=Q(status=SignalStatus.AWAITING_CONFIRMATION)),
        invalidated=Count("id", filter=Q(status=SignalStatus.INVALIDATED)),
        expired=Count("id", filter=Q(status=SignalStatus.EXPIRED)),
        experimental=Count(
            "id", filter=Q(category=SignalCategory.EXPERIMENTAL_PATTERN)
        ),
    )
    return RecognitionMetrics(
        total_patterns=counts["total"] or 0,
        confirmed_patterns=counts["confirmed"] or 0,
        forming=counts["forming"] or 0,
        awaiting_confirmation=counts["awaiting"] or 0,
        invalidated=counts["invalidated"] or 0,
        expired=counts["expired"] or 0,
        experimental=counts["experimental"] or 0,
    )


def directional_metrics(*, owner=None, monitor=None, queryset=None) -> DirectionalMetrics:
    """Score approved directional signals using paper next-candle outcomes."""
    qs = queryset if queryset is not None else _base_queryset(owner=owner, monitor=monitor)
    qs = qs.filter(category=SignalCategory.RESEARCH_VALIDATED)

    total = qs.count()
    counts = qs.aggregate(
        correct=Count("id", filter=Q(outcome_status=OutcomeStatus.VERIFIED_CORRECT)),
        incorrect=Count(
            "id", filter=Q(outcome_status=OutcomeStatus.VERIFIED_INCORRECT)
        ),
        ties=Count("id", filter=Q(outcome_status=OutcomeStatus.TIE)),
        unverified=Count("id", filter=Q(outcome_status=OutcomeStatus.UNVERIFIABLE)),
        pending=Count("id", filter=Q(outcome_status=OutcomeStatus.PENDING)),
    )
    resolved = (counts["correct"] or 0) + (counts["incorrect"] or 0)
    metrics = DirectionalMetrics(
        total_eligible=total,
        resolved=resolved,
        confirmed_correct=counts["correct"] or 0,
        confirmed_incorrect=counts["incorrect"] or 0,
        ties=counts["ties"] or 0,
        unverified=counts["unverified"] or 0,
    )
    if resolved:
        low, high = wilson_interval(metrics.confirmed_correct, resolved)
        metrics.hit_rate = metrics.confirmed_correct / resolved
        metrics.wilson_low = low
        metrics.wilson_high = high
    metrics.insufficient = resolved < DEFAULT_MIN_SIGNALS
    if metrics.insufficient:
        metrics.note = (
            f"fewer than {DEFAULT_MIN_SIGNALS} resolved directional signals; "
            "no performance conclusion is drawn"
        )
    return metrics


def metrics_by_strategy(*, owner=None, queryset=None) -> list[dict]:
    """Recognition + directional split per strategy (kept in separate keys)."""
    qs = queryset if queryset is not None else _base_queryset(owner=owner)
    keys = qs.values_list("strategy_key", flat=True).distinct()
    out: list[dict] = []
    for key in keys:
        sub = qs.filter(strategy_key=key)
        out.append(
            {
                "strategy_key": key,
                "recognition": recognition_metrics(queryset=sub).as_dict(),
                "directional": directional_metrics(queryset=sub).as_dict(),
            }
        )
    return out


def metrics_by_instrument(*, owner=None, queryset=None) -> list[dict]:
    qs = queryset if queryset is not None else _base_queryset(owner=owner)
    instruments = qs.values_list("instrument", flat=True).distinct()
    out: list[dict] = []
    for instrument in instruments:
        sub = qs.filter(instrument=instrument)
        out.append(
            {
                "instrument": instrument,
                "recognition": recognition_metrics(queryset=sub).as_dict(),
                "directional": directional_metrics(queryset=sub).as_dict(),
            }
        )
    return out


def metrics_by_timeframe(*, owner=None, queryset=None) -> list[dict]:
    qs = queryset if queryset is not None else _base_queryset(owner=owner)
    timeframes = qs.values_list("timeframe", flat=True).distinct()
    out: list[dict] = []
    for timeframe in timeframes:
        sub = qs.filter(timeframe=timeframe)
        out.append(
            {
                "timeframe": timeframe,
                "recognition": recognition_metrics(queryset=sub).as_dict(),
                "directional": directional_metrics(queryset=sub).as_dict(),
            }
        )
    return out


__all__ = [
    "DirectionalMetrics",
    "RecognitionMetrics",
    "directional_metrics",
    "metrics_by_instrument",
    "metrics_by_strategy",
    "metrics_by_timeframe",
    "recognition_metrics",
]
