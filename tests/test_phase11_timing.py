# tests/test_phase11_timing.py
"""Phase 11 CP5 — timezone and candle-timing correctness.

Proves that:

* ``Z`` and numeric offsets (positive and negative) are preserved and
  normalised to UTC;
* naive timestamps are **rejected** unless their source timezone is explicitly
  supplied (never silently shifted);
* candle boundaries, completed-vs-forming classification, expiry, stale
  screenshots, future timestamps and delayed analysis completion behave per
  the documented contract.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from apps.core.timeutils import ensure_utc, parse_iso_datetime, utc_iso
from apps.strategy_engine.constants import TimingValidity
from apps.strategy_engine.services.timing_validator import TimingValidator

pytestmark = pytest.mark.django_db


def _candle(open_time: datetime, *, minutes: int = 1, complete: bool = True) -> dict:
    return {
        "open": 1.1,
        "high": 1.105,
        "low": 1.095,
        "close": 1.102,
        "open_time": open_time,
        "close_time": open_time + timedelta(minutes=minutes),
        "complete": complete,
    }


class TestParseIsoDatetime:
    def test_utc_z_suffix_is_preserved(self):
        parsed = parse_iso_datetime("2026-03-01T10:00:00Z")
        assert parsed == datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
        assert parsed.tzinfo is not None

    def test_positive_offset_normalises_to_utc(self):
        parsed = parse_iso_datetime("2026-03-01T11:00:00+01:00")
        assert parsed == datetime(2026, 3, 1, 10, 0, tzinfo=UTC)

    def test_negative_offset_normalises_to_utc(self):
        parsed = parse_iso_datetime("2026-03-01T05:00:00-05:00")
        assert parsed == datetime(2026, 3, 1, 10, 0, tzinfo=UTC)

    def test_naive_string_is_rejected(self):
        assert parse_iso_datetime("2026-03-01T10:00:00") is None

    def test_naive_string_with_declared_source_tz_is_accepted(self):
        parsed = parse_iso_datetime("2026-03-01T11:00:00", source_tz=timezone(timedelta(hours=1)))
        assert parsed == datetime(2026, 3, 1, 10, 0, tzinfo=UTC)

    def test_naive_datetime_is_rejected_without_source_tz(self):
        assert parse_iso_datetime(datetime(2026, 3, 1, 10, 0)) is None

    def test_aware_datetime_is_converted(self):
        parsed = parse_iso_datetime(
            datetime(2026, 3, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))
        )
        assert parsed == datetime(2026, 3, 1, 10, 0, tzinfo=UTC)

    def test_garbage_and_empty_are_rejected(self):
        assert parse_iso_datetime("not-a-date") is None
        assert parse_iso_datetime("") is None
        assert parse_iso_datetime(None) is None
        assert parse_iso_datetime(12345) is None

    def test_ensure_utc_and_iso_roundtrip(self):
        aware = datetime(2026, 3, 1, 11, 0, tzinfo=timezone(timedelta(hours=1)))
        assert ensure_utc(aware) == datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
        assert utc_iso(aware) == "2026-03-01T10:00:00Z"


class TestTimingValidatorTimezones:
    """The signal candle is 10:00 UTC; M1 target candle opens 10:01 UTC."""

    SIGNAL = [_candle(datetime(2026, 3, 1, 10, 0, tzinfo=UTC))]

    def test_utc_evaluation_within_entry_window_is_valid(self):
        validity, info = TimingValidator().validate_timing(
            self.SIGNAL, "M1", datetime(2026, 3, 1, 10, 1, 2, tzinfo=UTC)
        )
        assert validity == TimingValidity.VALID
        assert info["target_candle_open_time"] == datetime(2026, 3, 1, 10, 1, tzinfo=UTC)

    def test_plus_one_offset_equivalent_evaluation_is_valid(self):
        # 11:01:02+01:00 == 10:01:02Z — same instant, different rendering.
        validity, _info = TimingValidator().validate_timing(
            self.SIGNAL, "M1", datetime(2026, 3, 1, 11, 1, 2, tzinfo=timezone(timedelta(hours=1)))
        )
        assert validity == TimingValidity.VALID

    def test_negative_offset_equivalent_evaluation_is_valid(self):
        # 05:01:02-05:00 == 10:01:02Z.
        validity, _info = TimingValidator().validate_timing(
            self.SIGNAL, "M1", datetime(2026, 3, 1, 5, 1, 2, tzinfo=timezone(timedelta(hours=-5)))
        )
        assert validity == TimingValidity.VALID

    def test_offset_that_changes_the_decision_is_expired(self):
        # 10:01:30Z is past the M1 entry tolerance; rendered as +01:00 it must
        # still be EXPIRED — the instant decides, not the spelling.
        validity, _info = TimingValidator().validate_timing(
            self.SIGNAL, "M1", datetime(2026, 3, 1, 11, 1, 30, tzinfo=timezone(timedelta(hours=1)))
        )
        assert validity == TimingValidity.EXPIRED

    def test_string_timestamps_with_offsets_are_supported(self):
        validity, _info = TimingValidator().validate_timing(
            [{"open_time": "2026-03-01T10:00:00Z", "close_time": "2026-03-01T10:01:00+00:00"}],
            "M1",
            "2026-03-01T10:01:02Z",
        )
        assert validity == TimingValidity.VALID

    def test_naive_evaluation_clock_is_uncertain(self):
        validity, info = TimingValidator().validate_timing(
            self.SIGNAL, "M1", datetime(2026, 3, 1, 10, 1, 2)
        )
        assert validity == TimingValidity.UNCERTAIN
        assert info["reason"] == "ambiguous_evaluation_timestamp"

    def test_naive_candle_timestamp_is_uncertain(self):
        validity, info = TimingValidator().validate_timing(
            [_candle(datetime(2026, 3, 1, 10, 0))], "M1", datetime(2026, 3, 1, 10, 1, tzinfo=UTC)
        )
        assert validity == TimingValidity.UNCERTAIN
        assert info["reason"] == "signal_open_time_unparsable"

    def test_explicit_source_tz_resolves_ambiguity(self):
        validity, _info = TimingValidator().validate_timing(
            [_candle(datetime(2026, 3, 1, 11, 0))],
            "M1",
            datetime(2026, 3, 1, 10, 1, 2, tzinfo=UTC),
            source_tz=timezone(timedelta(hours=1)),
        )
        assert validity == TimingValidity.VALID


class TestTimingBoundaries:
    def test_midnight_boundary_rollover(self):
        # Signal candle 23:59-00:00 (UTC) crosses midnight; target opens 00:00.
        signal = [_candle(datetime(2026, 3, 1, 23, 59, tzinfo=UTC))]
        validity, info = TimingValidator().validate_timing(
            signal, "M1", datetime(2026, 3, 2, 0, 0, 2, tzinfo=UTC)
        )
        assert validity == TimingValidity.VALID
        assert info["target_candle_open_time"] == datetime(2026, 3, 2, 0, 0, tzinfo=UTC)
        assert info["target_candle_close_time"] == datetime(2026, 3, 2, 0, 1, tzinfo=UTC)

    def test_target_candle_already_completed_is_expired(self):
        signal = [_candle(datetime(2026, 3, 1, 10, 0, tzinfo=UTC))]
        validity, info = TimingValidator().validate_timing(
            signal, "M1", datetime(2026, 3, 1, 10, 5, tzinfo=UTC)
        )
        assert validity == TimingValidity.EXPIRED
        assert info["reason"] == "target_candle_completed"

    def test_expired_signal_is_never_rolled_to_the_next_candle(self):
        # Three candles later the assessment must stay EXPIRED with the
        # original target — not re-pointed at a fresh candle.
        candles = [
            _candle(datetime(2026, 3, 1, 10, 0, tzinfo=UTC)),
            _candle(datetime(2026, 3, 1, 10, 1, tzinfo=UTC)),
            _candle(datetime(2026, 3, 1, 10, 2, tzinfo=UTC)),
        ]
        validity, info = TimingValidator().validate_timing(
            candles, "M1", datetime(2026, 3, 1, 10, 4, tzinfo=UTC)
        )
        assert validity == TimingValidity.EXPIRED
        assert info["target_candle_open_time"] == datetime(2026, 3, 1, 10, 3, tzinfo=UTC)

    def test_evaluation_before_signal_close_is_future_invalid(self):
        signal = [_candle(datetime(2026, 3, 1, 10, 0, tzinfo=UTC))]
        validity, info = TimingValidator().validate_timing(
            signal, "M1", datetime(2026, 3, 1, 9, 59, 30, tzinfo=UTC)
        )
        assert validity == TimingValidity.FUTURE_INVALID
        assert info["reason"] == "evaluation_before_signal_close"

    def test_future_target_flagged_on_high_timeframes(self):
        # H1 signal: the target candle has not closed; evaluation 20 minutes
        # before the signal close is a look-ahead artefact.
        signal = [_candle(datetime(2026, 3, 1, 9, 0, tzinfo=UTC), minutes=60)]
        validity, _info = TimingValidator().validate_timing(
            signal, "H1", datetime(2026, 3, 1, 9, 40, tzinfo=UTC)
        )
        assert validity == TimingValidity.FUTURE_INVALID

    def test_stale_screenshot_is_expired(self):
        # A screenshot from the 10:00 candle analysed 30 minutes later: the
        # entry window for that next candle is long gone.
        signal = [_candle(datetime(2026, 3, 1, 10, 0, tzinfo=UTC))]
        validity, _info = TimingValidator().validate_timing(
            signal, "M1", datetime(2026, 3, 1, 10, 30, tzinfo=UTC)
        )
        assert validity == TimingValidity.EXPIRED

    def test_delayed_completion_within_window_is_valid_with_delay_reported(self):
        # AI processing took 3 seconds: still inside the M1 entry window.
        signal = [_candle(datetime(2026, 3, 1, 10, 0, tzinfo=UTC))]
        validity, info = TimingValidator().validate_timing(
            signal, "M1", datetime(2026, 3, 1, 10, 1, 3, tzinfo=UTC)
        )
        assert validity == TimingValidity.VALID
        assert info["delayed_entry_seconds"] == 3.0

    def test_high_timeframe_entry_window_is_proportional(self):
        # H1: 20 minutes into the target candle (10:00-11:00) is still
        # actionable (within 50%); the old code only ever checked M1, and a
        # naive 5s rule would make every H1 evaluation EXPIRED.
        signal = [_candle(datetime(2026, 3, 1, 9, 0, tzinfo=UTC), minutes=60)]
        validity, _info = TimingValidator().validate_timing(
            signal, "H1", datetime(2026, 3, 1, 10, 20, tzinfo=UTC)
        )
        assert validity == TimingValidity.VALID

    def test_high_timeframe_beyond_half_candle_is_expired(self):
        signal = [_candle(datetime(2026, 3, 1, 9, 0, tzinfo=UTC), minutes=60)]
        validity, info = TimingValidator().validate_timing(
            signal, "H1", datetime(2026, 3, 1, 10, 40, 30, tzinfo=UTC)
        )
        assert validity == TimingValidity.EXPIRED
        assert info["reason"] == "entry_window_expired"

    def test_unsupported_timeframe_is_uncertain(self):
        signal = [_candle(datetime(2026, 3, 1, 10, 0, tzinfo=UTC))]
        validity, info = TimingValidator().validate_timing(
            signal, "X9", datetime(2026, 3, 1, 10, 0, 30, tzinfo=UTC)
        )
        assert validity == TimingValidity.UNCERTAIN
        assert info["reason"] == "unsupported_timeframe"

    def test_missing_close_time_is_derived_from_open(self):
        candle = {
            "open_time": "2026-03-01T10:00:00Z",
            "close_time": None,
            "complete": True,
        }
        validity, info = TimingValidator().validate_timing(
            [candle], "M1", datetime(2026, 3, 1, 10, 1, 1, tzinfo=UTC)
        )
        assert validity == TimingValidity.VALID
        assert info["signal_candle_close_time"] == datetime(2026, 3, 1, 10, 1, tzinfo=UTC)


class TestCandleCompletionState:
    def test_flagged_candles(self):
        validator = TimingValidator()
        now = datetime(2026, 3, 1, 10, 2, tzinfo=UTC)
        forming = _candle(datetime(2026, 3, 1, 10, 1, tzinfo=UTC), complete=False)
        completed = _candle(datetime(2026, 3, 1, 10, 1, tzinfo=UTC), complete=True)
        assert validator.candle_completion_state(forming, "M1", now=now) == "forming"
        assert validator.candle_completion_state(completed, "M1", now=now) == "completed"

    def test_boundary_derivation_without_flag(self):
        validator = TimingValidator()
        candle = {"open_time": "2026-03-01T10:01:00Z", "close_time": None}
        before_close = datetime(2026, 3, 1, 10, 1, 30, tzinfo=UTC)
        after_close = datetime(2026, 3, 1, 10, 2, 0, tzinfo=UTC)
        assert validator.candle_completion_state(candle, "M1", now=before_close) == "forming"
        assert validator.candle_completion_state(candle, "M1", now=after_close) == "completed"

    def test_unknown_when_clock_is_ambiguous(self):
        validator = TimingValidator()
        candle = {"open_time": "2026-03-01T10:01:00Z", "close_time": None}
        assert (
            validator.candle_completion_state(candle, "M1", now=datetime(2026, 3, 1, 10, 2))
            == "unknown"
        )
