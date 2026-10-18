"""Buyer and seller failure engine (Step 6).

This module reports *observable* buyer/seller behaviour and keeps the order of
events. It never infers institutional intent: a "source" is only called weak
when price evidence (reduced progress or repeated failures) supports it.
"""

from __future__ import annotations

from typing import Any

from apps.price_action.constants import Direction, SwingKind
from apps.price_action.services.candle_math import is_bearish, is_bullish
from apps.price_action.services.candle_sequences import analyze_reference_sequences
from apps.price_action.services.config import PriceActionConfig
from apps.price_action.services.market_structure import detect_swings, last_swing
from apps.price_action.services.support_resistance import detect_zones


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


def buyers_create_support(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any] | None:
    """A swing low from which price rose: an observable buyer footprint."""
    config = config or PriceActionConfig.from_settings()
    swings = detect_swings(candles, config.swing_lookback)
    low = last_swing(swings, SwingKind.LOW)
    if low is None or low.index + 1 >= len(candles):
        return None
    after = candles[low.index + 1 : low.index + 1 + config.swing_lookback]
    if after and any(is_bullish(c) and _f(c, "close") > low.value for c in after):
        return {
            "type": "buyers_created_support",
            "index": low.index,
            "level": low.value,
            "direction": Direction.BULLISH,
            "note": "observable swing low with a bullish response; not an intent claim",
        }
    return None


def sellers_create_resistance(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any] | None:
    config = config or PriceActionConfig.from_settings()
    swings = detect_swings(candles, config.swing_lookback)
    high = last_swing(swings, SwingKind.HIGH)
    if high is None or high.index + 1 >= len(candles):
        return None
    after = candles[high.index + 1 : high.index + 1 + config.swing_lookback]
    if after and any(is_bearish(c) and _f(c, "close") < high.value for c in after):
        return {
            "type": "sellers_created_resistance",
            "index": high.index,
            "level": high.value,
            "direction": Direction.BEARISH,
            "note": "observable swing high with a bearish response; not an intent claim",
        }
    return None


def _attempted_and_failed(
    candles: list[dict[str, Any]], level: float, *, side: str, tol: float
) -> tuple[bool, int | None, int | None]:
    """Return (failed, attempt_index, failure_index) around ``level``."""
    attempt_index: int | None = None
    for i, c in enumerate(candles):
        if side == "resistance" and _f(c, "high") > level * (1 + tol):
            attempt_index = i
            break
    if attempt_index is None:
        return False, None, None
    for j in range(attempt_index, len(candles)):
        if side == "resistance" and _f(candles[j], "close") < level:
            return True, attempt_index, j
        if side == "support" and _f(candles[j], "close") > level:
            return True, attempt_index, j
    return False, attempt_index, None


def detect_failures(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any]:
    """Attempts and failures against detected support/resistance levels."""
    config = config or PriceActionConfig.from_settings()
    zones = detect_zones(candles, config=config)
    events: list[dict[str, Any]] = []
    for zone in zones:
        side = "resistance" if zone.kind == "resistance" else "support"
        detail = _attempted_and_failed(
            candles, zone.high if side == "resistance" else zone.low, side=side, tol=0.0
        )
        failed, attempt, failure = detail
        if attempt is not None:
            events.append(
                {
                    "type": f"buyers_attempt_break_{side}"
                    if side == "resistance"
                    else "sellers_attempt_break_support",
                    "index": attempt,
                    "level": zone.high if side == "resistance" else zone.low,
                    "direction": Direction.BULLISH if side == "resistance" else Direction.BEARISH,
                }
            )
        if failed and failure is not None:
            events.append(
                {
                    "type": "buyers_failed_to_break_resistance"
                    if side == "resistance"
                    else "sellers_failed_to_break_support",
                    "index": failure,
                    "level": zone.high if side == "resistance" else zone.low,
                    "direction": Direction.BEARISH if side == "resistance" else Direction.BULLISH,
                    "note": "attempt wick was rejected and price closed back inside",
                }
            )
    events.sort(key=lambda e: e["index"])
    return {"events": events}


def source_strength(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any]:
    """Whether the dominant side's progress is strengthening or weakening."""
    config = config or PriceActionConfig.from_settings()
    ref = analyze_reference_sequences(candles, config=config)
    if not ref.get("available"):
        return {"available": False, "reasons": ["no directional run available"]}
    return {
        "available": True,
        "direction": ref["current_direction"],
        "strengthening": ref["strengthening"],
        "weakening": ref["weakening"],
        "reasons": ref["reasons"],
    }


def detect_buyer_seller_failure(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any]:
    """Aggregate Step 6 observations, preserving event order."""
    config = config or PriceActionConfig.from_settings()
    events: list[dict[str, Any]] = []
    for fn in (buyers_create_support, sellers_create_resistance):
        found = fn(candles, config=config)
        if found:
            events.append(found)
    events.extend(detect_failures(candles, config=config)["events"])

    zones = detect_zones(candles, config=config)
    for zone in zones:
        side = "resistance" if zone.kind == "resistance" else "support"
        detail = _attempted_and_failed(
            candles, zone.high if side == "resistance" else zone.low, side=side, tol=0.0
        )
        failed, _attempt, failure = detail
        if failed and failure is not None:
            # source failure followed by breakout / retest
            level = zone.high if side == "resistance" else zone.low
            for j in range(failure + 1, len(candles)):
                close = _f(candles[j], "close")
                broke = close > level if side == "resistance" else close < level
                if broke:
                    events.append(
                        {
                            "type": "source_failure_then_breakout",
                            "index": j,
                            "level": level,
                            "direction": (
                                Direction.BULLISH if side == "resistance" else Direction.BEARISH
                            ),
                            "note": "the failed side later gave way",
                        }
                    )
                    break

    events.sort(key=lambda e: e["index"])
    strength = source_strength(candles, config=config)
    return {"events": events, "source_strength": strength}


__all__ = [
    "buyers_create_support",
    "detect_buyer_seller_failure",
    "detect_failures",
    "sellers_create_resistance",
    "source_strength",
]
