"""Support and resistance engine (Step 5).

Levels are treated as *zones*, never infinitely precise lines. Every function
reports the tolerance it used. Breakouts are only "confirmed" when a completed
candle *closes* beyond the zone; a retest is only reported when one actually
happened (never assumed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.price_action.constants import RejectionKind, SwingKind, ZoneKind, ZoneState
from apps.price_action.services.candle_math import lower_wick_ratio, upper_wick_ratio
from apps.price_action.services.config import PriceActionConfig
from apps.price_action.services.market_structure import Swing, detect_swings


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


@dataclass(frozen=True, slots=True)
class Zone:
    """A support/resistance zone with an explicit width."""

    kind: str
    low: float
    high: float
    touches: int
    strength: int
    first_index: int
    last_index: int
    state: str = ZoneState.ACTIVE
    reason: str = ""

    @property
    def price(self) -> float:
        return (self.low + self.high) / 2.0

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high


def _cluster(levels: list[tuple[float, int]], tolerance: float) -> list[list[tuple[float, int]]]:
    clusters: list[list[tuple[float, int]]] = []
    for value, index in sorted(levels, key=lambda x: x[0]):
        placed = False
        for cluster in clusters:
            ref = cluster[0][0]
            if ref > 0 and abs(value - ref) / ref <= tolerance:
                cluster.append((value, index))
                placed = True
                break
        if not placed:
            clusters.append([(value, index)])
    return clusters


def _make_zone(
    cluster: list[tuple[float, int]],
    kind: str,
    candles: list[dict[str, Any]],
    config: PriceActionConfig,
) -> Zone:
    values = [v for v, _ in cluster]
    indices = [i for _, i in cluster]
    low = min(values)
    high = max(values)
    touches = count_touches(candles, low, high, config.zone_tolerance)
    return Zone(
        kind=kind,
        low=low,
        high=high,
        touches=touches,
        strength=touches,
        first_index=min(indices),
        last_index=max(indices),
        reason="clustered_swings",
    )


def count_touches(candles: list[dict[str, Any]], low: float, high: float, tolerance: float) -> int:
    touches = 0
    for c in candles:
        for key in ("high", "low"):
            value = _f(c, key)
            if value <= 0:
                continue
            if low <= value <= high or abs(value - low) / low <= tolerance:
                touches += 1
                break
    return touches


def detect_zones(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> list[Zone]:
    """Detect support and resistance zones from clustered swing points."""
    config = config or PriceActionConfig.from_settings()
    if len(candles) < 3:
        return []
    swings: list[Swing] = detect_swings(candles, config.swing_lookback)
    high_levels = [(s.value, s.index) for s in swings if s.kind == SwingKind.HIGH]
    low_levels = [(s.value, s.index) for s in swings if s.kind == SwingKind.LOW]
    zones: list[Zone] = []
    for cluster in _cluster(high_levels, config.zone_tolerance):
        zone = _make_zone(cluster, ZoneKind.RESISTANCE, candles, config)
        if zone.touches >= config.zone_min_touches:
            zones.append(zone)
    for cluster in _cluster(low_levels, config.zone_tolerance):
        zone = _make_zone(cluster, ZoneKind.SUPPORT, candles, config)
        if zone.touches >= config.zone_min_touches:
            zones.append(zone)
    return zones


def detect_rejection(
    candles: list[dict[str, Any]],
    zone: Zone,
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """Report a wick/close rejection off a zone on the most recent candle."""
    config = config or PriceActionConfig.from_settings()
    if not candles:
        return None
    c = candles[-1]
    idx = len(candles) - 1
    if zone.kind == ZoneKind.RESISTANCE and _f(c, "high") >= zone.low:
        upper = upper_wick_ratio(c) or 0.0
        if upper >= config.rejection_wick_min and _f(c, "close") <= zone.high:
            return {
                "kind": RejectionKind.WICK_REJECTION,
                "side": "resistance",
                "index": idx,
                "wick_ratio": upper,
            }
    if zone.kind == ZoneKind.SUPPORT and _f(c, "low") <= zone.high:
        lower = lower_wick_ratio(c) or 0.0
        if lower >= config.rejection_wick_min and _f(c, "close") >= zone.low:
            return {
                "kind": RejectionKind.WICK_REJECTION,
                "side": "support",
                "index": idx,
                "wick_ratio": lower,
            }
    return None


def detect_breakout_confirmation(
    candles: list[dict[str, Any]],
    zone: Zone,
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """A *completed close* beyond the zone confirms a breakout (never assumed)."""
    config = config or PriceActionConfig.from_settings()
    if not candles:
        return None
    c = candles[-1]
    idx = len(candles) - 1
    margin = config.breakout_close_margin
    if zone.kind == ZoneKind.RESISTANCE and _f(c, "close") > zone.high * (1 + margin):
        return {"type": "bullish_breakout", "level": zone.high, "index": idx}
    if zone.kind == ZoneKind.SUPPORT and _f(c, "close") < zone.low * (1 - margin):
        return {"type": "bearish_breakout", "level": zone.low, "index": idx}
    return None


def detect_retest(
    candles: list[dict[str, Any]],
    zone: Zone,
    breakout_index: int,
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """A retest of a broken zone within ``retest_window`` candles."""
    config = config or PriceActionConfig.from_settings()
    start = breakout_index + 1
    end = min(len(candles), start + config.retest_window)
    for i in range(start, end):
        c = candles[i]
        if zone.contains(_f(c, "low")) or zone.contains(_f(c, "high")):
            return {"type": "retest", "index": i, "level": zone.price}
    return None


def detect_sbr_rbs(
    candles: list[dict[str, Any]],
    zone: Zone,
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """Support-becomes-resistance / resistance-becomes-support.

    Requires a *valid level break* (a completed close beyond the zone) followed
    by a retest from the opposite side.
    """
    config = config or PriceActionConfig.from_settings()
    for i, c in enumerate(candles):
        close = _f(c, "close")
        if zone.kind == ZoneKind.RESISTANCE and close > zone.high * (
            1 + config.breakout_close_margin
        ):
            retest = detect_retest(candles, zone, i, config=config)
            if retest:
                return {
                    "type": "resistance_became_support",
                    "break_index": i,
                    "retest_index": retest["index"],
                }
        if zone.kind == ZoneKind.SUPPORT and close < zone.low * (1 - config.breakout_close_margin):
            retest = detect_retest(candles, zone, i, config=config)
            if retest:
                return {
                    "type": "support_became_resistance",
                    "break_index": i,
                    "retest_index": retest["index"],
                }
    return None


def is_level_invalidated(
    candles: list[dict[str, Any]],
    zone: Zone,
    *,
    config: PriceActionConfig | None = None,
) -> bool:
    """A zone is invalidated by two consecutive completed closes beyond it."""
    config = config or PriceActionConfig.from_settings()
    margin = config.breakout_close_margin
    streak = 0
    for c in candles:
        close = _f(c, "close")
        beyond = (
            close > zone.high * (1 + margin)
            if zone.kind == ZoneKind.RESISTANCE
            else close < zone.low * (1 - margin)
        )
        streak = streak + 1 if beyond else 0
        if streak >= 2:
            return True
    return False


__all__ = [
    "Zone",
    "count_touches",
    "detect_breakout_confirmation",
    "detect_rejection",
    "detect_retest",
    "detect_sbr_rbs",
    "detect_zones",
    "is_level_invalidated",
]
