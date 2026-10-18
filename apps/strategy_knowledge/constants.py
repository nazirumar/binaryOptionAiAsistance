# apps/strategy_knowledge/constants.py
"""Enumerations for the versioned strategy knowledge base.

Values are *vocabulary only*: they name verification outcomes, condition kinds
and provenance so downstream services never have to guess semantics.
"""

from __future__ import annotations

from django.db import models


class ValidationStatus(models.TextChoices):
    """Review state of a strategy definition."""

    DRAFT = "draft", "Draft"
    REVIEWED = "reviewed", "Reviewed"
    APPROVED = "approved", "Approved"
    EXPERIMENTAL = "experimental", "Experimental"
    RETIRED = "retired", "Retired"


class ConditionKind(models.TextChoices):
    """Role a structured condition plays inside a strategy definition."""

    REQUIRED = "required", "Required condition"
    OPTIONAL = "optional", "Optional confirmation"
    CONTRADICTORY = "contradictory", "Contradictory evidence"
    INVALIDATION = "invalidation", "Invalidation condition"


class StrategyVariant(models.TextChoices):
    """Directional variant of a strategy definition."""

    BULLISH = "bullish", "Bullish"
    BEARISH = "bearish", "Bearish"
    NEUTRAL = "neutral", "Neutral / two-sided"


class DetectionStatus(models.TextChoices):
    """Outcome of verifying a strategy candidate against evidence."""

    DETECTED = "detected", "Detected"
    POSSIBLE = "possible", "Possible"
    REJECTED = "rejected", "Rejected"
    INSUFFICIENT = "insufficient_evidence", "Insufficient evidence"


class EvidenceProvenance(models.TextChoices):
    """Where the evidence backing a detection came from."""

    VISION = "vision", "Screenshot vision (pixel/qualitative evidence)"
    OHLC = "ohlc", "Verified OHLC candles"
    HYBRID = "hybrid", "Vision candidates verified with OHLC candles"
    SCREENSHOT_ONLY = "screenshot_only", "Screenshot-only (no OHLC confirmation)"


class ConditionSource(models.TextChoices):
    """How a condition's truth was established during verification."""

    DETERMINISTIC = "deterministic", "Deterministic detector"
    VISION = "vision", "Vision observation"
    MISSING = "missing", "Evidence not available"


class DatasetSampleKind(models.TextChoices):
    """Label class of a dataset sample (CP14)."""

    POSITIVE = "positive", "Valid pattern"
    NEGATIVE = "negative", "Invalid pattern"
    INCOMPLETE = "incomplete", "Incomplete pattern"
    LOOKALIKE = "lookalike", "Lookalike (not the pattern)"
    POOR_QUALITY = "poor_quality", "Poor-quality screenshot"
    OTC = "otc", "OTC screenshot"


class LabelSource(models.TextChoices):
    """Who/what produced a dataset label. Vision guesses are never ground truth."""

    REVIEWER = "reviewer", "Human reviewer"
    COURSE = "course", "Course material"
    VISION_CANDIDATE = "vision_candidate", "Vision model candidate (unverified)"


#: Registry values that reference deterministic detectors. Definitions whose
#: ``detector_key`` is not in this mapping are *inert*: they display fine but
#: can never execute anything, which is what keeps database content from
#: running arbitrary logic.
DETECTOR_KEYS = (
    "cs.bullish_engulfing",
    "cs.bearish_engulfing",
    "cs.bullish_pin_bar",
    "cs.bearish_pin_bar",
    "cs.hammer",
    "cs.inverted_hammer",
    "cs.shooting_star",
    "cs.hanging_man",
    "cs.doji",
    "cs.dragonfly_doji",
    "cs.gravestone_doji",
    "cs.spinning_top",
    "cs.bullish_harami",
    "cs.bearish_harami",
    "cs.inside_bar",
    "cs.outside_bar",
    "cs.morning_star",
    "cs.evening_star",
    "cs.three_white_soldiers",
    "cs.three_black_crows",
    "cs.tweezer_top",
    "cs.tweezer_bottom",
    "cs.piercing",
    "cs.dark_cloud_cover",
    "sr.support_rejection",
    "sr.resistance_rejection",
    "sr.support_becomes_resistance",
    "sr.resistance_becomes_support",
    "sr.breakout_retest",
    "sr.false_breakout",
    "sr.failed_support_test",
    "sr.failed_resistance_test",
    "sr.multi_touch",
    "sr.engulfing_at_support",
    "sr.engulfing_at_resistance",
    "sr.doji_above_support",
    "sr.doji_below_resistance",
    "ms.bos_bullish",
    "ms.bos_bearish",
    "ms.choch_bullish",
    "ms.choch_bearish",
    "ms.mss_bullish",
    "ms.mss_bearish",
    "ms.trend_exhaustion",
    "ms.failed_structural_break",
    "liq.bullish_sweep",
    "liq.bearish_sweep",
    "liq.equal_highs",
    "liq.equal_lows",
    "liq.inducement",
    "liq.displacement",
    "fvg.bullish",
    "fvg.bearish",
    "fvg.retest",
    "ob.bullish",
    "ob.bearish",
    "ob.breaker",
    "ob.mitigation",
    "zone.premium_discount",
    "cycle.motive_wave",
    "cycle.counter_wave",
    "cycle.weak_last_effort",
    "cycle.new_motive_wave",
    "psy.buyer_failure",
    "psy.seller_failure",
    "psy.reference_sequence",
    "psy.similar_sequence",
    "psy.lonely_candle",
    "psy.candle_progress",
    "psy.run_count",
    "psy.strong_close",
    "psy.weak_close",
    "psy.failed_continuation",
    "abc.generic",
)

__all__ = [
    "DETECTOR_KEYS",
    "ConditionKind",
    "ConditionSource",
    "DatasetSampleKind",
    "DetectionStatus",
    "EvidenceProvenance",
    "LabelSource",
    "StrategyVariant",
    "ValidationStatus",
]
