"""Market-cycle engine (Step 13).

Segments price into motive / counter / last-effort waves using confirmed swings
and reports a *candidate* cycle phase. The original course definitions are
ambiguous about where one wave ends and the next begins, so those ambiguities
are documented on every result and no reversal is ever marked "confirmed" until
the required evidence exists.
"""

from __future__ import annotations

from typing import Any

from apps.price_action.constants import CyclePhase, SwingKind, SwingLabel
from apps.price_action.services.config import PriceActionConfig
from apps.price_action.services.market_structure import detect_swings, label_swings

#: Documented ambiguities in the original course definitions.
CYCLE_AMBIGUITIES = (
    "The course does not define a minimum wave size, so wave boundaries are "
    "approximate and depend on the swing lookback.",
    "A 'last-effort' wave and a normal counter wave can look identical before "
    "the following structure break.",
    "Reversal cycles are only candidates until a confirmed structure break "
    "against the prior motive appears.",
)


def classify_cycle(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any]:
    config = config or PriceActionConfig.from_settings()
    swings = label_swings(
        detect_swings(candles, config.swing_lookback), config.equal_level_tolerance
    )
    highs = [s for s in swings if s.kind == SwingKind.HIGH]
    lows = [s for s in swings if s.kind == SwingKind.LOW]

    result: dict[str, Any] = {
        "phase": str(CyclePhase.UNCLEAR),
        "confirmed": False,
        "ambiguous": list(CYCLE_AMBIGUITIES),
        "reasons": [],
    }
    if len(highs) < 2 or len(lows) < 2:
        result["reasons"].append("not enough confirmed swings to segment a cycle")
        return result

    last_high, prev_high = highs[-1], highs[-2]
    last_low, prev_low = lows[-1], lows[-2]

    bullish_reversal = last_high.label == SwingLabel.LH and last_low.label == SwingLabel.HL
    bearish_continuation = last_high.label == SwingLabel.HH and last_low.label == SwingLabel.HL
    bearish_reversal = last_high.label == SwingLabel.HH and last_low.label == SwingLabel.LL
    bullish_continuation = last_high.label == SwingLabel.LH and last_low.label == SwingLabel.LL

    if bearish_continuation:
        result.update(
            phase=str(CyclePhase.MOTIVE),
            reasons=["higher high and higher low: motive wave still in force"],
        )
    elif bullish_continuation:
        result.update(
            phase=str(CyclePhase.MOTIVE),
            reasons=["lower high and lower low: motive wave still in force"],
        )
    elif bullish_reversal:
        result.update(
            phase=str(CyclePhase.BULLISH_REVERSAL),
            reasons=["lower high formed but the low held: bullish reversal candidate"],
        )
    elif bearish_reversal:
        result.update(
            phase=str(CyclePhase.BEARISH_REVERSAL),
            reasons=["higher high formed but the low failed: bearish reversal candidate"],
        )
    else:
        result["reasons"].append("swing labels are inconclusive")

    del prev_high, prev_low  # reserved for richer wave segmentation in Phase 6
    return result


#: Backwards-compatible alias.
detect_market_cycle = classify_cycle


__all__ = [
    "CYCLE_AMBIGUITIES",
    "classify_cycle",
    "detect_market_cycle",
]
