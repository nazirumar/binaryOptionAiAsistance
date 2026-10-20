# live_signals/services/monitor.py
"""The live monitoring engine (Phase 15, checkpoints 3-4).

Responsibilities, each deliberately narrow:

* discover which instruments/timeframes are being watched (system monitors
  unioned with every user's :class:`~apps.live_signals.models.UserMonitorSettings`);
* ask the configured :class:`CandleProvider` for **closed** candles;
* skip candles that have already been evaluated (duplicate prevention);
* run every eligible strategy through the matching engine;
* persist new :class:`LiveSignal` rows, expiring the ones whose window passed;
* resolve paper outcomes one compatible candle later;
* keep monitor health (feed state, last update, bounded failure counters).

Nothing here invents data: a missing feed yields ``UNAVAILABLE``; an OTC
instrument with no compatible feed stays ``UNVERIFIABLE``; a forming candle is
never evaluated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.live_signals.constants import (
    TIMEFRAME_SECONDS,
    FeedState,
    MonitorState,
    OutcomeStatus,
    SignalStatus,
)
from apps.live_signals.models import (
    InstrumentMonitor,
    LiveSignal,
    UserMonitorSettings,
)
from apps.live_signals.services.matching import match_strategy
from apps.live_signals.services.providers import (
    ProviderCandle,
    get_provider,
)
from apps.market_data.constants import FeedCompatibility
from apps.market_data.services.symbol_mapper import (
    check_feed_type_compatibility,
    get_instrument,
)

logger = logging.getLogger(__name__)

#: How many closed candles to hand a detector. The book detectors need at most
#: ~17 for the stochastic gate plus the seed window; 60 is comfortably enough
#: and keeps queries bounded.
CANDLE_WINDOW = 60

#: A feed whose newest closed candle is older than this many periods is STALE.
STALE_AFTER_PERIODS = 3

#: Bounded retries: after this many consecutive failures a monitor is marked
#: ERROR and stops being retried until an operator re-enables it.
MAX_CONSECUTIVE_FAILURES = 5


@dataclass(slots=True)
class MonitorRunResult:
    """Summary of one monitor pass (also returned to callers/tests)."""

    monitor_id: int
    instrument: str
    timeframe: str
    feed_state: str
    evaluated: bool
    new_signals: int = 0
    expired: int = 0
    resolved: int = 0
    message: str = ""


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _instrument_is_otc(canonical: str) -> bool:
    try:
        return bool(get_instrument(canonical).is_otc)
    except Exception:
        return canonical.upper().endswith("_OTC")


def _feed_is_compatible(canonical: str, market_type: str) -> tuple[bool, str]:
    """Return ``(compatible, feed_compatibility_value)`` for a monitor.

    Uses the existing OTC-compatibility check so an OTC instrument is never
    satisfied by a regular feed.
    """
    feed_is_otc = market_type == "otc"
    try:
        compatibility = check_feed_type_compatibility(
            canonical, broker_is_otc=feed_is_otc
        )
    except Exception:
        return False, "unverified"
    if compatibility == FeedCompatibility.OTC_MISMATCH:
        return False, "incompatible"
    return True, compatibility


def default_monitors() -> list[tuple[str, str, str]]:
    """The system's default ``(instrument, timeframe, market_type)`` triples.

    Read from settings so an operator controls the watched set without code
    changes. Empty by default: with no configured feed the monitor reports
    ``UNAVAILABLE`` rather than pretending to watch anything.
    """
    from django.conf import settings

    entries = getattr(settings, "LIVE_SIGNAL_MONITORS", ()) or ()
    triples: list[tuple[str, str, str]] = []
    for entry in entries:
        if isinstance(entry, str):
            parts = entry.split(":")
            if len(parts) == 2:
                parts.append("regular")
            if len(parts) == 3:
                triples.append((parts[0], parts[1], parts[2]))
        elif isinstance(entry, (list, tuple)) and len(entry) == 3:
            triples.append((str(entry[0]), str(entry[1]), str(entry[2])))
    return triples


def ensure_monitors() -> list[InstrumentMonitor]:
    """Return the shared monitors, creating any default ones that are missing.

    Deduplicated by the model's unique constraint so concurrent workers do not
    create duplicates.
    """
    for canonical, timeframe, market_type in default_monitors():
        try:
            InstrumentMonitor.objects.get_or_create(
                canonical_instrument=canonical,
                timeframe=timeframe,
                market_type=market_type,
                defaults={
                    "provider": "db",
                    "is_otc": market_type == "otc",
                },
            )
        except IntegrityError:  # pragma: no cover - concurrent worker race
            pass
    return list(InstrumentMonitor.objects.all())


def watched_monitors_for_user(user) -> list[InstrumentMonitor]:
    """Monitors a user asked to watch, intersected with the system set.

    User settings can only *narrow* the monitored set; they can never add an
    instrument the system feed does not serve, and can never widen the
    approval gate.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    settings_obj = UserMonitorSettings.objects.filter(user=user).first()
    if settings_obj is None:
        return []
    qs = InstrumentMonitor.objects.all()
    if settings_obj.instruments:
        qs = qs.filter(canonical_instrument__in=settings_obj.instruments)
    if settings_obj.timeframes:
        qs = qs.filter(timeframe__in=settings_obj.timeframes)
    return list(qs)


