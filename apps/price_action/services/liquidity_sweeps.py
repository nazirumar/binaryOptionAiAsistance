"""Liquidity sweep engine (Step 14).

A sweep is an *observable* price event: a wick pierces a prior extreme and price
closes back inside the prior range. Whether that represents "stop hunting" or
"manipulation" is **not** directly observable and is never claimed here. Rejection
sweeps are distinguished from sustained breakouts.
"""

from __future__ import annotations

from typing import Any

from apps.price_action.constants import Direction, SweepOutcome, SweepType
from apps.price_action.services.candle_math import (
    lower_wick_ratio,
    upper_wick_ratio,
)
from apps.price_action.services.candlestick_patterns import (
    bearish_engulfing,
    bullish_engulfing,
)
from apps.price_action.services.config import PriceActionConfig


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


def _prior_high(candles: list[dict[str, Any]], n: int) -> float | None:
    window = candles[-n - 1 : -1]
    if not window:
        return None
    return max(_f(c, "high") for c in window)


def _prior_low(candles: list[dict[str, Any]], n: int) -> float | None:
    window = candles[-n - 1 : -1]
    if not window:
        return None
    return min(_f(c, "low") for c in window)


def prev_high_sweep(candles: list[dict[str, Any]]) -> bool:
    if len(candles) < 3:
        return False
    prior = _prior_high(candles, 2)
    last = candles[-1]
    return prior is not None and _f(last, "high") > prior and _f(last, "close") <= prior


def prev_low_sweep(candles: list[dict[str, Any]]) -> bool:
    if len(candles) < 3:
        return False
    prior = _prior_low(candles, 2)
    last = candles[-1]
    return prior is not None and _f(last, "low") < prior and _f(last, "close") >= prior


def _continuation(candles: list[dict[str, Any]], level: float, side: str) -> bool:
    for c in candles:
        if side == "high" and _f(c, "close") > level:
            return True
        if side == "low" and _f(c, "close") < level:
            return True
    return False


def detect_sweep(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> list[dict[str, Any]]:
    """Detect sweep candles and classify their immediate outcome."""
    config = config or PriceActionConfig.from_settings()
    out: list[dict[str, Any]] = []
    if len(candles) < 3:
        return out
    prior_high = _prior_high(candles, 2)
    prior_low = _prior_low(candles, 2)
    last = candles[-1]
    idx = len(candles) - 1
    penetration = config.sweep_min_penetration

    if prior_high is not None and _f(last, "high") > prior_high * (1 + penetration):
        closed_back = _f(last, "close") <= prior_high
        upper = upper_wick_ratio(last) or 0.0
        confirmed = bearish_engulfing(candles, idx)
        if closed_back:
            outcome = (
                SweepOutcome.REJECTION
                if upper >= config.rejection_wick_min
                else (SweepOutcome.REJECTION if confirmed else SweepOutcome.INSUFFICIENT_RECOVERY)
            )
        elif _continuation(candles[-1:], prior_high, "high"):
            outcome = SweepOutcome.CONTINUATION
        else:
            outcome = SweepOutcome.UNRESOLVED
        out.append(
            {
                "type": SweepType.HIGH_SWEEP,
                "index": idx,
                "level": prior_high,
                "outcome": str(outcome),
                "closed_back_inside": closed_back,
                "engulfing_confirmation": confirmed,
                "direction": Direction.BEARISH,
                "note": "sweep is observable; intent is not",
            }
        )

    if prior_low is not None and _f(last, "low") < prior_low * (1 - penetration):
        closed_back = _f(last, "close") >= prior_low
        lower = lower_wick_ratio(last) or 0.0
        confirmed = bullish_engulfing(candles, idx)
        if closed_back:
            outcome = (
                SweepOutcome.REJECTION
                if lower >= config.rejection_wick_min
                else (SweepOutcome.REJECTION if confirmed else SweepOutcome.INSUFFICIENT_RECOVERY)
            )
        elif _continuation(candles[-1:], prior_low, "low"):
            outcome = SweepOutcome.CONTINUATION
        else:
            outcome = SweepOutcome.UNRESOLVED
        out.append(
            {
                "type": SweepType.LOW_SWEEP,
                "index": idx,
                "level": prior_low,
                "outcome": str(outcome),
                "closed_back_inside": closed_back,
                "engulfing_confirmation": confirmed,
                "direction": Direction.BULLISH,
                "note": "sweep is observable; intent is not",
            }
        )
    return out


__all__ = [
    "detect_sweep",
    "prev_high_sweep",
    "prev_low_sweep",
]
