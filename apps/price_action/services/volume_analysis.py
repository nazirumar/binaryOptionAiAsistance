"""Volume intelligence (Step 18).

Tick volume and real volume are **never** treated as interchangeable: every
result records which source was used. Volume agreement is descriptive only and
is never presented as proof of a future direction.
"""

from __future__ import annotations

from typing import Any

from apps.price_action.constants import VolumeSource
from apps.price_action.services.candle_math import candle_range
from apps.price_action.services.config import PriceActionConfig


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


def volume_of(candle: dict[str, Any]) -> tuple[float | None, str]:
    """Return (value, source). Real volume takes precedence; then tick volume."""
    real = candle.get("real_volume")
    if real is not None:
        return float(real), str(VolumeSource.REAL)
    tick = candle.get("tick_volume")
    if tick is None:
        tick = candle.get("volume")
    if tick is not None:
        return float(tick), str(VolumeSource.TICK)
    return None, str(VolumeSource.NONE)


def average_volume(candles: list[dict[str, Any]], lookback: int = 20) -> tuple[float | None, str]:
    window = candles[-lookback:]
    values: list[float] = []
    sources: set[str] = set()
    for c in window:
        value, source = volume_of(c)
        if value is not None:
            values.append(value)
            sources.add(source)
    if not values:
        return None, str(VolumeSource.NONE)
    source = next(iter(sources)) if len(sources) == 1 else str(VolumeSource.NONE)
    return sum(values) / len(values), source


def volume_effort_result(
    candle: dict[str, Any], *, avg_range: float | None = None
) -> dict[str, Any]:
    """Single-candle effort (volume) vs result (range)."""
    volume, source = volume_of(candle)
    rng = candle_range(candle)
    return {
        "volume": volume,
        "volume_source": source,
        "range": rng,
        "interpretable": rng > 0 and volume is not None,
        "avg_range": avg_range,
    }


def detect_volume_patterns(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> list[dict[str, Any]]:
    """Report volume anomalies and multi-candle volume sequences."""
    config = config or PriceActionConfig.from_settings()
    out: list[dict[str, Any]] = []
    avg_vol, _source = average_volume(candles, config.volume_lookback)
    if avg_vol is None or avg_vol <= 0:
        return out
    ranges = [candle_range(c) for c in candles[-config.volume_lookback :] if candle_range(c) > 0]
    avg_range = sum(ranges) / len(ranges) if ranges else None

    for i, c in enumerate(candles):
        volume, src = volume_of(c)
        if volume is None:
            continue
        rng = candle_range(c)
        rel_vol = volume / avg_vol
        rel_range = rng / avg_range if avg_range else None
        if (
            rel_vol >= config.high_volume_multiple
            and rel_range is not None
            and rel_range <= config.narrow_range_multiple
        ):
            out.append(
                {
                    "type": "high_volume_narrow_range",
                    "index": i,
                    "relative_volume": rel_vol,
                    "relative_range": rel_range,
                    "volume_source": src,
                    "note": "absorption candidate; descriptive only",
                }
            )
        if (
            rel_vol <= config.low_volume_multiple
            and rel_range is not None
            and rel_range >= config.wide_range_multiple
        ):
            out.append(
                {
                    "type": "low_volume_wide_range",
                    "index": i,
                    "relative_volume": rel_vol,
                    "relative_range": rel_range,
                    "volume_source": src,
                    "note": "thin-move candidate; descriptive only",
                }
            )

    # Multi-candle volume sequence over the trailing window.
    window = candles[-3:]
    seq = [volume_of(c)[0] for c in window]
    if all(v is not None for v in seq) and len(seq) == 3:
        a, b, c = (float(v) for v in seq)
        if a < b < c:
            out.append({"type": "rising_volume_sequence", "index": len(candles) - 1})
        elif a > b > c:
            out.append({"type": "falling_volume_sequence", "index": len(candles) - 1})
    return out


def reversal_pattern_volume_context(
    candles: list[dict[str, Any]], index: int, *, config: PriceActionConfig | None = None
) -> dict[str, Any]:
    """Describe the volume context around ``index`` without predicting direction."""
    config = config or PriceActionConfig.from_settings()
    if index < 0 or index >= len(candles):
        return {"available": False, "reason": "index out of range"}
    avg_vol, source = average_volume(candles[: index + 1], config.volume_lookback)
    volume, src = volume_of(candles[index])
    rel = (volume / avg_vol) if (volume is not None and avg_vol) else None
    return {
        "available": rel is not None,
        "relative_volume": rel,
        "volume_source": src,
        "average_source": source,
        "context": "elevated" if (rel or 0) >= config.high_volume_multiple else "normal",
    }


__all__ = [
    "average_volume",
    "detect_volume_patterns",
    "reversal_pattern_volume_context",
    "volume_effort_result",
    "volume_of",
]
