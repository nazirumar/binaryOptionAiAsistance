"""Opening gap engine (Step 17).

Only *numerical* gaps between one candle's close and the next candle's open are
reported. Visually apparent spacing caused by chart rendering is **not** a gap
and cannot be detected here; the engine says so explicitly rather than guessing.
"""

from __future__ import annotations

from typing import Any

from apps.price_action.constants import GapType
from apps.price_action.services.config import PriceActionConfig


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


def detect_opening_gaps(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> list[dict[str, Any]]:
    config = config or PriceActionConfig.from_settings()
    gaps: list[dict[str, Any]] = []
    for i in range(1, len(candles)):
        prev = candles[i - 1]
        cur = candles[i]
        prev_close = _f(prev, "close")
        cur_open = _f(cur, "open")
        if prev_close <= 0:
            continue
        if cur_open > prev_close:
            size = (cur_open - prev_close) / prev_close
            if size >= config.opening_gap_min_size:
                gaps.append(
                    {
                        "type": str(GapType.BULLISH),
                        "index": i,
                        "size": size,
                        "gap_bottom": prev_close,
                        "gap_top": cur_open,
                        "note": "numerical close-to-open gap only",
                    }
                )
        elif cur_open < prev_close:
            size = (prev_close - cur_open) / prev_close
            if size >= config.opening_gap_min_size:
                gaps.append(
                    {
                        "type": str(GapType.BEARISH),
                        "index": i,
                        "size": size,
                        "gap_bottom": cur_open,
                        "gap_top": prev_close,
                        "note": "numerical close-to-open gap only",
                    }
                )
    return gaps


#: Backwards-compatible singular alias.
detect_opening_gap = detect_opening_gaps


def gap_reaction(candles: list[dict[str, Any]], gap: dict[str, Any]) -> str:
    """Classify how price behaved after a gap: filled / continuation / reversal / pending."""
    bottom = gap["gap_bottom"]
    top = gap["gap_top"]
    for c in candles[gap["index"] + 1 :]:
        low = _f(c, "low")
        high = _f(c, "high")
        if low <= bottom and high >= top:
            return "filled"
        if gap["type"] == str(GapType.BULLISH) and _f(c, "close") > top:
            return "continuation"
        if gap["type"] == str(GapType.BEARISH) and _f(c, "close") < bottom:
            return "continuation"
        if gap["type"] == str(GapType.BULLISH) and _f(c, "close") < bottom:
            return "reversal"
        if gap["type"] == str(GapType.BEARISH) and _f(c, "close") > top:
            return "reversal"
    return "pending"


def annotate_gap_reactions(
    candles: list[dict[str, Any]], gaps: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    for gap in gaps:
        gap["reaction"] = gap_reaction(candles, gap)
    return gaps


__all__ = [
    "annotate_gap_reactions",
    "detect_opening_gap",
    "detect_opening_gaps",
    "gap_reaction",
]
