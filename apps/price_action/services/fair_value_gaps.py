"""Fair value gap engine (Step 16).

A three-candle fair value gap exists when the wick of the first candle and the
wick of the third candle do not overlap, leaving an imbalance spanned by the
middle candle. Gaps are only confirmed once the third candle has **closed**.
"""

from __future__ import annotations

from typing import Any

from apps.price_action.constants import FVGState, FVGType
from apps.price_action.services.config import PriceActionConfig


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


def detect_fvg(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> list[dict[str, Any]]:
    """Return confirmed three-candle fair value gaps."""
    del config
    fvgs: list[dict[str, Any]] = []
    for i in range(2, len(candles)):
        left = candles[i - 2]
        right = candles[i]
        left_high = _f(left, "high")
        right_low = _f(right, "low")
        left_low = _f(left, "low")
        right_high = _f(right, "high")
        if left_high < right_low:
            fvgs.append(
                {
                    "type": str(FVGType.BULLISH),
                    "top": right_low,
                    "bottom": left_high,
                    "index": i,
                    "middle_index": i - 1,
                    "confirmed_by_close": True,
                }
            )
        if left_low > right_high:
            fvgs.append(
                {
                    "type": str(FVGType.BEARISH),
                    "top": left_low,
                    "bottom": right_high,
                    "index": i,
                    "middle_index": i - 1,
                    "confirmed_by_close": True,
                }
            )
    return fvgs


def _trades_into(candle: dict[str, Any], bottom: float, top: float) -> bool:
    return _f(candle, "low") <= top and _f(candle, "high") >= bottom


def classify_fvg_state(candles: list[dict[str, Any]], gap: dict[str, Any]) -> str:
    """Mitigation = traded back into the gap; invalidation = closed fully through."""
    bottom = gap["bottom"]
    top = gap["top"]
    gap_index = gap["index"]
    for c in candles[gap_index + 1 :]:
        if not _trades_into(c, bottom, top):
            continue
        if gap["type"] == str(FVGType.BULLISH) and _f(c, "close") < bottom:
            return FVGState.INVALIDATED
        if gap["type"] == str(FVGType.BEARISH) and _f(c, "close") > top:
            return FVGState.INVALIDATED
        return FVGState.MITIGATED
    return FVGState.OPEN


def annotate_fvg_states(
    candles: list[dict[str, Any]], gaps: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    for gap in gaps:
        gap["state"] = str(classify_fvg_state(candles, gap))
    return gaps


def fvg_sweep_confluence(
    gaps: list[dict[str, Any]], sweeps: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Report gaps whose level coincides with a detected sweep level."""
    out: list[dict[str, Any]] = []
    for gap in gaps:
        for sweep in sweeps:
            if gap["bottom"] <= sweep["level"] <= gap["top"]:
                out.append(
                    {
                        "fvg_index": gap["index"],
                        "sweep_index": sweep["index"],
                        "type": gap["type"],
                        "level": sweep["level"],
                        "note": "FVG and sweep levels coincide; confluence is descriptive",
                    }
                )
    return out


__all__ = [
    "annotate_fvg_states",
    "classify_fvg_state",
    "detect_fvg",
    "fvg_sweep_confluence",
]
