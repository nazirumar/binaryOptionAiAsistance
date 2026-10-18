"""Candle geometry and strength (Step 8).

Objective measurements (ratios, ranges) are kept strictly separate from the
*subjective labels* derived from them (strong/weak/neutral/rejection). Callers
that want the raw numbers should call the ratio helpers; callers that want the
label should call :func:`classify_strength`, which is explicit about the
thresholds it used.
"""

from __future__ import annotations

from typing import Any

from apps.price_action.constants import CandleStrength
from apps.price_action.services.config import PriceActionConfig

Numeric = float | int


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


def is_bullish(candle: dict[str, Any]) -> bool:
    return _f(candle, "close") > _f(candle, "open")


def is_bearish(candle: dict[str, Any]) -> bool:
    return _f(candle, "close") < _f(candle, "open")


def candle_range(candle: dict[str, Any]) -> float:
    return _f(candle, "high") - _f(candle, "low")


def body_size(candle: dict[str, Any]) -> float:
    return abs(_f(candle, "close") - _f(candle, "open"))


def body_range_ratio(candle: dict[str, Any]) -> float | None:
    rng = candle_range(candle)
    if rng <= 0.0:
        return None
    return body_size(candle) / rng


#: Convenience alias used by some detectors/tests.
body_ratio = body_range_ratio


def upper_wick_ratio(candle: dict[str, Any]) -> float | None:
    rng = candle_range(candle)
    if rng <= 0.0:
        return None
    top_body = max(_f(candle, "open"), _f(candle, "close"))
    return max(0.0, (_f(candle, "high") - top_body)) / rng


def lower_wick_ratio(candle: dict[str, Any]) -> float | None:
    rng = candle_range(candle)
    if rng <= 0.0:
        return None
    bottom_body = min(_f(candle, "open"), _f(candle, "close"))
    return max(0.0, (bottom_body - _f(candle, "low"))) / rng


def real_body_top(candle: dict[str, Any]) -> float:
    return max(_f(candle, "open"), _f(candle, "close"))


def real_body_bottom(candle: dict[str, Any]) -> float:
    return min(_f(candle, "open"), _f(candle, "close"))


def is_doji(candle: dict[str, Any], doji_body_ratio_max: float = 0.12) -> bool:
    ratio = body_range_ratio(candle)
    if ratio is None:
        return True
    return ratio <= doji_body_ratio_max


def average_range(candles: list[dict[str, Any]], lookback: int = 20) -> float | None:
    window = candles[-lookback:]
    ranges = [candle_range(c) for c in window]
    usable = [r for r in ranges if r > 0]
    if not usable:
        return None
    return sum(usable) / len(usable)


def classify_strength(
    candle: dict[str, Any],
    *,
    avg_range: float | None = None,
    config: PriceActionConfig | None = None,
) -> str:
    """Label a candle's strength. The label is a *convention*, not a fact."""
    config = config or PriceActionConfig.from_settings()
    ratio = body_range_ratio(candle)
    if ratio is None:
        return CandleStrength.UNKNOWN
    rng = candle_range(candle)
    range_ok = True
    if avg_range and avg_range > 0:
        range_ok = rng >= config.strong_range_multiple * avg_range
    strong = ratio >= config.strong_body_ratio_min and range_ok
    if strong and is_bullish(candle):
        return CandleStrength.STRONG_BULLISH
    if strong and is_bearish(candle):
        return CandleStrength.STRONG_BEARISH
    if ratio <= config.small_body_ratio_max:
        return CandleStrength.WEAK
    return CandleStrength.NEUTRAL


def is_rejection_candle(
    candle: dict[str, Any], *, config: PriceActionConfig | None = None
) -> dict[str, Any]:
    """Report whether the upper or lower wick dominates (a rejection footprint)."""
    config = config or PriceActionConfig.from_settings()
    upper = upper_wick_ratio(candle)
    lower = lower_wick_ratio(candle)
    if upper is None or lower is None:
        return {"rejection": False, "side": None, "upper": upper, "lower": lower}
    if lower >= config.rejection_wick_min and lower > upper:
        return {"rejection": True, "side": "lower", "upper": upper, "lower": lower}
    if upper >= config.rejection_wick_min and upper > lower:
        return {"rejection": True, "side": "upper", "upper": upper, "lower": lower}
    return {"rejection": False, "side": None, "upper": upper, "lower": lower}


def is_wick_sweep_candidate(candle: dict[str, Any], level: float, side: str) -> bool:
    """A wick pierced ``level`` but the candle closed back on the origin side."""
    if side == "high":
        return _f(candle, "high") > level and _f(candle, "close") <= level
    return _f(candle, "low") < level and _f(candle, "close") >= level


def aggregate_ohlc(candles: list[dict[str, Any]]) -> dict[str, float] | None:
    """Aggregate several candles into one synthetic OHLC candle."""
    if not candles:
        return None
    return {
        "open": _f(candles[0], "open"),
        "high": max(_f(c, "high") for c in candles),
        "low": min(_f(c, "low") for c in candles),
        "close": _f(candles[-1], "close"),
    }


__all__ = [
    "aggregate_ohlc",
    "average_range",
    "body_range_ratio",
    "body_ratio",
    "body_size",
    "candle_range",
    "classify_strength",
    "is_bearish",
    "is_bullish",
    "is_doji",
    "is_rejection_candle",
    "is_wick_sweep_candidate",
    "lower_wick_ratio",
    "real_body_bottom",
    "real_body_top",
    "upper_wick_ratio",
]
