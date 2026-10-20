# live_signals/services/dashboard.py
"""Read-model builders for the Live Signals dashboard (Phase 15, cp 5-7).

Everything here reads **real persisted rows** — monitors, signals, alerts. No
fictional price, signal or statistic is produced: an empty feed is shown as
empty, an unavailable feed is shown as unavailable, and metrics are computed
from the same rows the tables render.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Count, Q

from apps.live_signals.constants import (
    FeedState,
    SignalCategory,
    SignalStatus,
)
from apps.live_signals.models import (
    InstrumentMonitor,
    LiveSignal,
    SignalAlert,
)
from apps.live_signals.services.metrics import (
    directional_metrics,
    recognition_metrics,
)


@dataclass(slots=True)
class SignalFilters:
    """Filter state for the signal list; all fields optional."""

    strategy: str = ""
    instrument: str = ""
    timeframe: str = ""
    category: str = ""
    status: str = ""
    direction: str = ""
    outcome: str = ""


def _visible_signals(user, filters: SignalFilters):
    """Signals a user may see, honouring their preferences as *narrowing*.

    System (owner-null) signals are shared; a user's own signals are included.
    ``only_approved`` hides pattern alerts from *this user's view* without
    changing the underlying records.
    """
    qs = LiveSignal.objects.select_related("monitor").filter(
        Q(owner__isnull=True) | Q(owner=user)
    )
    if filters.strategy:
        qs = qs.filter(strategy_key=filters.strategy)
    if filters.instrument:
        qs = qs.filter(instrument=filters.instrument)
    if filters.timeframe:
        qs = qs.filter(timeframe=filters.timeframe)
    if filters.category:
        qs = qs.filter(category=filters.category)
    if filters.status:
        qs = qs.filter(status=filters.status)
    if filters.outcome:
        qs = qs.filter(outcome_status=filters.outcome)
    if filters.direction:
        qs = qs.filter(direction=filters.direction)

    settings_obj = getattr(user, "live_signal_settings", None)
    if settings_obj is not None:
        if settings_obj.only_approved:
            qs = qs.filter(category=SignalCategory.RESEARCH_VALIDATED)
        elif not settings_obj.show_experimental:
            qs = qs.exclude(category=SignalCategory.EXPERIMENTAL_PATTERN)
    return qs


def build_dashboard(user, filters: SignalFilters | None = None) -> dict:
    """Assemble the whole dashboard context from real data."""
    filters = filters or SignalFilters()
    signals = _visible_signals(user, filters)

    monitors = list(InstrumentMonitor.objects.all())
    active_monitors = [m for m in monitors if m.enabled]
    unavailable = [m for m in monitors if m.feed_state in (FeedState.UNAVAILABLE, FeedState.INCOMPATIBLE)]
    stale = [m for m in monitors if m.feed_state == FeedState.STALE]

    last_update = max(
        (m.last_successful_candle_update for m in monitors if m.last_successful_candle_update),
        default=None,
    )

    counts = signals.aggregate(
        confirmed=Count("id", filter=Q(status=SignalStatus.CONFIRMED_PATTERN)),
        directional=Count("id", filter=Q(category=SignalCategory.RESEARCH_VALIDATED)),
        forming=Count(
            "id", filter=Q(status__in=(SignalStatus.FORMING, SignalStatus.AWAITING_CONFIRMATION))
        ),
        invalidated=Count("id", filter=Q(status=SignalStatus.INVALIDATED)),
    )

    recent = list(signals[:50])
    unread_alerts = (
        SignalAlert.objects.filter(user=user, read_at__isnull=True).count()
        if getattr(user, "is_authenticated", False)
        else 0
    )

    return {
        "monitors": monitors,
        "active_monitors": active_monitors,
        "unavailable_monitors": unavailable,
        "stale_monitors": stale,
        "last_update": last_update,
        "new_signal_count": counts["confirmed"] or 0,
        "confirmed_patterns": counts["confirmed"] or 0,
        "directional_signals": counts["directional"] or 0,
        "forming_count": counts["forming"] or 0,
        "invalidated_count": counts["invalidated"] or 0,
        "recent_signals": recent,
        "recognitions": recognition_metrics(queryset=signals).as_dict(),
        "directionals": directional_metrics(queryset=signals).as_dict(),
        "unread_alerts": unread_alerts,
        "filters": filters,
        "filter_options": _filter_options(signals),
    }


def _filter_options(signals) -> dict:
    """Distinct values actually present (so filters never offer empty choices)."""
    return {
        "strategies": list(
            signals.values_list("strategy_key", "strategy_name")
            .order_by("strategy_key")
            .distinct()
        ),
        "instruments": sorted(
            {v for v in signals.values_list("instrument", flat=True) if v}
        ),
        "timeframes": sorted(
            {v for v in signals.values_list("timeframe", flat=True) if v}
        ),
    }


def signal_detail(user, signal_id: int) -> LiveSignal | None:
    """One signal the user may see, or ``None`` (owner-scoped, 404 upstream)."""
    return (
        LiveSignal.objects.select_related("monitor")
        .filter(Q(owner__isnull=True) | Q(owner=user), pk=signal_id)
        .first()
    )


@dataclass(slots=True)
class OutcomeSummary:
    """Aggregate paper outcomes for the recognition/directional split."""

    recognition: dict = field(default_factory=dict)
    directional: dict = field(default_factory=dict)
    by_strategy: list = field(default_factory=list)
    by_instrument: list = field(default_factory=list)
    by_timeframe: list = field(default_factory=list)


def build_outcomes(user) -> OutcomeSummary:
    """Metrics strict-split view for the outcomes section."""
    from apps.live_signals.services.metrics import (
        metrics_by_instrument,
        metrics_by_strategy,
        metrics_by_timeframe,
    )

    signals = LiveSignal.objects.filter(Q(owner__isnull=True) | Q(owner=user))
    return OutcomeSummary(
        recognition=recognition_metrics(queryset=signals).as_dict(),
        directional=directional_metrics(queryset=signals).as_dict(),
        by_strategy=metrics_by_strategy(queryset=signals),
        by_instrument=metrics_by_instrument(queryset=signals),
        by_timeframe=metrics_by_timeframe(queryset=signals),
    )


__all__ = [
    "OutcomeSummary",
    "SignalFilters",
    "build_dashboard",
    "build_outcomes",
    "signal_detail",
]
