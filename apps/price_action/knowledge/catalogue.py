"""Versioned knowledge catalogue (Step 22).

For every concept the engine implements, the catalogue documents:

* the original course interpretation,
* the objective implementation definition,
* required inputs,
* detection logic,
* known limitations,
* configurable thresholds,
* a representative test case,
* related concepts and conflicting conditions.

Concepts whose course definition is ambiguous are explicitly marked as
**research hypotheses**; nothing here is described as a proven strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.price_action.constants import PA_KNOWLEDGE_VERSION


@dataclass(frozen=True, slots=True)
class Concept:
    key: str
    title: str
    course_interpretation: str
    implementation: str
    required_inputs: tuple[str, ...]
    detection_logic: str
    limitations: tuple[str, ...]
    thresholds: tuple[str, ...] = ()
    test_case: str = ""
    related: tuple[str, ...] = ()
    conflicting: tuple[str, ...] = ()
    research_hypothesis: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "course_interpretation": self.course_interpretation,
            "implementation": self.implementation,
            "required_inputs": list(self.required_inputs),
            "detection_logic": self.detection_logic,
            "limitations": list(self.limitations),
            "thresholds": list(self.thresholds),
            "test_case": self.test_case,
            "related": list(self.related),
            "conflicting": list(self.conflicting),
            "research_hypothesis": self.research_hypothesis,
        }


CONCEPTS: tuple[Concept, ...] = (
    Concept(
        key="market_structure",
        title="Market structure and swing points",
        course_interpretation="Price trends through higher highs/lows or lower highs/lows.",
        implementation="Confirmed swings labelled HH/HL/LH/LL; trend inferred from labels.",
        required_inputs=("completed OHLC candles", "swing_lookback"),
        detection_logic="A swing is confirmed only with lookback candles on both sides.",
        limitations=("Plateaus can delay confirmation", "Lookback changes the labelling"),
        thresholds=("PA_SWING_LOOKBACK", "PA_EQUAL_LEVEL_TOLERANCE"),
        test_case="tests/test_price_action_structure.py::test_uptrend",
        related=("support_resistance",),
        conflicting=("consolidation",),
    ),
    Concept(
        key="support_resistance",
        title="Support and resistance zones",
        course_interpretation="Repeated levels reject and later flip roles.",
        implementation="Zones built from clustered swings with explicit width.",
        required_inputs=("completed OHLC candles", "zone_tolerance"),
        detection_logic="Cluster swing values; count touches; require min touches.",
        limitations=("Zones are approximate", "Breakouts do not always retest"),
        thresholds=("PA_ZONE_TOLERANCE", "PA_ZONE_MIN_TOUCHES"),
        test_case="tests/test_price_action_structure.py::test_zone_detection",
        related=("buyer_seller_failure",),
    ),
    Concept(
        key="buyer_seller_failure",
        title="Buyer and seller failure",
        course_interpretation="The side that fails to break a level often yields.",
        implementation="Observable attempts, failures and ordered events around zones.",
        required_inputs=("completed OHLC candles", "support/resistance zones"),
        detection_logic="Track wick attempts and closes back inside a zone.",
        limitations=("Intent is never observable", "Failure can precede continuation"),
        thresholds=("PA_ZONE_TOLERANCE",),
        test_case="tests/test_price_action_buyer_seller.py::test_failure_detected",
        related=("support_resistance", "sweeps"),
        conflicting=("sweep_without_recovery",),
        research_hypothesis=True,
    ),
    Concept(
        key="candlestick_patterns",
        title="Candlestick patterns",
        course_interpretation="Specific candle shapes encode pressure shifts.",
        implementation="14 shape predicates returning candle refs, context and invalidation.",
        required_inputs=("completed OHLC candles",),
        detection_logic="Geometric body/wick/close relations over 1-3 candles.",
        limitations=("Context is required", "Shapes alone are not signals"),
        thresholds=("PA_DOJI_BODY_RATIO_MAX", "PA_SMALL_BODY_RATIO_MAX"),
        test_case="tests/test_price_action_patterns.py::test_bullish_engulfing",
        related=("candle_sequences",),
    ),
    Concept(
        key="candle_sequences",
        title="Reference, similar, lonely and psychological sequences",
        course_interpretation="Runs of candles carry a rhythm the trader reads.",
        implementation="Directional runs, past-only signature matching, isolated candles.",
        required_inputs=("completed OHLC candles", "signature length"),
        detection_logic="Sign sequence matching against strictly earlier windows.",
        limitations=("Run length is descriptive", "Similarity is not prediction"),
        thresholds=("PA_SEQUENCE_SIGNATURE_LENGTH", "PA_SIMILAR_SEQUENCE_MIN_SAMPLES"),
        test_case="tests/test_price_action_sequences.py::test_psych_template",
        related=("candlestick_patterns",),
        conflicting=("overfitting",),
        research_hypothesis=True,
    ),
    Concept(
        key="market_cycle",
        title="Market cycle waves",
        course_interpretation="Motive, counter and last-effort waves precede reversals.",
        implementation="Candidate cycle phase from labelled swings; never 'confirmed'.",
        required_inputs=("completed OHLC candles", "swing_lookback"),
        detection_logic="Compare last two swing labels of each kind.",
        limitations=("Wave boundaries are ambiguous", "Last-effort mimics counter wave"),
        thresholds=("PA_SWING_LOOKBACK",),
        test_case="tests/test_price_action_cycle.py::test_reversal_candidate",
        related=("market_structure",),
        research_hypothesis=True,
    ),
    Concept(
        key="liquidity_sweeps",
        title="Liquidity sweeps",
        course_interpretation="Wicks take out stops before reversing.",
        implementation="Observable sweep classification: rejection vs continuation.",
        required_inputs=("completed OHLC candles", "prior range"),
        detection_logic="Wick beyond prior extreme and close back inside.",
        limitations=("Stop-hunting is not directly observable", "Recovery may fail"),
        thresholds=("PA_SWEEP_MIN_PENETRATION", "PA_REJECTION_WICK_MIN"),
        test_case="tests/test_price_action_sweeps_gaps.py::test_low_sweep_rejection",
        related=("support_resistance", "fair_value_gaps"),
        conflicting=("sweep_without_recovery",),
        research_hypothesis=True,
    ),
    Concept(
        key="order_blocks",
        title="Order blocks",
        course_interpretation="The candle before a strong move marks a reaction zone.",
        implementation="Two separate definitions (teacher pattern, ICT style), never merged.",
        required_inputs=("completed OHLC candles", "definition"),
        detection_logic="Last opposing candle before a strong departure.",
        limitations=("Definitions disagree", "Institutional orders are not observable"),
        thresholds=("PA_STRONG_BODY_RATIO_MIN", "PA_STRONG_RANGE_MULTIPLE"),
        test_case="tests/test_price_action_sweeps_gaps.py::test_order_block_teacher",
        related=("fair_value_gaps", "liquidity_sweeps"),
        research_hypothesis=True,
    ),
    Concept(
        key="fair_value_gaps",
        title="Fair value gaps",
        course_interpretation="An imbalance between three candles tends to be revisited.",
        implementation="Three-candle non-overlap with mitigation/invalidation states.",
        required_inputs=("completed OHLC candles",),
        detection_logic="left.high < right.low (bullish) or left.low > right.high (bearish).",
        limitations=("Mitigation timing varies", "Gaps can stay open indefinitely"),
        thresholds=(),
        test_case="tests/test_price_action_sweeps_gaps.py::test_bullish_fvg",
        related=("liquidity_sweeps",),
        research_hypothesis=True,
    ),
    Concept(
        key="opening_gaps",
        title="Opening gaps",
        course_interpretation="A close-to-open gap reflects a jump in price.",
        implementation="Numerical gaps only; visual spacing is explicitly out of scope.",
        required_inputs=("completed OHLC candles", "opening_gap_min_size"),
        detection_logic="cur.open != prev.close beyond the minimum size.",
        limitations=("Rendering can create apparent (non) gaps",),
        thresholds=("PA_OPENING_GAP_MIN_SIZE",),
        test_case="tests/test_price_action_sweeps_gaps.py::test_bullish_gap",
        related=("fair_value_gaps",),
    ),
    Concept(
        key="volume",
        title="Volume intelligence",
        course_interpretation="Effort (volume) should be proportional to result (range).",
        implementation="Effort/result ratios and anomaly flags, tick vs real kept separate.",
        required_inputs=("volume (tick or real)", "candles"),
        detection_logic="Relate volume and range to their rolling averages.",
        limitations=("Tick and real volume differ", "Volume is not direction"),
        thresholds=("PA_HIGH_VOLUME_MULTIPLE", "PA_NARROW_RANGE_MULTIPLE"),
        test_case="tests/test_price_action_volume.py::test_high_volume_narrow_range",
        related=("market_context",),
    ),
    Concept(
        key="market_context",
        title="Market context",
        course_interpretation="Session, regime and volatility frame every setup.",
        implementation="Pure classifiers; news status is UNKNOWN without a source.",
        required_inputs=("timezone-aware datetime", "candles"),
        detection_logic="UTC session mapping, regime/volatility from ranges.",
        limitations=("Session boundaries are coarse", "No calendar unless injected"),
        thresholds=("PA_HIGH_VOLATILITY_MULTIPLE",),
        test_case="tests/test_price_action_context.py::test_session",
        related=("volume",),
    ),
)


def catalogue() -> dict[str, Any]:
    return {
        "knowledge_version": PA_KNOWLEDGE_VERSION,
        "concepts": [c.to_dict() for c in CONCEPTS],
        "note": "Research concepts, not proven strategies.",
    }


def get_concept(key: str) -> Concept | None:
    return next((c for c in CONCEPTS if c.key == key), None)


__all__ = ["CONCEPTS", "Concept", "catalogue", "get_concept"]
