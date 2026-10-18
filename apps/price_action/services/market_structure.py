"""Market-structure engine (Step 4).

Swing points, higher highs/lows, lower highs/lows, trend, structure breaks and
failed breakouts. **No look-ahead:** a swing at index ``i`` is only reported
once ``lookback`` candles have closed on *both* sides of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.price_action.constants import StructureState, SwingKind, SwingLabel
from apps.price_action.services.config import PriceActionConfig


@dataclass(frozen=True, slots=True)
class Swing:
    """A confirmed swing point with a structural label."""

    index: int
    kind: str  # SwingKind.HIGH | SwingKind.LOW
    value: float
    label: str = SwingLabel.UNKNOWN
    time: str | None = None


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


def _close(candle: dict[str, Any]) -> float:
    return _f(candle, "close")


def detect_swings(candles: list[dict[str, Any]], lookback: int = 2) -> list[Swing]:
    """Detect raw swing highs/lows confirmed by ``lookback`` candles each side."""
    swings: list[Swing] = []
    n = len(candles)
    if n == 0 or lookback < 1:
        return swings
    for i in range(lookback, n - lookback):
        c = candles[i]
        high = _f(c, "high")
        low = _f(c, "low")
        left = range(i - lookback, i)
        right = range(i + 1, i + lookback + 1)
        is_high = all(high >= _f(candles[j], "high") for j in left) and all(
            high >= _f(candles[j], "high") for j in right
        )
        is_low = all(low <= _f(candles[j], "low") for j in left) and all(
            low <= _f(candles[j], "low") for j in right
        )
        t = c.get("open_time") or c.get("time")
        t = t if isinstance(t, str) else None
        if is_high:
            swings.append(Swing(index=i, kind=SwingKind.HIGH, value=high, time=t))
        if is_low:
            swings.append(Swing(index=i, kind=SwingKind.LOW, value=low, time=t))
    return swings


def label_swings(swings: list[Swing], tolerance: float = 0.0005) -> list[Swing]:
    """Label each swing relative to the previous swing of the same kind."""
    labelled: list[Swing] = []
    last_high: float | None = None
    last_low: float | None = None
    for s in sorted(swings, key=lambda x: x.index):
        label = SwingLabel.UNKNOWN
        if s.kind == SwingKind.HIGH:
            if last_high is not None:
                label = _compare(
                    s.value, last_high, tolerance, up=SwingLabel.HH, down=SwingLabel.LH
                )
            last_high = s.value
        else:
            if last_low is not None:
                label = _compare(s.value, last_low, tolerance, up=SwingLabel.HL, down=SwingLabel.LL)
            last_low = s.value
        labelled.append(Swing(index=s.index, kind=s.kind, value=s.value, label=label, time=s.time))
    return labelled


def _compare(value: float, previous: float, tolerance: float, *, up: str, down: str) -> str:
    if previous == 0.0:
        return SwingLabel.UNKNOWN
    rel = (value - previous) / abs(previous)
    if rel > tolerance:
        return up
    if rel < -tolerance:
        return down
    return SwingLabel.EQ


def infer_trend(
    candles: list[dict[str, Any]],
    swing_lookback: int = 2,
    *,
    config: PriceActionConfig | None = None,
) -> str:
    """Return "uptrend", "downtrend", "ranging" or "unclear"."""
    config = config or PriceActionConfig.from_settings()
    swings = label_swings(detect_swings(candles, swing_lookback), config.equal_level_tolerance)
    highs = [s for s in swings if s.kind == SwingKind.HIGH]
    lows = [s for s in swings if s.kind == SwingKind.LOW]
    if len(highs) < config.min_swings_for_trend or len(lows) < config.min_swings_for_trend:
        return "unclear"
    hh = highs[-1].label == SwingLabel.HH
    hl = lows[-1].label == SwingLabel.HL
    lh = highs[-1].label == SwingLabel.LH
    ll = lows[-1].label == SwingLabel.LL
    if hh and hl:
        return "uptrend"
    if lh and ll:
        return "downtrend"
    return "ranging"


def structure_state(
    candles: list[dict[str, Any]],
    *,
    swing_lookback: int | None = None,
    config: PriceActionConfig | None = None,
) -> str:
    """Map the inferred trend onto a :class:`StructureState` value."""
    config = config or PriceActionConfig.from_settings()
    lookback = config.swing_lookback if swing_lookback is None else swing_lookback
    trend = infer_trend(candles, lookback, config=config)
    if trend == "uptrend":
        return StructureState.BULLISH
    if trend == "downtrend":
        return StructureState.BEARISH
    if trend == "ranging":
        return StructureState.RANGING
    return StructureState.UNCLEAR


def last_swing(swings: list[Swing], kind: str) -> Swing | None:
    for s in reversed(swings):
        if s.kind == kind:
            return s
    return None


def detect_structure_break(
    candles: list[dict[str, Any]], lookback: int = 2
) -> dict[str, Any] | None:
    """Break of structure: the latest close beyond the most recent confirmed swing."""
    swings = detect_swings(candles, lookback)
    if not candles:
        return None
    price = _close(candles[-1])
    high = last_swing(swings, SwingKind.HIGH)
    low = last_swing(swings, SwingKind.LOW)
    if high is not None and price > high.value:
        return {"type": "bullish_bos", "level": high.value, "index": len(candles) - 1}
    if low is not None and price < low.value:
        return {"type": "bearish_bos", "level": low.value, "index": len(candles) - 1}
    return None


def detect_failed_breakout(
    candles: list[dict[str, Any]], lookback: int = 2
) -> dict[str, Any] | None:
    """Price pierced a swing but closed back inside it (a failed breakout)."""
    swings = detect_swings(candles, lookback)
    if not candles:
        return None
    c = candles[-1]
    high = last_swing(swings, SwingKind.HIGH)
    low = last_swing(swings, SwingKind.LOW)
    if high is not None and _f(c, "high") > high.value and _close(c) < high.value:
        return {"type": "failed_high_breakout", "level": high.value, "index": len(candles) - 1}
    if low is not None and _f(c, "low") < low.value and _close(c) > low.value:
        return {"type": "failed_low_breakout", "level": low.value, "index": len(candles) - 1}
    return None


def detect_consolidation(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any] | None:
    """A tight range over a window with no decisive close outside it."""
    config = config or PriceActionConfig.from_settings()
    window = candles[-config.consolidation_min_candles :]
    if len(window) < config.consolidation_min_candles:
        return None
    high = max(_f(c, "high") for c in window)
    low = min(_f(c, "low") for c in window)
    if low <= 0:
        return None
    width = (high - low) / low
    if width <= config.consolidation_max_width:
        return {
            "type": "consolidation",
            "high": high,
            "low": low,
            "width": width,
            "candles": len(window),
            "index": len(candles) - 1,
        }
    return None


__all__ = [
    "Swing",
    "detect_consolidation",
    "detect_failed_breakout",
    "detect_structure_break",
    "detect_swings",
    "infer_trend",
    "label_swings",
    "last_swing",
    "structure_state",
]
