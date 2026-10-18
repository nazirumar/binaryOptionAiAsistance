"""Immutable data-transfer objects exchanged between sync services.

The comparator services never touch the database directly; they consume and
produce these plain dataclasses, which keeps them deterministic and trivial to
unit-test with hand-built fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class InstrumentMatch:
    """Result of matching a screenshot instrument to an MT5 symbol."""

    screenshot_instrument: str
    supported: bool
    ambiguous: bool
    canonical_instrument: str = ""
    broker_symbol: str = ""
    broker: str = ""
    market_type: str = ""
    mapping_source: str = "none"
    mapping_status: str = ""
    mapping_verified: bool = False
    screenshot_is_otc: bool | None = None
    reference_is_otc: bool | None = None
    reference_id: int | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TimeframeMatch:
    """Result of interpreting the screenshot timeframe vs the MT5 timeframe."""

    screenshot_timeframe: str | None
    screenshot_raw: str
    mt5_timeframe: str | None
    supported: bool
    mismatch: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    """Timestamp alignment between the screenshot and the MT5 candle grid."""

    anchor: datetime | None
    source: str
    confidence: float | None
    uncertain: bool
    #: screenshot candle index -> aligned MT5 candle open time (UTC).
    mt5_open_times: dict[int, datetime] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CandleAlignmentRecord:
    """One screenshot candle aligned (or not) to an MT5 interval."""

    screenshot_index: int
    screenshot_classification: str
    screenshot_body_size: str
    screenshot_upper_wick: str
    screenshot_lower_wick: str
    screenshot_position: str
    mt5_open_time: datetime | None = None
    mt5_candle_id: int | None = None
    mt5_direction: str | None = None
    mt5_body_ratio: float | None = None
    mt5_upper_wick_ratio: float | None = None
    mt5_lower_wick_ratio: float | None = None
    match_result: str = "insufficient"
    direction_match: bool | None = None
    body_match: bool | None = None
    wick_match: bool | None = None
    local_extreme_match: bool | None = None
    confidence: float | None = None
    limitations: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CandleComparison:
    """Aggregate outcome of the per-candle comparison."""

    alignments: list[CandleAlignmentRecord]
    aligned_count: int
    matched_count: int
    mismatched_count: int
    insufficient_count: int
    unaligned_count: int
    direction_agreement: float | None
    body_agreement: float | None
    wick_agreement: float | None
    metrics: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StructureComparison:
    """Market-structure agreement between screenshot and MT5."""

    agreement: str
    screenshot_trend: str
    mt5_trend: str
    comparable_items: int
    agreeing_items: int
    metrics: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FeedAssessment:
    """Feed-compatibility assessment (including OTC protection)."""

    compatibility: str
    screenshot_is_otc: bool | None
    reference_is_otc: bool | None
    reasons: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    #: Whether the canonical<->broker mapping is explicitly validated.
    mapping_verified: bool = False


@dataclass(frozen=True, slots=True)
class FreshnessAssessment:
    """Freshness of the screenshot and of the MT5 reference data."""

    status: str
    screenshot_age_seconds: float | None
    mt5_age_seconds: float | None
    entry_window_expired: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PriceLevelComparison:
    """Outcome of comparing price levels (numeric axis when available)."""

    method: str
    matched: bool | None
    offset: float | None
    metrics: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SyncIssue:
    """A single mismatch / limitation worth surfacing to the user."""

    code: str
    severity: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)
    candle_index: int | None = None


__all__ = [
    "AlignmentResult",
    "CandleAlignmentRecord",
    "CandleComparison",
    "FeedAssessment",
    "FreshnessAssessment",
    "InstrumentMatch",
    "PriceLevelComparison",
    "StructureComparison",
    "SyncIssue",
    "TimeframeMatch",
]
