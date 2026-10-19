# apps/strategy_engine/constants.py
"""Constants and enums for the strategy evaluation engine (Phase 6).

No trading probabilities are defined here. Until Phase 7 calibration exists,
probability status is reported as UNAVAILABLE_UNCALIBRATED.
"""

from __future__ import annotations

from django.db import models


class EvaluationDirection(models.TextChoices):
    """Final decision direction."""

    UP = "up", "UP"
    DOWN = "down", "DOWN"
    NO_TRADE = "no_trade", "NO_TRADE"


class StrategyFamily(models.TextChoices):
    """Core strategy families as defined in Phase 6."""

    SUPPORT_RESISTANCE_REJECTION = "sr_rejection", "Support/Resistance Rejection"
    BREAKOUT_RETEST_SBR_RBS = "breakout_retest", "Breakout-Retest (SBR/RBS)"
    LIQUIDITY_SWEEP_REJECTION = "liquidity_sweep", "Liquidity Sweep & Rejection"
    #: Deterministic book pattern from Phase 13; only ever reaches the engine
    #: after explicit ``decision_use_approved`` (see book_strategies services).
    BOOK_PATTERN = "book_pattern", "Book Pattern (Trading Bible)"
    COMBINED = "combined", "Combined"
    UNKNOWN = "unknown", "Unknown"


class MarketContextState(models.TextChoices):
    """Market context classification."""

    BULLISH_TREND = "bullish_trend", "Bullish trend"
    BEARISH_TREND = "bearish_trend", "Bearish trend"
    RANGE = "range", "Range-bound"
    TRANSITION = "transition", "Transition"
    UNCERTAIN = "uncertain", "Uncertain"


class CandidateStatus(models.TextChoices):
    """Status of a strategy candidate."""

    VALID = "valid", "Valid"
    WEAK = "weak", "Weak"
    INVALID = "invalid", "Invalid"
    REJECTED = "rejected", "Rejected"


class InvalidationReasonCode(models.TextChoices):
    """Explicit reason codes for NO_TRADE decisions."""

    INCOMPATIBLE_SYNC = "incompatible_sync", "Screenshot/MT5 compatibility not verified"
    UNCERTAIN_INSTRUMENT = "uncertain_instrument", "Instrument or timeframe uncertain"
    UNFINISHED_CANDLE = "unfinished_candle", "Required signal candle is unfinished"
    STALE_DATA = "stale_data", "Screenshot or market data is stale"
    EXPIRED_ENTRY = "expired_entry", "Next-candle entry window has passed"
    AMBIGUOUS_STRUCTURE = "ambiguous_structure", "Market structure too ambiguous"
    MISSING_CONDITIONS = "missing_conditions", "Required strategy conditions missing"
    STRONG_CONTRADICTION = "strong_contradiction", "Strong contradictory evidence exists"
    SETUP_INVALIDATED = "setup_invalidated", "The setup is invalidated"
    NEWS_FILTER_CLOSED = "news_filter_closed", "News filter cannot be evaluated (fail-closed)"
    INSUFFICIENT_QUALITY = "insufficient_quality", "Data quality is insufficient"
    NO_CANDIDATES = "no_candidates", "No valid strategy candidates found"
    MULTIPLE_CONFLICTING = (
        "multiple_conflicting",
        "Multiple conflicting candidates with no clear winner",
    )


class ProbabilityStatus(models.TextChoices):
    """Probability calibration status."""

    UNAVAILABLE_UNCALIBRATED = "unavailable_uncalibrated", "Unavailable (uncalibrated)"
    CALIBRATED = "calibrated", "Calibrated"
    PENDING_CALIBRATION = "pending_calibration", "Pending calibration"


class TimingValidity(models.TextChoices):
    """Timing validity for next-candle prediction."""

    VALID = "valid", "Valid"
    EXPIRED = "expired", "Expired"
    FUTURE_INVALID = "future_invalid", "Future target invalid"
    UNCERTAIN = "uncertain", "Uncertain"
    MISSING_TIMESTAMPS = "missing_timestamps", "Missing timestamps"


# Schema/config versions
STRATEGY_INPUT_SCHEMA_VERSION = "1.0"
STRATEGY_OUTPUT_SCHEMA_VERSION = "1.0"
STRATEGY_CONFIG_VERSION = "1.0"
STRATEGY_RULE_VERSION = "1.0"


__all__ = [
    "STRATEGY_CONFIG_VERSION",
    "STRATEGY_INPUT_SCHEMA_VERSION",
    "STRATEGY_OUTPUT_SCHEMA_VERSION",
    "STRATEGY_RULE_VERSION",
    "CandidateStatus",
    "EvaluationDirection",
    "InvalidationReasonCode",
    "MarketContextState",
    "ProbabilityStatus",
    "StrategyFamily",
    "TimingValidity",
]