def _eligible_strategies(enabled_keys: list[str] | None = None):
    """Recognition-enabled book strategies, optionally filtered by key."""
    from apps.book_strategies.models import BookStrategy

    qs = BookStrategy.objects.filter(recognition_enabled=True).select_related("version")
    if enabled_keys:
        qs = qs.filter(key__in=enabled_keys)
    return list(qs)


class LiveSignalMonitor:
    """Runs one pass over one monitor and persists what it honestly observed."""

    def __init__(self, provider_name: str = "db", *, provider=None) -> None:
        self.provider = provider or get_provider(provider_name)

    # -- feed ------------------------------------------------------------
    def fetch(self, monitor: InstrumentMonitor, *, now: datetime | None = None):
        return self.provider.fetch_closed(
            broker_symbol=monitor.broker_symbol,
            canonical_instrument=monitor.canonical_instrument,
            timeframe=monitor.timeframe,
            count=CANDLE_WINDOW,
            now=now,
        )

    # -- duplicate / freshness -------------------------------------------
    @staticmethod
    def _already_evaluated(monitor: InstrumentMonitor, candle: ProviderCandle) -> bool:
        """True when this monitor already processed this candle's open time."""
        return (
            monitor.last_evaluated_candle_open_time is not None
            and candle.open_time <= monitor.last_evaluated_candle_open_time
        )

    @staticmethod
    def _feed_stale(monitor: InstrumentMonitor, candle: ProviderCandle, now: datetime) -> bool:
        seconds = TIMEFRAME_SECONDS.get(monitor.timeframe, 60)
        age = (now - (candle.open_time + timedelta(seconds=seconds))).total_seconds()
        return age > seconds * STALE_AFTER_PERIODS

    # -- main pass --------------------------------------------------------
    def run_monitor(
        self, monitor: InstrumentMonitor, *, now: datetime | None = None
    ) -> MonitorRunResult:
        now = now or utc_now()
        result = MonitorRunResult(
            monitor_id=monitor.pk,
            instrument=monitor.canonical_instrument,
            timeframe=monitor.timeframe,
            feed_state=monitor.feed_state,
            evaluated=False,
        )

        compatible, compatibility = _feed_is_compatible(
            monitor.canonical_instrument, monitor.market_type
        )
        if not compatible:
            self._mark_feed(monitor, FeedState.INCOMPATIBLE, "incompatible feed")
            # No compatible feed can ever verify this instrument's outcomes:
            # existing pending signals are marked UNVERIFIABLE, never guessed.
            self._mark_unverifiable(monitor)
            result.feed_state = FeedState.INCOMPATIBLE
            result.message = "market-data feed is incompatible with the instrument"
            return result

        try:
            fetch = self.fetch(monitor, now=now)
        except Exception as exc:  # pragma: no cover - provider-dependent
            self._record_failure(monitor, f"provider error: {exc}")
            result.feed_state = FeedState.UNAVAILABLE
            result.message = str(exc)
            return result

        if not fetch.available or not fetch.candles:
            self._mark_feed(monitor, FeedState.UNAVAILABLE, fetch.message)
            result.feed_state = FeedState.UNAVAILABLE
            result.message = fetch.message
            return result

        latest = fetch.candles[-1]
        stale = self._feed_stale(monitor, latest, now)
        new_signals = 0
        evaluated_any = False

        if not self._already_evaluated(monitor, latest):
            new_signals = self._evaluate_candle(
                monitor, fetch.candles, compatibility, now
            )
            evaluated_any = True

        # Expire and resolve regardless (they act on existing rows).
        expired = self._expire_stale(monitor, fetch.candles, now)
        resolved = self._resolve_outcomes(monitor, fetch.candles)

        with transaction.atomic():
            monitor.refresh_from_db()
            monitor.last_evaluated_candle_open_time = max(
                latest.open_time,
                monitor.last_evaluated_candle_open_time or latest.open_time,
            )
            monitor.last_successful_candle_update = now
            monitor.last_run_at = now
            monitor.feed_state = FeedState.STALE if stale else FeedState.OK
            monitor.state = MonitorState.RUNNING
            monitor.consecutive_failures = 0
            monitor.last_error = ""
            monitor.signals_detected = LiveSignal.objects.filter(monitor=monitor).count()
            monitor.save(
                update_fields=[
                    "last_evaluated_candle_open_time",
                    "last_successful_candle_update",
                    "last_run_at",
                    "feed_state",
                    "state",
                    "consecutive_failures",
                    "last_error",
                    "signals_detected",
                    "updated_at",
                ]
            )

        result.feed_state = monitor.feed_state
        result.evaluated = evaluated_any
        result.new_signals = new_signals
        result.expired = expired
        result.resolved = resolved
        result.message = "stale feed" if stale else "ok"
        return result

    # -- detection --------------------------------------------------------
    def _evaluate_candle(
        self,
        monitor: InstrumentMonitor,
        candles: list[ProviderCandle],
        compatibility: str,
        now: datetime,
    ) -> int:
        created = 0
        strategies = _eligible_strategies()
        instrument_is_otc = monitor.is_otc or _instrument_is_otc(
            monitor.canonical_instrument
        )
        for strategy in strategies:
            matched = match_strategy(
                strategy,
                candles,
                instrument=monitor.canonical_instrument,
                timeframe=monitor.timeframe,
                market_type=monitor.market_type,
                feed_is_otc=monitor.market_type == "otc",
                instrument_is_otc=instrument_is_otc,
            )
            if matched is None:
                continue
            if self._persist_signal(monitor, matched, now):
                created += 1
        return created

    @staticmethod
    def _persist_signal(monitor: InstrumentMonitor, matched, now: datetime) -> bool:
        """Insert a signal idempotently; a duplicate candle is a no-op."""
        try:
            with transaction.atomic():
                LiveSignal.objects.create(
                    monitor=monitor,
                    owner=None,
                    instrument=monitor.canonical_instrument,
                    timeframe=monitor.timeframe,
                    market_type=monitor.market_type,
                    provider=monitor.provider,
                    strategy_key=matched.strategy_key,
                    strategy_name=matched.strategy_name,
                    strategy_version=matched.strategy_version,
                    detector_key=matched.detector_key,
                    category=matched.category,
                    status=matched.status,
                    direction=matched.direction,
                    signal_candle_open_time=matched.signal_candle_open_time,
                    signal_candle_close_time=matched.signal_candle_close_time,
                    confirmation_candle_open_time=matched.confirmation_candle_open_time,
                    candle_refs=matched.candle_refs,
                    observed_evidence=matched.observed_evidence,
                    missing_conditions=matched.missing_conditions,
                    invalidation_evidence=matched.invalidation_evidence,
                    reference_level=matched.reference_level,
                    level_kind=matched.level_kind,
                    approval_status=matched.approval_status,
                    decision_use_approved=matched.decision_use_approved,
                    feed_compatibility=matched.feed_compatibility,
                    data_verification=matched.data_verification,
                    expiry_rule=matched.expiry_rule,
                    expires_after_candles=matched.expires_after_candles,
                    decision=matched.decision,
                    probability_status=matched.probability_status,
                    detected_at=now,
                )
            return True
        except IntegrityError:
            # Duplicate (monitor, strategy, candle, status): already recorded.
            return False

    # -- lifecycle --------------------------------------------------------
    @staticmethod
    def _expire_stale(
        monitor: InstrumentMonitor, candles: list[ProviderCandle], now: datetime
    ) -> int:
        """Expire non-confirmed signals whose confirmation window has passed.

        A signal expires when more than ``expires_after_candles`` of its own
        candles have closed since its signal candle without it confirming.
        """
        if not candles:
            return 0
        latest_open = candles[-1].open_time
        seconds = TIMEFRAME_SECONDS.get(monitor.timeframe, 60)
        candidates = LiveSignal.objects.filter(
            monitor=monitor,
            status__in=(SignalStatus.FORMING, SignalStatus.AWAITING_CONFIRMATION),
        )
        expired = 0
        for signal in candidates:
            allowed = signal.expires_after_candles * seconds
            if (latest_open - signal.signal_candle_open_time).total_seconds() > allowed:
                LiveSignal.objects.filter(pk=signal.pk).update(status=SignalStatus.EXPIRED)
                expired += 1
        return expired

    def _resolve_outcomes(
        self, monitor: InstrumentMonitor, candles: list[ProviderCandle]
    ) -> int:
        """Resolve paper outcomes one compatible candle after the signal candle.

        Outcomes are only ever the **next-candle close direction** of the same
        feed — never a binary settlement. Signals on an OTC monitor with no
        compatible feed are marked ``UNVERIFIABLE``.
        """
        compatible, _ = _feed_is_compatible(monitor.canonical_instrument, monitor.market_type)
        if not compatible:
            return self._mark_unverifiable(monitor)

        by_open = {c.open_time: c for c in candles}
        pending = LiveSignal.objects.filter(
            monitor=monitor, outcome_status=OutcomeStatus.PENDING
        )
        resolved = 0
        for signal in pending:
            outcome_open = signal.signal_candle_close_time
            outcome = by_open.get(outcome_open)
            if outcome is None:
                continue
            signal_candle = by_open.get(signal.signal_candle_open_time)
            if signal_candle is None:
                continue
            signal.record_outcome(**_outcome_fields(signal, signal_candle, outcome))
            resolved += 1
        return resolved

    @staticmethod
    def _mark_unverifiable(monitor: InstrumentMonitor) -> int:
        pending = LiveSignal.objects.filter(
            monitor=monitor, outcome_status=OutcomeStatus.PENDING
        )
        count = 0
        for signal in pending:
            signal.record_outcome(
                outcome_status=OutcomeStatus.UNVERIFIABLE,
                outcome_note="no compatible feed to verify this instrument",
            )
            count += 1
        return count

    # -- health -----------------------------------------------------------
    @staticmethod
    def _mark_feed(monitor: InstrumentMonitor, state: str, message: str) -> None:
        InstrumentMonitor.objects.filter(pk=monitor.pk).update(
            feed_state=state,
            state=MonitorState.DEGRADED,
            last_run_at=timezone.now(),
            last_error=message,
        )

    @staticmethod
    def _record_failure(monitor: InstrumentMonitor, message: str) -> None:
        monitor.refresh_from_db()
        failures = monitor.consecutive_failures + 1
        state = MonitorState.ERROR if failures >= MAX_CONSECUTIVE_FAILURES else MonitorState.DEGRADED
        InstrumentMonitor.objects.filter(pk=monitor.pk).update(
            consecutive_failures=failures,
            state=state,
            feed_state=FeedState.UNAVAILABLE,
            last_run_at=timezone.now(),
            last_error=message,
        )


