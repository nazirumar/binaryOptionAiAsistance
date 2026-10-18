"""Enumerations and constant registries for the price-action knowledge engine.

Nothing in this module makes a trading decision. It only names the *observable*
concepts the detectors are allowed to report, so downstream phases can consume a
stable vocabulary. Values are expressed as :class:`~django.db.models.TextChoices`
to match the rest of the project.
"""

from __future__ import annotations

from django.db import models


class EvidenceStatus(models.TextChoices):
    """Whether a rule's conditions were met on the supplied candles."""

    DETECTED = "detected", "Detected"
    NOT_DETECTED = "not_detected", "Not detected"
    INSUFFICIENT = "insufficient", "Insufficient evidence"
    CONFLICTING = "conflicting", "Conflicting"
    INVALIDATED = "invalidated", "Invalidated"


class Direction(models.TextChoices):
    """Directional interpretation attached to an evidence item."""

    BULLISH = "bullish", "Bullish"
    BEARISH = "bearish", "Bearish"
    NEUTRAL = "neutral", "Neutral"


class PatternDirection(models.TextChoices):
    """Extended directional class used by candlestick patterns."""

    BULLISH = "bullish", "Bullish"
    BEARISH = "bearish", "Bearish"
    NEUTRAL = "neutral", "Neutral"
    REVERSAL = "reversal", "Reversal"
    CONTINUATION = "continuation", "Continuation"


class TrendDirection(models.TextChoices):
    BULLISH = "bullish", "Bullish"
    BEARISH = "bearish", "Bearish"
    RANGING = "ranging", "Ranging"
    UNCLEAR = "unclear", "Unclear"


class SwingKind(models.TextChoices):
    HIGH = "high", "Swing high"
    LOW = "low", "Swing low"


class SwingLabel(models.TextChoices):
    """Structural label of a swing relative to the previous same-kind swing."""

    HH = "HH", "Higher high"
    HL = "HL", "Higher low"
    LH = "LH", "Lower high"
    LL = "LL", "Lower low"
    EQ = "EQ", "Equal"
    UNKNOWN = "unknown", "Unknown"


class StructureState(models.TextChoices):
    BULLISH = "bullish_structure", "Bullish structure"
    BEARISH = "bearish_structure", "Bearish structure"
    RANGING = "ranging_structure", "Ranging structure"
    UNCLEAR = "unclear", "Unclear"


class ZoneKind(models.TextChoices):
    SUPPORT = "support", "Support"
    RESISTANCE = "resistance", "Resistance"


class ZoneState(models.TextChoices):
    ACTIVE = "active", "Active"
    BROKEN = "broken", "Broken"
    INVALIDATED = "invalidated", "Invalidated"
    FLIPPED = "flipped", "Flipped (SBR/RBS)"


class RejectionKind(models.TextChoices):
    WICK_REJECTION = "wick_rejection", "Wick rejection"
    CLOSE_REJECTION = "close_rejection", "Candle-close rejection"


class DataQuality(models.TextChoices):
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"
    UNKNOWN = "unknown", "Unknown"
    UNUSABLE = "unusable", "Unusable"


class CandleStrength(models.TextChoices):
    STRONG_BULLISH = "strong_bullish", "Strong bullish"
    STRONG_BEARISH = "strong_bearish", "Strong bearish"
    WEAK = "weak", "Weak"
    NEUTRAL = "neutral", "Neutral"
    UNKNOWN = "unknown", "Unknown"


class VolumeSource(models.TextChoices):
    """Where a volume figure came from; sources are never interchangeable."""

    TICK = "tick_volume", "Tick volume"
    REAL = "real_volume", "Real volume"
    NONE = "none", "Unavailable"


class GapType(models.TextChoices):
    BULLISH = "bullish", "Bullish"
    BEARISH = "bearish", "Bearish"


class FVGType(models.TextChoices):
    BULLISH = "bullish_fvg", "Bullish FVG"
    BEARISH = "bearish_fvg", "Bearish FVG"


class FVGState(models.TextChoices):
    OPEN = "open", "Open"
    MITIGATED = "mitigated", "Mitigated"
    INVALIDATED = "invalidated", "Invalidated"


class MarketType(models.TextChoices):
    FOREX = "forex", "Forex"
    OTC = "otc", "OTC"
    UNKNOWN = "unknown", "Unknown"


class MarketRegime(models.TextChoices):
    TRENDING = "trending", "Trending"
    RANGING = "ranging", "Ranging"
    CHOPPY = "choppy", "Choppy"
    UNKNOWN = "unknown", "Unknown"


