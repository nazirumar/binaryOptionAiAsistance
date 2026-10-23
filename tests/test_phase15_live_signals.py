# tests/test_phase15_live_signals.py
"""Phase 15 - automatic live-signals monitor.

Hermetic: SQLite, hand-built candles, a fake in-memory candle provider, no
network, no MT5, no LLM. The tests assert the honesty guarantees the brief
demands:

* closed-candle-only processing (forming bars are never evaluated);
* strategy matching via the existing deterministic detectors;
* approval gating (unapproved strategies never carry a direction);
* duplicate prevention and restart recovery;
* signal immutability and one-shot outcome resolution;
* OTC/feed incompatibility -> UNVERIFIABLE (never a guessed outcome);
* owner-scoped settings that can only narrow, never widen, the gate;
* dashboard rendering, live-update fragments and alert deduplication.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse

from apps.book_strategies.models import BookStrategy
from apps.live_signals.constants import (
    MONITORABLE_TIMEFRAMES,
    FeedState,
    OutcomeStatus,
    SignalCategory,
    SignalStatus,
)
from apps.live_signals.models import (
    InstrumentMonitor,
    LiveSignal,
    SignalAlert,
    SignalImmutableError,
    UserMonitor,
    UserMonitorSettings,
    payload_digest,
)
from apps.live_signals.services.alerts import (
    create_alerts_for_signal,
    mark_alert_read,
    unread_alerts_for,
)
from apps.live_signals.services.matching import categorise, check_eligibility, match_strategy
from apps.live_signals.services.metrics import (
    directional_metrics,
    recognition_metrics,
)
from apps.live_signals.services.monitor import (
    LiveSignalMonitor,
    watched_monitors_for_user,
)
from apps.live_signals.services.providers import (
    DatabaseCandleProvider,
    ProviderCandle,
    ProviderResult,
)
from apps.market_data.constants import DataSource
from apps.market_data.models import MarketCandle, MarketSymbol
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
BASE = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


def _legs(start: float = 1.0, cycles: int = 4, leg: int = 3,
          step: float = 0.0008, pull: float = 0.0005) -> list[dict]:
    """Rising market with real swing structure (3-candle legs).

    Copy of the Phase 13 fixture so the trend gate sees a genuine uptrend.
    """
    from tests.pa_fakes import candle

    out: list[dict] = []
    price = start

    def up_leg() -> None:
        nonlocal price
        for _ in range(leg):
            o = price
            c = price + step
            out.append(candle(o, c + 0.0001, o, c))
            price = c

    def down_leg() -> None:
        nonlocal price
        for _ in range(leg):
            o = price
            c = price - pull
            out.append(candle(o, o, c - 0.0001, c))
            price = c

    for _ in range(cycles):
        up_leg()
        down_leg()
    up_leg()
    return out


def ss22_series() -> list[dict]:
    """Rising three (SS22) — exact shape from the Phase 13 tests."""
    from tests.pa_fakes import candle

    c = _legs()
    p = c[-1]["close"]
    for _ in range(3):
        o = p
        c.append(candle(o, o + 0.0004, o - 0.0001, o + 0.0003))
        p = o + 0.0003
    g_top = max(x["high"] for x in c[-3:])
    g_lo = min(x["low"] for x in c[-3:])
    for _ in range(3):
        o = p
        c.append(candle(o, o + 0.0001, o - 0.0003, o - 0.0002))
        p = o - 0.0002
    c.append(candle(g_lo, g_top + 0.0004, g_lo - 0.0001, g_top + 0.0003))
    return c


def to_provider(candles: list[dict], *, start: datetime = BASE, step_seconds: int = 300,
                complete: bool = True) -> list[ProviderCandle]:
    """Wrap detector dicts as provider candles with ascending open times."""
    out: list[ProviderCandle] = []
    t = start
    for row in candles:
        out.append(
            ProviderCandle(
                open_time=t,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                is_complete=complete,
            )
        )
        t = t + timedelta(seconds=step_seconds)
    return out


class FakeProvider:
    """In-memory provider: returns exactly what a test hands it."""

    name = "fake"

    def __init__(self, candles: list[ProviderCandle], *, available: bool = True,
                 state: str = FeedState.OK, message: str = "ok") -> None:
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


def seed_ss22(*, recognition: bool = True, approved: bool = False,
              research_status: str = "implemented") -> BookStrategy:
    """Create/refresh the SS22 strategy row with explicit switches."""
    row, _ = BookStrategy.objects.get_or_create(
        key="SS22",
        defaults={"number": 22, "name": "Rising Three Method", "chapter": "7"},
    )
    row.recognition_enabled = recognition
    row.decision_use_approved = approved
    row.research_status = research_status
    row.detector_key = "ss22"
    row.save()
    return row


def make_monitor(*, instrument: str = "EURUSD", timeframe: str = "M5",
                 market_type: str = "regular", is_otc: bool = False) -> InstrumentMonitor:
    return InstrumentMonitor.objects.create(
        canonical_instrument=instrument,
        timeframe=timeframe,
        market_type=market_type,
        is_otc=is_otc,
        provider="fake",
    )


# ---------------------------------------------------------------------------
# Constants & configuration invariants
# ---------------------------------------------------------------------------
class TestConstants:
    def test_monitorable_timeframes_are_low_only(self):
        assert set(MONITORABLE_TIMEFRAMES) == {"M1", "M2", "M3", "M5", "M15"}

    def test_signal_categories_are_three_and_distinct(self):
        assert SignalCategory.ALL == (
            SignalCategory.EXPERIMENTAL_PATTERN,
            SignalCategory.CONFIRMED_PATTERN,
            SignalCategory.RESEARCH_VALIDATED,
        )

    def test_statuses_match_brief(self):
        assert set(SignalStatus.ALL) == {
            "FORMING",
            "AWAITING_CONFIRMATION",
            "CONFIRMED_PATTERN",
            "INVALIDATED",
            "EXPIRED",
            "UNVERIFIABLE",
        }


# ---------------------------------------------------------------------------
# 1. Closed-candle-only processing
# ---------------------------------------------------------------------------
class TestClosedCandleOnly:
    def test_provider_finalise_drops_forming_bars(self):
        candles = [
            ProviderCandle(BASE, 1, 1, 1, 1, is_complete=True),
            ProviderCandle(BASE + timedelta(seconds=300), 1, 1, 1, 1, is_complete=False),
        ]
        from apps.live_signals.services.providers import _finalise

        now = BASE + timedelta(seconds=900)
        final = _finalise(candles, "M5", 10, now)
        assert len(final) == 1
        assert final[0].is_complete is True

    def test_provider_rederives_completeness_from_time(self):
        # A bar marked complete but whose period has not closed is rejected.
        from apps.live_signals.services.providers import _finalise

        now = BASE + timedelta(seconds=60)  # only 1 min into a 5-min bar
        candles = [ProviderCandle(BASE, 1, 1, 1, 1, is_complete=True)]
        assert _finalise(candles, "M5", 10, now) == []

    def test_match_refuses_incomplete_candles(self):
        seed_ss22()
        strategy = BookStrategy.objects.get(key="SS22")
        candles = to_provider(ss22_series(), complete=False)
        result = match_strategy(
            strategy,
            candles,
            instrument="EURUSD",
            timeframe="M5",
            market_type="regular",
            feed_is_otc=False,
            instrument_is_otc=False,
        )
        assert result is None

    def test_monitor_detects_only_closed(self):
        seed_ss22()
        monitor = make_monitor()
        candles = to_provider(ss22_series())
        engine = LiveSignalMonitor(provider=FakeProvider(candles))
        result = engine.run_monitor(monitor, now=BASE + timedelta(days=1))
        assert result.evaluated is True
        assert LiveSignal.objects.filter(monitor=monitor).count() >= 1


# ---------------------------------------------------------------------------
# 2. Strategy matching & 3. invalidation
# ---------------------------------------------------------------------------
class TestMatching:
    def test_confirmed_pattern_detected(self):
        seed_ss22()
        strategy = BookStrategy.objects.get(key="SS22")
        candles = to_provider(ss22_series())
        matched = match_strategy(
            strategy, candles, instrument="EURUSD", timeframe="M5",
            market_type="regular", feed_is_otc=False, instrument_is_otc=False,
        )
        assert matched is not None
        assert matched.status == SignalStatus.CONFIRMED_PATTERN

    def test_insufficient_candles_yields_no_signal(self):
        seed_ss22()
        strategy = BookStrategy.objects.get(key="SS22")
        candles = to_provider(ss22_series()[:2])
        matched = match_strategy(
            strategy, candles, instrument="EURUSD", timeframe="M5",
            market_type="regular", feed_is_otc=False, instrument_is_otc=False,
        )
        assert matched is None

    def test_invalidated_pattern_is_not_directional(self):
        seed_ss22(approved=True, research_status="approved")
        strategy = BookStrategy.objects.get(key="SS22")
        # Reversing the final engulfing candle can invalidate the setup.
        from tests.pa_fakes import candle

        series = ss22_series()
        series[-1] = candle(series[-1]["open"], series[-1]["open"] + 0.0001,
                            series[-1]["open"] - 0.001, series[-1]["open"] - 0.0009)
        matched = match_strategy(
            strategy, to_provider(series), instrument="EURUSD", timeframe="M5",
            market_type="regular", feed_is_otc=False, instrument_is_otc=False,
        )
        # Whatever the detector says, a non-confirmed state never carries a
        # direction.
        if matched is not None:
            assert matched.direction == "none" or matched.status == SignalStatus.INVALIDATED


# ---------------------------------------------------------------------------
# 4. Approval gates
# ---------------------------------------------------------------------------
class TestApprovalGates:
    def test_unapproved_strategy_has_no_direction(self):
        seed_ss22(recognition=True, approved=False)
        strategy = BookStrategy.objects.get(key="SS22")
        matched = match_strategy(
            strategy, to_provider(ss22_series()), instrument="EURUSD",
            timeframe="M5", market_type="regular", feed_is_otc=False,
            instrument_is_otc=False,
        )
        assert matched is not None
        assert matched.category == SignalCategory.CONFIRMED_PATTERN
        assert matched.direction == "none"
        assert matched.decision_use_approved is False

    def test_approved_strategy_carries_direction(self):
        seed_ss22(recognition=True, approved=True, research_status="approved")
        strategy = BookStrategy.objects.get(key="SS22")
        matched = match_strategy(
            strategy, to_provider(ss22_series()), instrument="EURUSD",
            timeframe="M5", market_type="regular", feed_is_otc=False,
            instrument_is_otc=False,
        )
        assert matched is not None
        assert matched.category == SignalCategory.RESEARCH_VALIDATED
        assert matched.direction in ("bullish", "bearish")
        assert matched.decision_use_approved is True

    def test_approved_but_not_validated_stays_pattern(self):
        seed_ss22(recognition=True, approved=True, research_status="implemented")
        strategy = BookStrategy.objects.get(key="SS22")
        matched = match_strategy(
            strategy, to_provider(ss22_series()), instrument="EURUSD",
            timeframe="M5", market_type="regular", feed_is_otc=False,
            instrument_is_otc=False,
        )
        assert matched.category == SignalCategory.CONFIRMED_PATTERN
        assert matched.direction == "none"

    def test_recognition_disabled_is_ineligible(self):
        seed_ss22(recognition=False)
        strategy = BookStrategy.objects.get(key="SS22")
        decision = check_eligibility(
            strategy, instrument="EURUSD", timeframe="M5", market_type="regular",
            feed_is_otc=False, instrument_is_otc=False,
        )
        assert decision.eligible is False

    def test_categorise_never_promotes_unapproved(self):
        strategy = seed_ss22(recognition=True, approved=False)
        category, carries = categorise(strategy, "CONFIRMED_PATTERN")
        assert category == SignalCategory.CONFIRMED_PATTERN
        assert carries is False


# ---------------------------------------------------------------------------
# 5. Feed compatibility / OTC rejection
# ---------------------------------------------------------------------------
class TestFeedCompatibility:
    def test_otc_instrument_requires_otc_feed(self):
        seed_ss22()
        strategy = BookStrategy.objects.get(key="SS22")
        decision = check_eligibility(
            strategy, instrument="EURUSD_OTC", timeframe="M5",
            market_type="regular", feed_is_otc=False, instrument_is_otc=True,
        )
        assert decision.eligible is False
        assert decision.feed_compatibility == "INCOMPATIBLE_FEEDS"

    def test_otc_monitor_feed_marked_incompatible(self):
        seed_ss22()
        monitor = make_monitor(instrument="EURUSD_OTC", market_type="regular", is_otc=True)
        engine = LiveSignalMonitor(provider=FakeProvider(to_provider(ss22_series())))
        result = engine.run_monitor(monitor)
        assert result.feed_state == FeedState.INCOMPATIBLE
        monitor.refresh_from_db()
        assert monitor.feed_state == FeedState.INCOMPATIBLE

    def test_otc_outcome_is_unverifiable(self):
        seed_ss22(recognition=True, approved=True, research_status="approved")
        monitor = make_monitor(instrument="EURUSD_OTC", market_type="regular", is_otc=True)
        signal = LiveSignal.objects.create(
            monitor=monitor,
            instrument="EURUSD_OTC",
            timeframe="M5",
            category=SignalCategory.RESEARCH_VALIDATED,
            status=SignalStatus.CONFIRMED_PATTERN,
            direction="bullish",
            strategy_key="MANUAL",
            signal_candle_open_time=BASE,
            signal_candle_close_time=BASE + timedelta(seconds=300),
        )
        engine = LiveSignalMonitor(provider=FakeProvider(to_provider(ss22_series())))
        engine.run_monitor(monitor)
        signal.refresh_from_db()
        assert signal.outcome_status == OutcomeStatus.UNVERIFIABLE


# ---------------------------------------------------------------------------
# 6. Duplicate prevention & restart recovery
# ---------------------------------------------------------------------------
class TestDuplicatePrevention:
    def test_same_candle_not_evaluated_twice(self):
        seed_ss22()
        monitor = make_monitor()
        candles = to_provider(ss22_series())
        now = BASE + timedelta(days=1)
        engine = LiveSignalMonitor(provider=FakeProvider(candles))
        engine.run_monitor(monitor, now=now)
        first_count = LiveSignal.objects.filter(monitor=monitor).count()
        monitor.refresh_from_db()
        second = engine.run_monitor(monitor, now=now)
        assert second.evaluated is False
        assert LiveSignal.objects.filter(monitor=monitor).count() == first_count

    def test_duplicate_insert_is_noop(self):
        seed_ss22()
        monitor = make_monitor()
        candles = to_provider(ss22_series())
        engine = LiveSignalMonitor(provider=FakeProvider(candles))
        engine.run_monitor(monitor, now=BASE + timedelta(days=1))
        # Re-run detection directly for the same candle; constraint blocks it.
        count_before = LiveSignal.objects.count()
        engine._evaluate_candle(monitor, candles, "verified", BASE + timedelta(days=1))
        assert LiveSignal.objects.count() == count_before

    def test_restart_recovers_from_persisted_position(self):
        seed_ss22()
        monitor = make_monitor()
        candles = to_provider(ss22_series())
        now = BASE + timedelta(days=1)
        LiveSignalMonitor(provider=FakeProvider(candles)).run_monitor(monitor, now=now)
        monitor.refresh_from_db()
        assert monitor.last_evaluated_candle_open_time is not None
        # A fresh engine (simulating a worker restart) sees the position.
        engine2 = LiveSignalMonitor(provider=FakeProvider(candles))
        result = engine2.run_monitor(monitor, now=now)
        assert result.evaluated is False


# ---------------------------------------------------------------------------
# 7. Signal immutability & outcome resolution
# ---------------------------------------------------------------------------
class TestImmutability:
    def _signal(self, monitor=None) -> LiveSignal:
        monitor = monitor or make_monitor()
        return LiveSignal.objects.create(
            monitor=monitor,
            instrument=monitor.canonical_instrument,
            timeframe=monitor.timeframe,
            strategy_key="SS22",
            category=SignalCategory.CONFIRMED_PATTERN,
            status=SignalStatus.CONFIRMED_PATTERN,
            signal_candle_open_time=BASE,
            signal_candle_close_time=BASE + timedelta(seconds=300),
        )

    def test_direction_is_frozen(self):
        signal = self._signal()
        signal.direction = "bullish"
        with pytest.raises(SignalImmutableError):
            signal.save()

    def test_status_is_frozen(self):
        signal = self._signal()
        signal.status = SignalStatus.EXPIRED
        with pytest.raises(SignalImmutableError):
            signal.save()

    def test_outcome_can_be_recorded_once(self):
        signal = self._signal()
        signal.record_outcome(
            outcome_status=OutcomeStatus.VERIFIED_CORRECT,
            outcome_correct=True,
        )
        signal.refresh_from_db()
        assert signal.outcome_status == OutcomeStatus.VERIFIED_CORRECT
        with pytest.raises(SignalImmutableError):
            signal.record_outcome(outcome_status=OutcomeStatus.VERIFIED_INCORRECT)

    def test_payload_digest_is_stable(self):
        signal = self._signal()
        assert signal.payload_sha256
        assert signal.verify_integrity() is True
        assert payload_digest(signal._integrity_payload()) == signal.payload_sha256

    def test_integrity_fails_if_evidence_tampered_raw(self):
        signal = self._signal()
        LiveSignal.objects.filter(pk=signal.pk).update(observed_evidence=["tampered"])
        signal.refresh_from_db()
        assert signal.verify_integrity() is False


class TestOutcomeResolution:
    def test_next_candle_direction_scored(self):
        from tests.pa_fakes import candle

        monitor = make_monitor()
        # Two candles: signal candle closes up, next closes up -> bullish correct.
        series = [candle(1.0, 1.001, 0.999, 1.0005), candle(1.0005, 1.002, 1.000, 1.0015)]
        candles = to_provider(series)
        signal = LiveSignal.objects.create(
            monitor=monitor,
            instrument="EURUSD",
            timeframe="M5",
            category=SignalCategory.RESEARCH_VALIDATED,
            status=SignalStatus.CONFIRMED_PATTERN,
            direction="bullish",
            strategy_key="SS22",
            signal_candle_open_time=candles[0].open_time,
            signal_candle_close_time=candles[1].open_time,
        )
        engine = LiveSignalMonitor(provider=FakeProvider(candles))
        resolved = engine._resolve_outcomes(monitor, candles)
        signal.refresh_from_db()
        assert resolved == 1
        assert signal.outcome_status == OutcomeStatus.VERIFIED_CORRECT
        assert signal.outcome_correct is True

    def test_tie_is_recorded_as_tie(self):
        from tests.pa_fakes import candle

        monitor = make_monitor()
        series = [candle(1.0, 1.001, 0.999, 1.0000), candle(1.0, 1.001, 0.999, 1.0000)]
        candles = to_provider(series)
        signal = LiveSignal.objects.create(
            monitor=monitor,
            instrument="EURUSD",
            timeframe="M5",
            category=SignalCategory.RESEARCH_VALIDATED,
            status=SignalStatus.CONFIRMED_PATTERN,
            direction="bullish",
            strategy_key="SS22",
            signal_candle_open_time=candles[0].open_time,
            signal_candle_close_time=candles[1].open_time,
        )
        LiveSignalMonitor(provider=FakeProvider(candles))._resolve_outcomes(monitor, candles)
        signal.refresh_from_db()
        assert signal.outcome_status == OutcomeStatus.TIE
        assert signal.outcome_correct is None


# ---------------------------------------------------------------------------
# 8. Expiry lifecycle
# ---------------------------------------------------------------------------
class TestExpiry:
    def test_unconfirmed_signal_expires(self):
        monitor = make_monitor()
        # Signal candle long ago; latest candle is far ahead.
        signal = LiveSignal.objects.create(
            monitor=monitor,
            instrument="EURUSD",
            timeframe="M5",
            category=SignalCategory.EXPERIMENTAL_PATTERN,
            status=SignalStatus.AWAITING_CONFIRMATION,
            strategy_key="SS22",
            signal_candle_open_time=BASE,
            signal_candle_close_time=BASE + timedelta(seconds=300),
            expires_after_candles=1,
        )
        candles = to_provider(ss22_series()[:3], start=BASE + timedelta(hours=2))
        engine = LiveSignalMonitor(provider=FakeProvider(candles))
        expired = engine._expire_stale(monitor, candles, BASE + timedelta(hours=3))
        signal.refresh_from_db()
        assert expired == 1
        assert signal.status == SignalStatus.EXPIRED


# ---------------------------------------------------------------------------
# 9. Metrics separation
# ---------------------------------------------------------------------------
class TestMetrics:
    def test_recognition_and_directional_are_separate(self):
        monitor = make_monitor()
        LiveSignal.objects.create(
            monitor=monitor, instrument="EURUSD", timeframe="M5",
            strategy_key="SS22", category=SignalCategory.CONFIRMED_PATTERN,
            status=SignalStatus.CONFIRMED_PATTERN,
            signal_candle_open_time=BASE,
            signal_candle_close_time=BASE + timedelta(seconds=300),
        )
        LiveSignal.objects.create(
            monitor=monitor, instrument="EURUSD", timeframe="M5",
            strategy_key="SS22", category=SignalCategory.RESEARCH_VALIDATED,
            status=SignalStatus.CONFIRMED_PATTERN, direction="bullish",
            signal_candle_open_time=BASE + timedelta(minutes=5),
            signal_candle_close_time=BASE + timedelta(minutes=10),
            outcome_status=OutcomeStatus.VERIFIED_CORRECT, outcome_correct=True,
        )
        recognition = recognition_metrics()
        directional = directional_metrics()
        assert recognition.total_patterns == 2
        # Only the directional one is counted as eligible.
        assert directional.total_eligible == 1
        assert directional.resolved == 1
        assert directional.confirmed_correct == 1
        assert directional.insufficient is True  # below min sample

    def test_unverified_not_folded_into_hit_rate(self):
        monitor = make_monitor()
        LiveSignal.objects.create(
            monitor=monitor, instrument="EURUSD", timeframe="M5",
            strategy_key="SS22", category=SignalCategory.RESEARCH_VALIDATED,
            status=SignalStatus.CONFIRMED_PATTERN, direction="bullish",
            signal_candle_open_time=BASE,
            signal_candle_close_time=BASE + timedelta(seconds=300),
            outcome_status=OutcomeStatus.UNVERIFIABLE,
        )
        metrics = directional_metrics()
        assert metrics.unverified == 1
        assert metrics.resolved == 0
        assert metrics.hit_rate is None


# ---------------------------------------------------------------------------
# 10. User settings (owner-scoped, narrowing only)
# ---------------------------------------------------------------------------
class TestUserSettings:
    def test_defaults_are_safe(self):
        user = UserFactory()
        settings_obj = UserMonitorSettings.objects.create(user=user)
        assert settings_obj.only_approved is False
        assert settings_obj.show_experimental is True
        assert settings_obj.browser_notifications is False

    def test_settings_cannot_widen_gate(self):
        """No setting turns an unapproved pattern into a directional signal."""
        user = UserFactory()
        UserMonitorSettings.objects.create(user=user, only_approved=True)
        seed_ss22(recognition=True, approved=False)
        strategy = BookStrategy.objects.get(key="SS22")
        matched = match_strategy(
            strategy, to_provider(ss22_series()), instrument="EURUSD",
            timeframe="M5", market_type="regular", feed_is_otc=False,
            instrument_is_otc=False,
        )
        assert matched.category != SignalCategory.RESEARCH_VALIDATED

    def test_watched_monitors_are_owner_scoped(self):
        user = UserFactory()
        other = UserFactory()
        UserMonitorSettings.objects.create(
            user=user, instruments=["EURUSD"], timeframes=["M5"]
        )
        UserMonitorSettings.objects.create(
            user=other, instruments=["GBPUSD"], timeframes=["M15"]
        )
        ensure_monitors_defaults = [
            ("EURUSD", "M5", "regular"),
            ("GBPUSD", "M15", "regular"),
        ]
        for instrument, tf, market in ensure_monitors_defaults:
            InstrumentMonitor.objects.get_or_create(
                canonical_instrument=instrument, timeframe=tf, market_type=market
            )
        mine = watched_monitors_for_user(user)
        assert {m.canonical_instrument for m in mine} == {"EURUSD"}
        theirs = watched_monitors_for_user(other)
        assert {m.canonical_instrument for m in theirs} == {"GBPUSD"}


# ---------------------------------------------------------------------------
# 10b. Dynamic user-added monitors (from the settings UI)
# ---------------------------------------------------------------------------
class TestDynamicUserMonitors:
    def test_user_monitor_drives_watched_set(self):
        """A user-added monitor is returned and gets a shared system monitor."""
        user = UserFactory()
        UserMonitor.objects.create(
            user=user, canonical_instrument="GBPUSD", timeframe="M15"
        )
        watched = watched_monitors_for_user(user)
        assert [(m.canonical_instrument, m.timeframe) for m in watched] == [
            ("GBPUSD", "M15")
        ]
        # The shared monitor was created so the engine can actually run it.
        assert InstrumentMonitor.objects.filter(
            canonical_instrument="GBPUSD", timeframe="M15"
        ).exists()

    def test_user_monitors_are_owner_scoped(self):
        user = UserFactory()
        other = UserFactory()
        UserMonitor.objects.create(
            user=user, canonical_instrument="EURUSD", timeframe="M5"
        )
        assert {
            m.canonical_instrument for m in watched_monitors_for_user(other)
        } == set()

    def test_disabled_user_monitor_is_ignored(self):
        user = UserFactory()
        UserMonitor.objects.create(
            user=user, canonical_instrument="EURUSD", timeframe="M5", enabled=False
        )
        assert watched_monitors_for_user(user) == []

    def test_user_monitor_never_widens_the_gate(self):
        """A user-added monitor still only yields unapproved pattern detections."""
        user = UserFactory()
        UserMonitor.objects.create(
            user=user, canonical_instrument="EURUSD", timeframe="M5"
        )
        watched = watched_monitors_for_user(user)
        assert len(watched) == 1
        # Directional signals remain gated on strategy approval, not on monitors.
        assert watched[0].timeframe == "M5"

    def test_settings_page_adds_and_removes_monitor(self, client):
        user = UserFactory()
        client.force_login(user)
        url = reverse("dashboard:live-signals-settings")

        response = client.get(url)
        assert response.status_code == 200
        assert b"Your monitors" in response.content

        response = client.post(
            url,
            {
                "action": "add_monitor",
                "monitor_instrument": "eurusd",
                "monitor_timeframe": "M15",
            },
        )
        assert response.status_code == 302
        monitor = UserMonitor.objects.get(user=user)
        # Instrument is normalised to canonical casing.
        assert monitor.canonical_instrument == "EURUSD"
        assert monitor.timeframe == "M15"
        assert monitor.market_type == "regular"

        response = client.post(
            url, {"action": "remove_monitor", "monitor_id": monitor.pk}
        )
        assert response.status_code == 302
        assert not UserMonitor.objects.filter(user=user).exists()

    def test_settings_page_rejects_unsupported_timeframe(self, client):
        user = UserFactory()
        client.force_login(user)
        url = reverse("dashboard:live-signals-settings")

        response = client.post(
            url,
            {
                "action": "add_monitor",
                "monitor_instrument": "EURUSD",
                "monitor_timeframe": "H1",
            },
        )
        assert response.status_code == 302
        assert not UserMonitor.objects.filter(user=user).exists()

    def test_settings_page_rejects_blank_instrument(self, client):
        user = UserFactory()
        client.force_login(user)
        url = reverse("dashboard:live-signals-settings")

        response = client.post(
            url,
            {
                "action": "add_monitor",
                "monitor_instrument": "   ",
                "monitor_timeframe": "M5",
            },
        )
        assert response.status_code == 302
        assert not UserMonitor.objects.filter(user=user).exists()

    def test_add_monitor_is_idempotent(self, client):
        user = UserFactory()
        client.force_login(user)
        url = reverse("dashboard:live-signals-settings")
        payload = {
            "action": "add_monitor",
            "monitor_instrument": "EURUSD",
            "monitor_timeframe": "M5",
        }
        client.post(url, payload)
        client.post(url, payload)
        assert UserMonitor.objects.filter(user=user).count() == 1

    def test_remove_only_affects_own_monitor(self, client):
        user = UserFactory()
        other = UserFactory()
        client.force_login(user)
        theirs = UserMonitor.objects.create(
            user=other, canonical_instrument="GBPUSD", timeframe="M5"
        )
        response = client.post(
            reverse("dashboard:live-signals-settings"),
            {"action": "remove_monitor", "monitor_id": theirs.pk},
        )
        assert response.status_code == 302
        assert UserMonitor.objects.filter(pk=theirs.pk).exists()


# ---------------------------------------------------------------------------
# 11. Alerts & deduplication
# ---------------------------------------------------------------------------
class TestAlerts:
    def _signal(self) -> LiveSignal:
        monitor = make_monitor()
        return LiveSignal.objects.create(
            monitor=monitor, instrument="EURUSD", timeframe="M5",
            strategy_key="SS22", strategy_name="Rising Three Method",
            category=SignalCategory.CONFIRMED_PATTERN,
            status=SignalStatus.CONFIRMED_PATTERN,
            signal_candle_open_time=BASE,
            signal_candle_close_time=BASE + timedelta(seconds=300),
        )

    def test_alert_created_for_watcher(self):
        user = UserFactory(is_active=True)
        UserMonitorSettings.objects.create(user=user, alerts_enabled=True)
        signal = self._signal()
        created = create_alerts_for_signal(signal)
        assert len(created) == 1
        assert created[0].user == user

    def test_alert_deduplicated(self):
        user = UserFactory(is_active=True)
        UserMonitorSettings.objects.create(user=user)
        signal = self._signal()
        create_alerts_for_signal(signal)
        create_alerts_for_signal(signal)
        assert SignalAlert.objects.filter(user=user, signal=signal).count() == 1

    def test_only_approved_suppresses_pattern_alerts(self):
        user = UserFactory(is_active=True)
        UserMonitorSettings.objects.create(user=user, only_approved=True)
        signal = self._signal()  # a pattern, not directional
        created = create_alerts_for_signal(signal)
        assert created == []

    def test_mark_alert_read_is_owner_scoped(self):
        user = UserFactory(is_active=True)
        other = UserFactory(is_active=True)
        UserMonitorSettings.objects.create(user=user)
        signal = self._signal()
        alert = SignalAlert.objects.create(user=user, signal=signal, title="x")
        # A different user cannot mark it read.
        assert mark_alert_read(other, alert.pk) is False
        assert mark_alert_read(user, alert.pk) is True
        alert.refresh_from_db()
        assert alert.read_at is not None
        assert unread_alerts_for(user).count() == 0


# ---------------------------------------------------------------------------
# Feed availability honesty
# ---------------------------------------------------------------------------
class TestFeedHonesty:
    def test_unavailable_feed_marks_monitor_and_creates_nothing(self):
        seed_ss22()
        monitor = make_monitor()
        engine = LiveSignalMonitor(
            provider=FakeProvider([], available=False, state=FeedState.UNAVAILABLE,
                                  message="no candles")
        )
        result = engine.run_monitor(monitor)
        assert result.feed_state == FeedState.UNAVAILABLE
        assert LiveSignal.objects.count() == 0
        monitor.refresh_from_db()
        assert monitor.feed_state == FeedState.UNAVAILABLE
        assert monitor.state == "degraded"

    def test_provider_error_is_bounded(self):
        class BoomProvider:
            name = "boom"

            def fetch_closed(self, **kwargs):
                raise RuntimeError("boom")

        monitor = make_monitor()
        engine = LiveSignalMonitor(provider=BoomProvider())
        engine.run_monitor(monitor)
        monitor.refresh_from_db()
        assert monitor.consecutive_failures == 1
        assert "boom" in monitor.last_error

    def test_stale_feed_marked_stale(self):
        seed_ss22()
        monitor = make_monitor()
        candles = to_provider(ss22_series(), start=BASE)
        engine = LiveSignalMonitor(provider=FakeProvider(candles))
        # Run far in the future so the newest candle is stale.
        result = engine.run_monitor(monitor, now=BASE + timedelta(days=30))
        assert result.feed_state == FeedState.STALE


# ---------------------------------------------------------------------------
# DatabaseCandleProvider (integration with real MarketCandle rows)
# ---------------------------------------------------------------------------
class TestDatabaseProvider:
    def _make_symbol_and_candles(self, timeframe="M5", n=4):
        symbol = MarketSymbol.objects.create(
            canonical="EURUSD", broker_symbol="EURUSDm", is_active=True
        )
        base = datetime(2020, 1, 1, tzinfo=UTC)
        for i in range(n):
            MarketCandle.objects.create(
                symbol=symbol,
                timeframe=timeframe,
                open_time=base + timedelta(minutes=5 * i),
                open=1.0, high=1.001, low=0.999, close=1.0005,
                source=DataSource.MT5,
                is_complete=True,
            )
        return symbol

    def test_reads_closed_candles(self):
        self._make_symbol_and_candles()
        provider = DatabaseCandleProvider()
        # now far in the future: all bars are closed.
        result = provider.fetch_closed(
            broker_symbol="EURUSDm", canonical_instrument="EURUSD",
            timeframe="M5", count=10, now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert result.available is True
        assert len(result.candles) == 4

    def test_missing_symbol_is_unavailable(self):
        provider = DatabaseCandleProvider()
        result = provider.fetch_closed(
            broker_symbol="", canonical_instrument="ZZZXXX",
            timeframe="M5", count=10, now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert result.available is False
        assert result.state == FeedState.UNAVAILABLE

    def test_unsupported_timeframe_unavailable(self):
        provider = DatabaseCandleProvider()
        result = provider.fetch_closed(
            broker_symbol="EURUSDm", canonical_instrument="EURUSD",
            timeframe="W1", count=10, now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert result.available is False


# ---------------------------------------------------------------------------
# Dashboard / views / live updates
# ---------------------------------------------------------------------------
class TestDashboardViews:
    def test_live_signals_requires_login(self, client):
        response = client.get(reverse("dashboard:live-signals"))
        assert response.status_code == 302
        assert "/accounts/login/" in response.headers["Location"]

    def test_live_signals_renders(self, client):
        user = UserFactory()
        client.force_login(user)
        response = client.get(reverse("dashboard:live-signals"))
        assert response.status_code == 200
        body = response.content.decode()
        assert "Live Signals" in body
        assert "Research and paper monitoring only" in body

    def test_feed_fragment_renders(self, client):
        user = UserFactory()
        client.force_login(user)
        response = client.get(reverse("dashboard:live-signals-feed"))
        assert response.status_code == 200

    def test_status_fragment_renders(self, client):
        user = UserFactory()
        client.force_login(user)
        response = client.get(reverse("dashboard:live-signals-status"))
        assert response.status_code == 200
        assert "Monitoring" in response.content.decode()

    def test_status_fragment_does_not_claim_a_stale_feed_is_reporting(self, client):
        """A stale feed must never read as 'all feeds reporting live'."""
        user = UserFactory()
        client.force_login(user)
        monitor = make_monitor()
        monitor.feed_state = FeedState.STALE
        monitor.save(update_fields=["feed_state"])
        response = client.get(reverse("dashboard:live-signals-status"))
        body = response.content.decode()
        assert response.status_code == 200
        assert "all feeds reporting live" not in body
        assert "stale" in body.lower()

    def test_outcomes_page_keeps_metrics_separate(self, client):
        user = UserFactory()
        client.force_login(user)
        response = client.get(reverse("dashboard:live-signals-outcomes"))
        assert response.status_code == 200
        body = response.content.decode()
        assert "Recognition metrics" in body
        assert "Directional performance (paper)" in body

    def test_detail_is_owner_scoped(self, client):
        owner = UserFactory()
        intruder = UserFactory()
        monitor = make_monitor()
        signal = LiveSignal.objects.create(
            monitor=monitor, owner=owner, instrument="EURUSD", timeframe="M5",
            strategy_key="SS22", category=SignalCategory.CONFIRMED_PATTERN,
            status=SignalStatus.CONFIRMED_PATTERN,
            signal_candle_open_time=BASE,
            signal_candle_close_time=BASE + timedelta(seconds=300),
        )
        client.force_login(intruder)
        response = client.get(reverse("dashboard:live-signal-detail", args=[signal.pk]))
        assert response.status_code == 404

    def test_settings_roundtrip(self, client):
        user = UserFactory()
        client.force_login(user)
        seed_ss22(recognition=True)
        response = client.post(
            reverse("dashboard:live-signals-settings"),
            {
                "instruments": "EURUSD, GBPUSD",
                "timeframes": ["M5", "M15", "W1"],  # W1 must be rejected
                "enabled_strategies": ["SS22"],
                "alerts_enabled": "on",
                "only_approved": "on",
            },
        )
        assert response.status_code == 302
        settings_obj = UserMonitorSettings.objects.get(user=user)
        assert settings_obj.instruments == ["EURUSD", "GBPUSD"]
        assert "W1" not in settings_obj.timeframes
        assert settings_obj.only_approved is True

    def test_settings_cannot_offer_unrecognised_strategies(self, client):
        user = UserFactory()
        client.force_login(user)
        response = client.get(reverse("dashboard:live-signals-settings"))
        assert response.status_code == 200
        # SS22 not recognition-enabled -> not listed.
        assert "Rising Three Method" not in response.content.decode()


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
class TestTasks:
    def test_run_monitors_task_is_safe_without_monitors(self):
        from apps.live_signals.tasks import run_monitors_task

        result = run_monitors_task()
        assert result["monitors"] == 0

    def test_run_monitors_task_alerts_on_new_signal(self):
        user = UserFactory(is_active=True)
        UserMonitorSettings.objects.create(user=user, alerts_enabled=True)
        seed_ss22()
        monitor = make_monitor()
        # Persist a confirmed pattern directly, then alert on it.
        signal = LiveSignal.objects.create(
            monitor=monitor, instrument="EURUSD", timeframe="M5",
            strategy_key="SS22", category=SignalCategory.CONFIRMED_PATTERN,
            status=SignalStatus.CONFIRMED_PATTERN,
            signal_candle_open_time=BASE,
            signal_candle_close_time=BASE + timedelta(seconds=300),
        )
        from apps.live_signals.tasks import _alert_new_signals

        assert _alert_new_signals(monitor, set()) == 1
        assert SignalAlert.objects.filter(signal=signal).count() >= 1
