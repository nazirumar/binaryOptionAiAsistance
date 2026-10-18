# book_strategies/services/explainer.py
"""Deterministic, knowledge-grounded explanation of a book-strategy detection.

Answers the ten questions from the Phase 13 brief using ONLY the stored
detection record and the catalogued strategy definition. The language model
never generates this content - it receives it as context - so an explanation
cannot invent a detection, a level, or a direction the detector did not report.

If the detection carries no completed setup, the explanation says exactly that
(hallucination resistance: no strategy is asserted from an empty detection).
"""

from __future__ import annotations

from typing import Any

from apps.book_strategies.constants import (
    DECISION_NO_TRADE,
    SPEC_BY_KEY,
    BookPatternState,
)

NO_DETECTION_TEXT = (
    "No book strategy is detected on the provided evidence; nothing can be "
    "asserted about pattern number, level, or direction."
)


def explain(
    detection: Any,
    *,
    last_candle_complete: bool = True,
    strategy: Any = None,
) -> dict[str, Any]:
    """Build the structured explanation mapping (Step 5 question set)."""
    spec = SPEC_BY_KEY.get(getattr(detection, "strategy_key", ""))

    state = getattr(detection, "recognition_status", BookPatternState.INSUFFICIENT_DATA)
    # Only a sequence that actually exists (or fired an invalidation) counts
    # as a detection. A FORMING candidate has not been detected yet.
    detected = (
        state
        in (
            BookPatternState.CONFIRMED_PATTERN,
            BookPatternState.AWAITING_CONFIRMATION,
            BookPatternState.INVALIDATED,
        )
        and bool(getattr(detection, "observed_evidence", []))
    )

    if not detected or spec is None:
        which = NO_DETECTION_TEXT
        if spec is not None and state == BookPatternState.FORMING:
            which = (
                f"{NO_DETECTION_TEXT} Candidate {spec.key} ({spec.name}) was "
                "checked but its book sequence has not formed on the provided "
                "candles."
            )
        return {
            "which_strategy": which,
            "pattern_number": None,
            "pattern_candles": [],
            "reference_level": None,
            "breakout_happened": None,
            "last_candle_complete": last_candle_complete,
            "missing_conditions": list(getattr(detection, "missing_conditions", []) or []),
            "invalidation": [],
            "direction_rationale": NO_DETECTION_TEXT,
            "no_trade_rationale": (
                "The evidence does not establish a completed book setup, so "
                "the decision is NO TRADE."
            ),
            "decision": DECISION_NO_TRADE,
        }

    refs = list(getattr(detection, "candle_refs", []) or [])
    level = getattr(detection, "reference_level", None)
    level_kind = getattr(detection, "level_kind", "")
    direction = getattr(detection, "direction", "neutral")
    completed_at = getattr(detection, "completed_at", None)
    missing = list(getattr(detection, "missing_conditions", []) or [])
    invalidations = list(getattr(detection, "invalidations", []) or [])
    contradictions = list(getattr(detection, "contradictions", []) or [])

    # Breakout status derived strictly from the detector's own fields.
    breakout_happened: bool | None
    if state == BookPatternState.CONFIRMED_PATTERN and level is not None:
        breakout_happened = True
    elif state == BookPatternState.CONFIRMED_PATTERN:
        breakout_happened = None  # sequence patterns have no single level
    elif level is not None:
        breakout_happened = False
    else:
        breakout_happened = False

    if direction == "bullish":
        direction_rationale = (
            f"The book's {spec.key} rule for the up variant is satisfied on "
            f"candles {refs}: " + (spec.confirmation_rule or "")
        )
    elif direction == "bearish":
        direction_rationale = (
            f"The book's {spec.key} rule for the down variant is satisfied on "
            f"candles {refs}: " + (spec.confirmation_rule or "")
        )
    else:
        direction_rationale = (
            "No direction is asserted: required conditions are missing or the "
            "setup is invalidated."
        )

    missing_text = list(missing)
    if not last_candle_complete:
        missing_text.append("the last candle on the chart is still forming")
    missing_text.extend(
        "book contradiction recorded (not repaired): " + item
        for item in contradictions
    )

    if state == BookPatternState.CONFIRMED_PATTERN:
        no_trade = (
            "Every deterministic book condition is met, but a recognised "
            "pattern is an observation, not a calibrated prediction: no "
            "approved validation exists for this strategy's next-candle "
            "probability, so the decision stays NO TRADE."
        )
    elif state == BookPatternState.INVALIDATED:
        no_trade = (
            "The book's own invalidation rule fired, so NO TRADE is the only "
            "correct outcome."
        )
    else:
        no_trade = (
            "Conditions are incomplete (or the data is insufficient), so the "
            "decision is NO TRADE - a partial pattern is never traded."
        )

    return {
        "which_strategy": f"{spec.key} - {spec.name}",
        "pattern_number": spec.number,
        "pattern_candles": refs,
        "reference_level": {"value": level, "kind": level_kind},
        "breakout_happened": breakout_happened,
        "last_candle_complete": last_candle_complete,
        "missing_conditions": missing_text,
        "invalidation": list(invalidations) or list(spec.invalidation_rules),
        "direction_rationale": direction_rationale,
        "no_trade_rationale": no_trade,
        "completed_at": completed_at,
        "decision": DECISION_NO_TRADE,
    }
