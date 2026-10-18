# apps/strategy_engine/services/timing_validator.py
"""Timing and next-candle validation (Step 10, reworked in Phase 11 CP5).

Timezone contract
-----------------
Every datetime that reaches a comparison here is **UTC-aware**. Parsing goes
through :mod:`apps.core.timeutils`, which keeps ``Z``/numeric offsets and
**rejects** naive timestamps unless their source timezone is explicitly
supplied. A naive timestamp is never silently shifted — that was a real defect
(``_parse_time`` used to strip ``+00:00``/``Z`` and produce naive values).

Expiry contract
---------------
The signal candle is the last **completed** candle; the prediction target is
the candle that follows it. The evaluation is:

* ``EXPIRED`` once the target candle has already closed (a finished opportunity
  is never re-pointed at a later candle), and
* ``EXPIRED`` when the evaluation lands beyond the entry window after the
  target open. For ``M1`` the entry window is the classic few seconds; for
  higher timeframes it is a configurable fraction of the candle
  (``max_entry_ratio``) so that a 5-second rule does not make ``H1`` unusable.
* ``FUTURE_INVALID`` when the evaluation timestamp precedes the close of the
  signal candle (clock skew or look-ahead artefact).
* ``UNCERTAIN`` when timestamps are missing, unparsable or ambiguous.
"""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from typing import Any

from apps.core.timeutils import parse_iso_datetime
from apps.market_data.services.timeframe_mapper import duration_seconds
from apps.strategy_engine.constants import TimingValidity


class TimingValidator:
    """Validate timing for next-candle predictions."""

    #: Grace period (seconds) after the target open within which the entry is
    #: still considered actionable. Applies to every timeframe.
    DEFAULT_ENTRY_TOLERANCE_SECONDS = 5

    #: Hard expiry: once this fraction of the target candle has elapsed the
    #: setup is no longer an actionable "next candle" entry (all timeframes).
    DEFAULT_MAX_ENTRY_RATIO = 0.5

    def __init__(
        self,
        entry_tolerance_seconds: int = DEFAULT_ENTRY_TOLERANCE_SECONDS,
        max_entry_ratio: float = DEFAULT_MAX_ENTRY_RATIO,
    ) -> None:
        self.entry_tolerance_seconds = entry_tolerance_seconds
        self.max_entry_ratio = max_entry_ratio

    def validate_timing(
        self,
        candles: list[dict[str, Any]],
        timeframe: str,
        evaluation_timestamp: datetime | None = None,
        *,
        source_tz: tzinfo | None = None,
        entry_tolerance_seconds: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Validate timing and return ``(validity, timing_info)``."""
        tolerance = (
            entry_tolerance_seconds
            if entry_tolerance_seconds is not None
            else self.entry_tolerance_seconds
        )

        if not candles or evaluation_timestamp is None:
            return TimingValidity.UNCERTAIN, {}

        # The evaluation clock must be timezone-aware and unambiguous: a naive
        # value (datetime or string) is rejected, never silently localised.
        evaluation_ts = parse_iso_datetime(evaluation_timestamp)
        if evaluation_ts is None:
            return TimingValidity.UNCERTAIN, {"reason": "ambiguous_evaluation_timestamp"}

        # Signal candle = last completed candle.
        signal = candles[-1]
        signal_open = self._parse_time(signal.get("open_time"), source_tz=source_tz)
        signal_close = self._parse_time(signal.get("close_time"), source_tz=source_tz)
        if signal_open is None:
            return TimingValidity.UNCERTAIN, {"reason": "signal_open_time_unparsable"}

        try:
            tf_seconds = duration_seconds(timeframe) if timeframe else 0
        except Exception:
            tf_seconds = 0
        if tf_seconds <= 0:
            # Without a known candle duration no boundary can be computed.
            return TimingValidity.UNCERTAIN, {"reason": "unsupported_timeframe"}

        if signal_close is None:
            # Derive the close from the period; never assume it is "now".
            signal_close = signal_open + timedelta(seconds=tf_seconds)

        target_open = signal_close
        target_close = target_open + timedelta(seconds=tf_seconds)
        entry_deadline = target_open + timedelta(seconds=tolerance)
        max_ratio_deadline = target_open + timedelta(seconds=tf_seconds * self.max_entry_ratio)

        timing_info: dict[str, Any] = {
            "signal_candle_open_time": signal_open,
            "signal_candle_close_time": signal_close,
            "target_candle_open_time": target_open,
            "target_candle_close_time": target_close,
            "entry_deadline": entry_deadline,
        }

        # Look-ahead / clock skew: the evaluation predates the signal close.
        if evaluation_ts < signal_close - timedelta(seconds=tolerance):
            timing_info["reason"] = "evaluation_before_signal_close"
            return TimingValidity.FUTURE_INVALID, timing_info

        # The target candle has already finished: the opportunity is gone and
        # must never be shifted to a later candle.
        if evaluation_ts >= target_close:
            timing_info["reason"] = "target_candle_completed"
            return TimingValidity.EXPIRED, timing_info

        # Entry window: strict tolerance for fast timeframes, proportional
        # window for slower ones (documented policy, constructor-tunable).
        if timeframe == "M1" or tf_seconds <= 300:
            deadline = entry_deadline
        else:
            deadline = max(entry_deadline, max_ratio_deadline)
        if evaluation_ts > deadline:
            timing_info["reason"] = "entry_window_expired"
            timing_info["entry_deadline"] = deadline
            return TimingValidity.EXPIRED, timing_info

        # Still inside the target candle (past the tolerance): actionable but
        # delayed — surfaced so callers can display processing latency.
        delayed = (evaluation_ts - target_open).total_seconds()
        timing_info["delayed_entry_seconds"] = max(0.0, delayed)
        if delayed > tolerance:
            timing_info["reason"] = "delayed_entry_within_window"

        return TimingValidity.VALID, timing_info

    def candle_completion_state(
        self,
        candle: dict[str, Any],
        timeframe: str,
        *,
        now: datetime,
        source_tz: tzinfo | None = None,
    ) -> str:
        """Classify a candle as ``completed`` / ``forming`` / ``unknown``.

        Uses the recorded ``complete`` flag when present; otherwise derives the
        state from the candle's close boundary versus ``now`` (both must be
        timezone-aware — an ambiguous input yields ``unknown``).
        """
        flag = candle.get("complete")
        if flag is True:
            return "completed"
        if flag is False:
            return "forming"
        close = self._parse_time(candle.get("close_time"), source_tz=source_tz)
        open_time = self._parse_time(candle.get("open_time"), source_tz=source_tz)
        if close is None and open_time is not None and timeframe:
            try:
                close = open_time + timedelta(seconds=duration_seconds(timeframe))
            except Exception:
                close = None
        if close is None or now is None or now.tzinfo is None:
            return "unknown"
        return "completed" if now >= close else "forming"

    def _parse_time(self, t: Any, *, source_tz: tzinfo | None = None) -> datetime | None:
        """Parse a timestamp, preserving timezone information.

        ``Z`` and numeric offsets are honoured; naive values are rejected
        unless ``source_tz`` is explicitly provided. Returns UTC-aware or
        ``None`` — never a naive datetime.
        """
        return parse_iso_datetime(t, source_tz=source_tz)

    def is_candle_unfinished(self, candle: dict[str, Any]) -> bool:
        """Check if candle is marked as unfinished."""
        return candle.get("complete") is False


__all__ = ["TimingValidator"]
