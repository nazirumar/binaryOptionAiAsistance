"""Generic ABC pivot pattern detector (Phase 12, CP7).

Labels a swing sequence A→B→C from confirmed swings: A is the origin swing, B
the first opposite retracement swing, C the next swing that *fails to exceed*
A (for an up-ABC) or to undercut A (for a down-ABC).

**This is a generic textbook reading of "ABC", labelled as such.** The course's
specific ABC rules (its exact retracement and extension thresholds) were not
available in machine-readable form; nothing here claims to implement them. All
thresholds are explicit, configurable and reported on the result.
"""

from __future__ import annotations

from typing import Any

from apps.price_action.constants import SwingKind
from apps.price_action.services.config import PriceActionConfig
from apps.price_action.services.market_structure import Swing, detect_swings


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


def _retracement_ratio(origin: float, extreme: float, turn: float) -> float | None:
    """Fraction of the A→extreme leg retraced at point B (0..1+, None if flat)."""
    leg = extreme - origin
    if leg == 0.0:
        return None
    return (turn - origin) / leg


def detect_abc(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> list[dict[str, Any]]:
    """Detect textbook ABC corrections from confirmed swings.

    Bullish reading (retracement in an up-leg): A = swing low, B = swing high,
    C = next swing low that holds above A. Bearish reading mirrored. A pattern
    is only reported when C actually exists — nothing is extrapolated from an
    unfinished leg.
    """
    config = config or PriceActionConfig.from_settings()
    swings = detect_swings(candles, config.swing_lookback)
    out: list[dict[str, Any]] = []
    for i in range(len(swings) - 2):
        a, b, c = swings[i], swings[i + 1], swings[i + 2]
        if a.kind == c.kind != b.kind:
            out.append(
                _evaluate(
                    a, b, c, "bullish_abc" if a.kind == SwingKind.LOW else "bearish_abc", config
                )
            )
    return [r for r in out if r is not None]


def _evaluate(
    a: Swing, b: Swing, c: Swing, kind: str, config: PriceActionConfig
) -> dict[str, Any] | None:
    ratio = _retracement_ratio(a.value, b.value, c.value)
    if ratio is None:
        return None
    if kind == "bullish_abc":
        # C must hold above A; B must be above A (up-leg then pullback).
        if not (b.value > a.value and c.value > a.value):
            return None
        leg_ratio = abs(b.value - a.value) / a.value if a.value else None
    else:
        if not (b.value < a.value and c.value < a.value):
            return None
        leg_ratio = abs(b.value - a.value) / a.value if a.value else None
    in_band = config.abc_retracement_min <= ratio <= config.abc_retracement_max
    return {
        "type": kind,
        "label": "generic_abc",
        "a": {"index": a.index, "kind": str(a.kind), "value": a.value},
        "b": {"index": b.index, "kind": str(b.kind), "value": b.value},
        "c": {"index": c.index, "kind": str(c.kind), "value": c.value},
        "retracement_ratio": ratio,
        "leg_ratio": leg_ratio,
        "within_textbook_band": in_band,
        "thresholds": {
            "retracement_min": config.abc_retracement_min,
            "retracement_max": config.abc_retracement_max,
            "min_leg_ratio": config.abc_min_leg_ratio,
        },
        "note": (
            "generic textbook ABC reading from confirmed swings; the course's "
            "specific ABC thresholds were not available and are not claimed"
        ),
        "requirements": [
            "three confirmed alternating swings (no unconfirmed pivots)",
            "C must actually exist — never extrapolated",
        ],
        "sufficient_for_entry": False,
    }


def abc_candidates(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any]:
    """All ABC candidates plus an honest summary of what is and isn't known."""
    config = config or PriceActionConfig.from_settings()
    candidates = detect_abc(candles, config=config)
    return {
        "candidates": candidates,
        "count": len(candidates),
        "label": "generic_abc",
        "course_specific_rules_available": False,
        "note": (
            "these are generic ABC candidates produced with explicit, reported "
            "thresholds. They are not course-validated and never sufficient for "
            "an entry on their own."
        ),
    }


__all__ = ["abc_candidates", "detect_abc"]
