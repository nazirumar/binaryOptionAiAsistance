# apps/strategy_engine/services/timing_validator.py
"""Timing and next-candle validation (Step 10)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from apps.market_data.services.timeframe_mapper import duration_seconds
from apps.strategy_engine.constants import TimingValidity


class TimingValidator:
    """Validate timing for next-candle predictions."""

    def __init__(self, entry_tolerance_seconds: int = 5) -> None:
        self.entry_tolerance_seconds = entry_tolerance_seconds

    def validate_timing(
        self,
        candles: list[dict[str, Any]],
        timeframe: str,
        evaluation_timestamp: datetime | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Validate timing and return (validity, timing_info)."""
        if not candles or evaluation_timestamp is None:
            return TimingValidity.UNCERTAIN, {}

        # Get signal candle (last completed candle)
        signal = candles[-1] if candles else {}
        signal_open = self._parse_time(signal.get("open_time"))
        signal_close = self._parse_time(signal.get("close_time")) or signal_open

        try:
            tf_seconds = duration_seconds(timeframe) if timeframe else 0
        except Exception:
            tf_seconds = 0

        timing_info = {
            "signal_candle_open_time": signal_open,
            "signal_candle_close_time": signal_close,
            "target_candle_open_time": None,
            "target_candle_close_time": None,
        }

        if tf_seconds > 0 and signal_close:
            target_open = signal_close + timedelta(seconds=tf_seconds)
            target_close = target_open + timedelta(seconds=tf_seconds)
            timing_info["target_candle_open_time"] = target_open
            timing_info["target_candle_close_time"] = target_close

            # For M1 specifically, check if target candle started beyond tolerance
            if timeframe == "M1":
                elapsed = (evaluation_timestamp - target_open).total_seconds()
                if elapsed > self.entry_tolerance_seconds:
                    return TimingValidity.EXPIRED, timing_info
                if elapsed < -300:  # More than 5 minutes in future - odd
                    return TimingValidity.FUTURE_INVALID, timing_info

        return TimingValidity.VALID, timing_info

    def _parse_time(self, t: Any) -> datetime | None:
        if t is None:
            return None
        if isinstance(t, datetime):
            return t
        if isinstance(t, str):
            try:
                # Handle ISO format
                if t.endswith("+00:00"):
                    t = t.replace("+00:00", "")
                return datetime.fromisoformat(t.replace("Z", ""))
            except Exception:
                return None
        return None

    def is_candle_unfinished(self, candle: dict[str, Any]) -> bool:
        """Check if candle is marked as unfinished."""
        return candle.get("complete") is False


__all__ = ["TimingValidator"]