class VolatilityState(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    UNKNOWN = "unknown", "Unknown"


class TradingSession(models.TextChoices):
    ASIAN = "asian", "Asian"
    LONDON = "london", "London"
    NEW_YORK = "new_york", "New York"
    LONDON_NY_OVERLAP = "london_ny_overlap", "London-New York overlap"
    ASIAN_LONDON_OVERLAP = "asian_london_overlap", "Asian-London overlap"
    OFF_HOURS = "off_hours", "Off-hours"
    UNKNOWN = "unknown", "Unknown"


class NewsStatus(models.TextChoices):
    """Result of the (optional) economic-calendar proximity interface."""

    NO_EVENT_NEARBY = "no_event_nearby", "No event nearby"
    EVENT_NEARBY = "event_nearby", "Event nearby"
    UNKNOWN = "news_status_unknown", "News status unknown"


class SweepType(models.TextChoices):
    HIGH_SWEEP = "high_sweep", "High sweep"
    LOW_SWEEP = "low_sweep", "Low sweep"


class SweepOutcome(models.TextChoices):
    REJECTION = "rejection", "Rejection sweep"
    CONTINUATION = "continuation", "Continuation after sweep"
    INSUFFICIENT_RECOVERY = "insufficient_recovery", "Insufficient recovery"
    UNRESOLVED = "unresolved", "Unresolved"


class OBType(models.TextChoices):
    BULLISH = "bullish_ob", "Bullish order block"
    BEARISH = "bearish_ob", "Bearish order block"


class OBDefinition(models.TextChoices):
    """Order-block definitions must never be silently merged."""

    TEACHER_PATTERN = "teacher_pattern", "Teacher pattern-based definition"
    ICT_STYLE = "ict_style", "ICT-style definition"


class CyclePhase(models.TextChoices):
    MOTIVE = "original_motive", "Original motive wave"
    COUNTER = "counter_wave", "Counter wave"
    LAST_EFFORT = "last_effort", "Last-effort wave"
    FAILED_TEST = "failed_sr_test", "Failed support/resistance test"
    NEW_MOTIVE = "new_opposing_motive", "New opposing motive candidate"
    BULLISH_REVERSAL = "bullish_reversal", "Bullish reversal cycle"
    BEARISH_REVERSAL = "bearish_reversal", "Bearish reversal cycle"
    UNCLEAR = "unclear", "Unclear"


class SBRStage(models.TextChoices):
    """Stages of a support/resistance flip (SBR/RBS) or breakout-retest.

    A flip is only *reported* at the stage actually observed; nothing jumps to
    ``completed`` without the earlier stages having happened.
    """

    FORMATION = "formation", "Formation (validated level)"
    VALID_BREAK = "valid_break", "Valid break (completed close beyond)"
    RETEST = "retest", "Retest from the opposite side"
    REJECTION = "rejection", "Retest rejected (flip failed)"
    ACCEPTANCE = "acceptance", "Retest accepted (new role holding)"
    COMPLETED = "completed", "Completed flip"
    INVALIDATED = "invalidated", "Invalidated (price back through the zone)"


class StructureBreakType(models.TextChoices):
    """Named structure events; CHOCH/MSS are never merged with plain BOS."""

    BOS_BULLISH = "bullish_bos", "Bullish break of structure"
    BOS_BEARISH = "bearish_bos", "Bearish break of structure"
    CHOCH_BULLISH = "bullish_choch", "Bullish change of character"
    CHOCH_BEARISH = "bearish_choch", "Bearish change of character"
    MSS_BULLISH = "bullish_mss", "Bullish market structure shift"
    MSS_BEARISH = "bearish_mss", "Bearish market structure shift"


class PriceZone(models.TextChoices):
    """Premium/discount classification of a price inside a dealing range."""

    PREMIUM = "premium", "Premium (upper half of the range)"
    DISCOUNT = "discount", "Discount (lower half of the range)"
    EQUILIBRIUM = "equilibrium", "Equilibrium (range midpoint)"


class ConflictType(models.TextChoices):
    BULLISH_AFTER_BUYER_FAILURE = (
        "bullish_after_buyer_failure",
        "Bullish pattern after buyer failure",
    )
    BEARISH_AFTER_SELLER_FAILURE = (
        "bearish_after_seller_failure",
        "Bearish pattern after seller failure",
    )
    REVERSAL_AGAINST_BREAKOUT = "reversal_against_breakout", "Reversal against confirmed breakout"
    SBR_RBS_WITHOUT_BREAK = "sbr_rbs_without_break", "SBR/RBS without a valid level break"
    SWEEP_WITHOUT_RECOVERY = "sweep_without_recovery", "Liquidity sweep without recovery"
    PATTERN_IN_CONSOLIDATION = "pattern_in_consolidation", "Pattern inside unresolved consolidation"
    UNCONFIRMED_PIVOT = "unconfirmed_pivot", "Unconfirmed pivot treated as confirmed"
    SOURCE_INCOMPATIBLE = "source_incompatible", "Incompatible screenshot/MT5 observations"
    OPPOSING_EVIDENCE = "opposing_evidence", "Opposing directional evidence"


class Severity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"


#: Version of the market-input schema produced by :mod:`apps.price_action.schemas`.
PA_MARKET_INPUT_SCHEMA_VERSION = "1.0"

#: Version of the engine's overall result document.
PA_ENGINE_SCHEMA_VERSION = "1.0"

#: Version of every rule's definition. Bumped when a rule's logic changes.
PA_RULE_VERSION = "1.0"

#: Version of the knowledge catalogue.
PA_KNOWLEDGE_VERSION = "1.0"

#: Placeholder for values that could not be read.
UNKNOWN = "UNKNOWN"


__all__ = [
    "PA_ENGINE_SCHEMA_VERSION",
    "PA_KNOWLEDGE_VERSION",
    "PA_MARKET_INPUT_SCHEMA_VERSION",
    "PA_RULE_VERSION",
    "UNKNOWN",
    "CandleStrength",
    "ConflictType",
    "CyclePhase",
    "DataQuality",
    "Direction",
    "EvidenceStatus",
    "FVGState",
    "FVGType",
    "GapType",
    "MarketRegime",
    "MarketType",
    "NewsStatus",
    "OBDefinition",
    "OBType",
    "PatternDirection",
    "PriceZone",
    "RejectionKind",
    "SBRStage",
    "Severity",
    "StructureBreakType",
    "StructureState",
    "SweepOutcome",
    "SweepType",
    "SwingKind",
    "SwingLabel",
    "TradingSession",
    "TrendDirection",
    "VolatilityState",
    "VolumeSource",
    "ZoneKind",
    "ZoneState",
]
