"""Order-block engine (Step 15).

Two definitions are supported and are **never merged**:

* :attr:`OBDefinition.TEACHER_PATTERN` - the Nazbeen course reading: the last
  opposing candle before a strong impulsive departure that breaks a prior swing.
* :attr:`OBDefinition.ICT_STYLE` - the common "last opposing candle before a
  displacement that leaves an imbalance, often after a sweep" reading.

Each is a *research hypothesis* about a zone, not a claim about institutional
orders. The engine reports boundaries, departure strength, retest and
invalidation, and records which definition produced the zone.
"""

from __future__ import annotations

from typing import Any

from apps.price_action.constants import OBDefinition, OBType
from apps.price_action.services.candle_math import (
    average_range,
    body_range_ratio,
    is_bearish,
    is_bullish,
)
from apps.price_action.services.config import PriceActionConfig
from apps.price_action.services.fair_value_gaps import detect_fvg


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


def _strong_departure(
    candle: dict[str, Any], avg_range: float | None, config: PriceActionConfig
) -> bool:
    ratio = body_range_ratio(candle)
    if ratio is None or ratio < config.strong_body_ratio_min:
        return False
    if avg_range and avg_range > 0:
        return (_f(candle, "high") - _f(candle, "low")) >= config.strong_range_multiple * avg_range
    return True


def detect_order_blocks(
    candles: list[dict[str, Any]],
    *,
    definition: str = OBDefinition.TEACHER_PATTERN,
    config: PriceActionConfig | None = None,
) -> list[dict[str, Any]]:
    config = config or PriceActionConfig.from_settings()
    avg = average_range(candles, config.volume_lookback)
    obs: list[dict[str, Any]] = []
    for i in range(1, len(candles)):
        prev = candles[i - 1]
        cur = candles[i]
        if not _strong_departure(cur, avg, config):
            continue
        # Bullish order block: last down candle before an up departure.
        if is_bearish(prev) and is_bullish(cur):
            obs.append(_build_ob(candles, i - 1, i, OBType.BULLISH, definition, bool(avg), config))
        # Bearish order block: last up candle before a down departure.
        if is_bullish(prev) and is_bearish(cur):
            obs.append(_build_ob(candles, i - 1, i, OBType.BEARISH, definition, bool(avg), config))
    return obs


def _build_ob(
    candles: list[dict[str, Any]],
    ob_index: int,
    departure_index: int,
    ob_type: str,
    definition: str,
    strong_departure: bool,
    config: PriceActionConfig,
) -> dict[str, Any]:
    zone_candle = candles[ob_index]
    top = _f(zone_candle, "high")
    bottom = _f(zone_candle, "low")
    sweep_before = False
    if definition == OBDefinition.ICT_STYLE:
        # ICT-style additionally requires an imbalance left by the departure.
        has_fvg = any(g["index"] >= departure_index for g in detect_fvg(candles, config=config))
        if not has_fvg:
            return {
                "type": ob_type,
                "definition": definition,
                "index": ob_index,
                "top": top,
                "bottom": bottom,
                "strong_departure": strong_departure,
                "sweep_before": False,
                "rejected": "no imbalance at departure",
            }
    return {
        "type": ob_type,
        "definition": definition,
        "index": ob_index,
        "departure_index": departure_index,
        "top": top,
        "bottom": bottom,
        "strong_departure": strong_departure,
        "sweep_before": sweep_before,
    }


def annotate_ob_lifecycle(
    candles: list[dict[str, Any]], zones: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Add retest index and state (active / invalidated) to each zone."""
    for zone in zones:
        top = zone["top"]
        bottom = zone["bottom"]
        retest_index = None
        state = "active"
        start = zone.get("departure_index", zone["index"]) + 1
        for i in range(start, len(candles)):
            c = candles[i]
            if retest_index is None and _f(c, "low") <= top and _f(c, "high") >= bottom:
                retest_index = i
            if zone["type"] == str(OBType.BULLISH) and _f(c, "close") < bottom:
                state = "invalidated"
            if zone["type"] == str(OBType.BEARISH) and _f(c, "close") > top:
                state = "invalidated"
        zone["retest_index"] = retest_index
        zone["state"] = state
    return zones


#: Backwards-compatible alias used by the earlier scaffold.
def detect_ob(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return detect_order_blocks(candles)


__all__ = [
    "annotate_ob_lifecycle",
    "detect_ob",
    "detect_order_blocks",
]
