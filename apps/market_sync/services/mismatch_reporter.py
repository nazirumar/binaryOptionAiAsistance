"""Mismatch reporting and synchronization-status decision (Step 12).

Central place for the *documented criteria* that map the various comparison
results onto a single :class:`~apps.market_sync.constants.SyncStatus`. The
priority order below is deliberate: an incompatible feed is reported ahead of a
mere data gap, and only a fully-agreeing, fresh, compatible run is ever labelled
``VERIFIED_ALIGNMENT``.
"""

from __future__ import annotations

from apps.market_sync.constants import (
    FeedCompatibilityStatus,
    FreshnessStatus,
    StructureAgreement,
    SyncStatus,
)
from apps.market_sync.services.config import SyncConfig
from apps.market_sync.services.dto import (
    CandleComparison,
    FeedAssessment,
    FreshnessAssessment,
    StructureComparison,
    SyncIssue,
)

# -- issue codes --------------------------------------------------------
MISSING_INSTRUMENT = "missing_instrument"
UNSUPPORTED_INSTRUMENT = "unsupported_instrument"
AMBIGUOUS_MAPPING = "ambiguous_mapping"
MAPPING_UNVERIFIED = "mapping_unverified"
MISSING_TIMEFRAME = "missing_timeframe"
TIMEFRAME_MISMATCH = "timeframe_mismatch"
OTC_INCOMPATIBLE = "otc_incompatible"
FEED_UNKNOWN = "feed_unknown"
MT5_NO_DATA = "mt5_no_data"
MT5_PARTIAL_HISTORY = "mt5_partial_history"
ALIGNMENT_NO_TIMESTAMP = "alignment_no_timestamp"
ALIGNMENT_UNCERTAIN = "alignment_uncertain"
INSUFFICIENT_OVERLAP = "insufficient_overlap"
CANDLE_DIRECTION_MISMATCH = "candle_direction_mismatch"
CANDLE_STRUCTURE_MISMATCH = "candle_structure_mismatch"
CANDLE_UNALIGNED = "candle_unaligned"
STALE_SCREENSHOT = "stale_screenshot"
STALE_MT5 = "stale_mt5"
ENTRY_WINDOW_EXPIRED = "entry_window_expired"
PRICE_OFFSET = "price_offset_reported"
SCREENSHOT_UNUSABLE = "screenshot_unusable"
ANALYSIS_INCOMPLETE = "analysis_incomplete"
COMPARISON_LIMITED = "comparison_limited"


def issue(
    code: str,
    severity: str,
    message: str,
    *,
    detail: dict | None = None,
    candle_index: int | None = None,
) -> SyncIssue:
    return SyncIssue(
        code=code,
        severity=severity,
        message=message,
        detail=detail or {},
        candle_index=candle_index,
    )


def decide_status(
    *,
    feed: FeedAssessment,
    mt5_available: bool,
    insufficient_information: bool,
    alignment_uncertain: bool,
    freshness: FreshnessAssessment,
    candle: CandleComparison,
    structure: StructureComparison,
    config: SyncConfig,
) -> str:
    """Return the single synchronization status for a run.

    Criteria (evaluated in order):

    1. ``INCOMPATIBLE_FEED`` — the feeds are not interchangeable (e.g. OTC).
    2. ``INSUFFICIENT_INFORMATION`` — a required input (symbol/timeframe/anchor)
       is missing, or too few completed candles overlap.
    3. ``MT5_UNAVAILABLE`` — no MT5 reference series exists at all.
    4. ``STALE_DATA`` — the screenshot or MT5 data is outside its freshness
       window.
    5. ``VERIFIED_ALIGNMENT`` — sufficient overlap, strong direction agreement,
       agreeing structure, compatible + fresh feed, a validated instrument
       mapping and a trustworthy anchor.
    6. ``PARTIAL_ALIGNMENT`` — some agreement, but not enough for full
       verification.
    7. ``DATA_MISMATCH`` — sufficient overlap but the sources disagree.
    """
    if feed.compatibility == FeedCompatibilityStatus.INCOMPATIBLE_FEED:
        return SyncStatus.INCOMPATIBLE_FEED

    if insufficient_information:
        return SyncStatus.INSUFFICIENT_INFORMATION

    if not mt5_available:
        return SyncStatus.MT5_UNAVAILABLE

    if freshness.status in (FreshnessStatus.STALE_SCREENSHOT, FreshnessStatus.STALE_MT5):
        return SyncStatus.STALE_DATA

    if candle.aligned_count < config.min_overlap_candles:
        return SyncStatus.INSUFFICIENT_INFORMATION

    if candle.direction_agreement is None:
        return SyncStatus.INSUFFICIENT_INFORMATION

    verified = (
        candle.direction_agreement >= config.direction_match_min
        and structure.agreement == StructureAgreement.AGREE
        and feed.compatibility == FeedCompatibilityStatus.COMPATIBLE
        and feed.mapping_verified
        and freshness.status == FreshnessStatus.FRESH
        and not alignment_uncertain
    )
    if verified:
        return SyncStatus.VERIFIED_ALIGNMENT

    partial = candle.direction_agreement >= config.direction_partial_min or structure.agreement in (
        StructureAgreement.AGREE,
        StructureAgreement.PARTIAL,
    )
    if partial:
        return SyncStatus.PARTIAL_ALIGNMENT

    return SyncStatus.DATA_MISMATCH


def status_message(status: str) -> str:
    """A plain-language explanation suitable for the dashboard."""
    return {
        SyncStatus.VERIFIED_ALIGNMENT: (
            "Verified alignment: the screenshot and MT5 agree strongly. This is the only "
            "status that counts as successful dual-source verification."
        ),
        SyncStatus.PARTIAL_ALIGNMENT: (
            "Partial alignment: the sources broadly agree, but this is NOT a full verification."
        ),
        SyncStatus.DATA_MISMATCH: (
            "Data mismatch: enough candles overlap, but the sources disagree."
        ),
        SyncStatus.INCOMPATIBLE_FEED: (
            "Incompatible feed: the screenshot cannot be verified against this MT5 feed "
            "(for example an OTC instrument with no verified reference)."
        ),
        SyncStatus.STALE_DATA: (
            "Stale data: the screenshot or the MT5 reference is outside its freshness window."
        ),
        SyncStatus.INSUFFICIENT_INFORMATION: (
            "Insufficient information: a required input is missing or too few candles overlap."
        ),
        SyncStatus.MT5_UNAVAILABLE: (
            "MT5 unavailable: no stored MT5 candles exist for the resolved symbol/timeframe."
        ),
    }.get(status, "Synchronization status is unknown.")


__all__ = ["decide_status", "issue", "status_message"]
