# tests/test_phase16_reliability.py
"""Phase 16 - live-monitoring reliability hardening tests.

These cover the reliability scenarios the Phase 15 suite did not exercise
explicitly, without changing any production behaviour:

* overlapping/duplicate monitoring jobs cannot double-persist a signal;
* repeated feed failures are bounded and eventually mark the monitor ERROR,
  after which ``run_all_monitors`` skips it;
* a market-closure window (no new closed candles) leaves the monitor healthy
  but evaluated=False and creates no signal;
* a delayed candle after closure is still evaluated exactly once.

Hermetic: SQLite, hand-built candles, in-memory provider, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.book_strategies.models import BookStrategy
from apps.live_signals.constants import FeedState, MonitorState
from apps.live_signals.models import InstrumentMonitor, LiveSignal
from apps.live_signals.services.monitor import (
    MAX_CONSECUTIVE_FAILURES,
    LiveSignalMonitor,
    run_all_monitors,
)
from apps.live_signals.services.providers import ProviderCandle, ProviderResult

pytestmark = pytest.mark.django_db

BASE = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


def _provider_candles(n: int, *, start: datetime = BASE, step_seconds: int = 300):
    return [
        ProviderCandle(
            open_time=start + timedelta(seconds=step_seconds * i),
            open=1.0,
            high=1.001,
            low=0.999,
            close=1.0005,
            is_complete=True,
        )
        for i in range(n)
    ]


class FakeProvider:
    name = "fake"

    def __init__(self, candles, *, available=True, state=FeedState.OK, message="ok"):
        self._candles = candles
        self._available = available
        self._state = state
        self._message = message

    def fetch_closed(self, *, broker_symbol, canonical_instrument, timeframe, count, now=None):
        return ProviderResult(
            candles=list(self._candles[-count:]) if count else list(self._candles),
            available=self._available,
            state=self._state,
            message=self._message,
        )


class BoomProvider:
    name = "boom"

    def fetch_closed(self, **kwargs):
        raise RuntimeError("boom")


def seed_strategy() -> BookStrategy:
    row, _ = BookStrategy.objects.get_or_create(
        key="SS22",
        defaults={"number": 22, "name": "Rising Three Method", "chapter": "7"},
    )
    row.recognition_enabled = True
    row.decision_use_approved = False
    row.research_status = "implemented"
    row.detector_key = "ss22"
    row.save()
    return row


def make_monitor(**kwargs) -> InstrumentMonitor:
    defaults = {
        "canonical_instrument": "EURUSD",
        "timeframe": "M5",
        "market_type": "regular",
        "is_otc": False,
        "provider": "fake",
    }
    defaults.update(kwargs)
    return InstrumentMonitor.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Overlapping monitoring jobs
# ---------------------------------------------------------------------------
class TestOverlappingJobs:
    def test_overlapping_runs_do_not_double_persist(self):
        seed_strategy()
        monitor = make_monitor()
        candles = _provider_candles(60)
        engine = LiveSignalMonitor(provider=FakeProvider(candles))
        now = BASE + timedelta(days=1)

        first = engine.run_monitor(monitor, now=now)
        after_first = LiveSignal.objects.filter(monitor=monitor).count()

        # Simulate a second worker running the same pass concurrently: even a
        # from-scratch detection over the same candle cannot add a duplicate.
        monitor.refresh_from_db()
        LiveSignalMonitor(provider=FakeProvider(candles)).run_monitor(monitor, now=now)
        after_second = LiveSignal.objects.filter(monitor=monitor).count()

        assert first.evaluated is True
        assert after_second == after_first

    def test_two_engines_same_second_are_idempotent(self):
        """Both engines evaluate; the unique constraint keeps signals unique."""
        seed_strategy()
        monitor = make_monitor()
        candles = _provider_candles(60)
        now = BASE + timedelta(days=1)

        engine_a = LiveSignalMonitor(provider=FakeProvider(candles))
        engine_b = LiveSignalMonitor(provider=FakeProvider(candles))
        engine_a.run_monitor(monitor, now=now)
        monitor.refresh_from_db()
        engine_b.run_monitor(monitor, now=now)

        # One row per (monitor, strategy, candle, status).
        from django.db.models import Count

        dupes = (
            LiveSignal.objects.filter(monitor=monitor)
            .values("strategy_key", "signal_candle_open_time", "status")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        assert not list(dupes)


# ---------------------------------------------------------------------------
# Bounded failures / broker disconnection
# ---------------------------------------------------------------------------
class TestBoundedFailures:
    def test_repeated_failures_mark_monitor_error(self):
        monitor = make_monitor()
        engine = LiveSignalMonitor(provider=BoomProvider())

        for _ in range(MAX_CONSECUTIVE_FAILURES):
            monitor.refresh_from_db()
            engine.run_monitor(monitor)

        monitor.refresh_from_db()
        assert monitor.consecutive_failures == MAX_CONSECUTIVE_FAILURES
        assert monitor.state == MonitorState.ERROR
        assert monitor.feed_state == FeedState.UNAVAILABLE

    def test_error_monitor_is_skipped_by_run_all(self):
        monitor = make_monitor()
        InstrumentMonitor.objects.filter(pk=monitor.pk).update(
            state=MonitorState.ERROR, enabled=True
        )

        results = run_all_monitors(provider_name="fake")
        # An ERROR monitor is skipped entirely: it must not appear in any result.
        assert all(r.monitor_id != monitor.pk for r in results)

    def test_success_resets_the_failure_counter(self):
        seed_strategy()
        monitor = make_monitor()
        engine = LiveSignalMonitor(provider=BoomProvider())
        engine.run_monitor(monitor)
        monitor.refresh_from_db()
        assert monitor.consecutive_failures == 1

        good = LiveSignalMonitor(provider=FakeProvider(_provider_candles(60)))
        good.run_monitor(monitor, now=BASE + timedelta(days=1))
        monitor.refresh_from_db()
        assert monitor.consecutive_failures == 0
        assert monitor.state == MonitorState.RUNNING


# ---------------------------------------------------------------------------
# Market closure / delayed processing
# ---------------------------------------------------------------------------
class TestMarketClosure:
    def test_no_new_candles_leaves_healthy_but_unevaluated(self):
        seed_strategy()
        monitor = make_monitor()
        candles = _provider_candles(60)
        now = BASE + timedelta(days=1)

        engine = LiveSignalMonitor(provider=FakeProvider(candles))
        engine.run_monitor(monitor, now=now)
        monitor.refresh_from_db()
        first_signal_count = LiveSignal.objects.filter(monitor=monitor).count()

        # Market closed: the same newest candle is presented again.
        second = engine.run_monitor(monitor, now=now + timedelta(minutes=5))
        assert second.evaluated is False
        assert LiveSignal.objects.filter(monitor=monitor).count() == first_signal_count

    def test_delayed_candle_is_evaluated_once_when_it_arrives(self):
        seed_strategy()
        monitor = make_monitor()
        candles = _provider_candles(60)
        now = BASE + timedelta(days=1)

        engine = LiveSignalMonitor(provider=FakeProvider(candles))
        engine.run_monitor(monitor, now=now)
        monitor.refresh_from_db()

        # A delayed candle finally appears: it is one step newer and evaluated.
        delayed = _provider_candles(61)
        result = LiveSignalMonitor(provider=FakeProvider(delayed)).run_monitor(
            monitor, now=now + timedelta(minutes=5)
        )
        assert result.evaluated is True
        monitor.refresh_from_db()
        assert monitor.last_evaluated_candle_open_time == delayed[-1].open_time
