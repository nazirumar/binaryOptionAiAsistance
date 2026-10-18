"""Normalisation of candle observations read from the screenshot.

Responsibilities:

* Derive a left-to-right *relative position* band when the model does not
  provide one (never a fabricated price).
* **Always** treat the rightmost candle as potentially incomplete: a static
  screenshot cannot prove a candle has closed, so the last candle is marked
  ``appears_complete = False`` with an explicit ambiguity note and warning.
* Keep the model's own claim (if any) in `provider_claimed_complete` for audit.
"""

from __future__ import annotations

from typing import Any

from apps.chart_vision.constants import UNKNOWN, CandleClassification

#: Bands from left to right, used when a relative position is not supplied.
_POSITION_BANDS = ("left", "mid-left", "middle", "mid-right", "right")


def position_band(index: int, total: int) -> str:
    """Return a qualitative horizontal band for the candle at ``index``."""
    if total <= 1:
        return "middle"
    ratio = index / float(total - 1)
    if ratio <= 0.125:
        return "left"
    if ratio <= 0.375:
        return "mid-left"
    if ratio < 0.625:
        return "middle"
    if ratio < 0.875:
        return "mid-right"
    return "right"


def normalize_candles(
    candles: list[dict[str, Any]] | None, warnings: list[str]
) -> list[dict[str, Any]]:
    """Return a normalised candle list with the rightmost-candle safeguard."""
    items = [dict(candle) for candle in (candles or []) if isinstance(candle, dict)]
    if not items:
        warnings.append("No candles could be reliably identified in the screenshot.")
        return items

    total = len(items)
    for index, candle in enumerate(items):
        if not candle.get("position") or candle.get("position") == UNKNOWN:
            candle["position"] = position_band(index, total)
        if candle.get("classification") in (None, ""):
            candle["classification"] = CandleClassification.UNKNOWN

    last = items[-1]
    claimed = last.get("appears_complete")
    last["appears_complete"] = False
    last["provider_claimed_complete"] = claimed
    if claimed is True:
        note = (
            "Provider reported the rightmost candle as complete, but completion "
            "cannot be verified from a static screenshot; treated as potentially "
            "incomplete."
        )
    else:
        note = "Rightmost candle may still be forming; treated as incomplete."
    last["ambiguity"] = last.get("ambiguity") or note
    warnings.append(note)
    return items


def has_incomplete_rightmost(candles: list[dict[str, Any]] | None) -> bool:
    """True when the rightmost candle is flagged (or assumed) incomplete."""
    if not candles:
        return False
    return not bool(candles[-1].get("appears_complete", False))


def summarize_candles(candles: list[dict[str, Any]] | None) -> str:
    """One-line, non-predictive summary of the candle observations."""
    items = candles or []
    if not items:
        return "No candles identified."
    bullish = sum(1 for c in items if c.get("classification") == CandleClassification.BULLISH)
    bearish = sum(1 for c in items if c.get("classification") == CandleClassification.BEARISH)
    doji = sum(1 for c in items if c.get("classification") == CandleClassification.DOJI)
    return (
        f"{len(items)} candle(s): {bullish} bullish, {bearish} bearish, {doji} doji. "
        "Rightmost candle treated as potentially incomplete."
    )


__all__ = [
    "has_incomplete_rightmost",
    "normalize_candles",
    "position_band",
    "summarize_candles",
]