def _outcome_fields(signal: LiveSignal, signal_candle: ProviderCandle, outcome: ProviderCandle) -> dict:
    """Build the ``record_outcome`` kwargs for a next-candle resolution."""
    if signal.direction not in ("bullish", "bearish"):
        return {
            "outcome_status": OutcomeStatus.UNVERIFIABLE,
            "outcome_candle_open_time": outcome.open_time,
            "outcome_candle_close_price": outcome.close,
            "outcome_note": "pattern-only signal: no direction to score",
        }
    went_up = outcome.close > signal_candle.close
    tied = outcome.close == signal_candle.close
    if tied:
        status = OutcomeStatus.TIE
        correct = None
    else:
        predicted_up = signal.direction == "bullish"
        correct = went_up == predicted_up
        status = (
            OutcomeStatus.VERIFIED_CORRECT if correct else OutcomeStatus.VERIFIED_INCORRECT
        )
    return {
        "outcome_status": status,
        "outcome_candle_open_time": outcome.open_time,
        "outcome_candle_close_price": outcome.close,
        "outcome_correct": correct,
        "outcome_note": "next-candle close direction on the same feed",
    }


def run_all_monitors(*, provider_name: str = "db", now: datetime | None = None) -> list[MonitorRunResult]:
    """Run every enabled monitor once (the Celery beat entry point)."""
    monitors = ensure_monitors()
    engine = LiveSignalMonitor(provider_name=provider_name)
    results: list[MonitorRunResult] = []
    for monitor in monitors:
        if not monitor.enabled:
            continue
        if monitor.state == MonitorState.ERROR:
            continue
        results.append(engine.run_monitor(monitor, now=now))
    return results


__all__ = [
    "CANDLE_WINDOW",
    "MAX_CONSECUTIVE_FAILURES",
    "STALE_AFTER_PERIODS",
    "LiveSignalMonitor",
    "MonitorRunResult",
    "default_monitors",
    "ensure_monitors",
    "run_all_monitors",
    "watched_monitors_for_user",
]
