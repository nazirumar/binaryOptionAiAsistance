"""Enumerations and constant registries for the market-synchronization domain.

``SyncStatus`` is the *outcome* of a comparison (Step 12 of the Phase 4 spec).
``SessionStatus`` is the *lifecycle* of the persisted session record. Keeping the
two separate prevents "running" being confused with a verification result.
"""

from __future__ import annotations

from django.db import models


class SyncStatus(models.TextChoices):
    """Outcome of comparing a screenshot with the MT5 reference feed.

    Only :attr:`VERIFIED_ALIGNMENT` may be treated as a successful dual-source
    verification. Every other value is either explicitly non-verified or a
    failure to verify.
    """

    VERIFIED_ALIGNMENT = "verified_alignment", "Verified alignment"
    PARTIAL_ALIGNMENT = "partial_alignment", "Partial alignment"
    DATA_MISMATCH = "data_mismatch", "Data mismatch"
    INCOMPATIBLE_FEED = "incompatible_feed", "Incompatible feed"
    STALE_DATA = "stale_data", "Stale data"
    INSUFFICIENT_INFORMATION = "insufficient_information", "Insufficient information"
    MT5_UNAVAILABLE = "mt5_unavailable", "MT5 unavailable"


class SessionStatus(models.TextChoices):
    """Lifecycle of a synchronization session record."""

    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class CandleMatch(models.TextChoices):
    """Per-candle alignment outcome."""

    MATCHED = "matched", "Matched"
    MISMATCHED = "mismatched", "Mismatched"
    UNALIGNED = "unaligned", "No matching MT5 interval"
    INSUFFICIENT = "insufficient", "Insufficient screenshot detail"


class StructureAgreement(models.TextChoices):
    """Overall market-structure agreement."""

    AGREE = "agree", "Agree"
    PARTIAL = "partial", "Partial"
    DISAGREE = "disagree", "Disagree"
    INSUFFICIENT = "insufficient_evidence", "Insufficient evidence"
    NOT_COMPARABLE = "not_comparable", "Not comparable"


class FeedCompatibilityStatus(models.TextChoices):
    COMPATIBLE = "compatible", "Compatible"
    INCOMPATIBLE_FEED = "incompatible_feed", "Incompatible feed"
    UNKNOWN = "unknown", "Unknown"


class PriceComparisonMethod(models.TextChoices):
    """How (if at all) price levels could be compared."""

    RELATIVE_STRUCTURE = "relative_structure", "Relative structure only"
    NUMERIC_AXIS = "numeric_axis", "Numeric axis labels available"
    NOT_AVAILABLE = "not_available", "Not available"


class FreshnessStatus(models.TextChoices):
    FRESH = "fresh", "Fresh"
    STALE_SCREENSHOT = "stale_screenshot", "Stale screenshot"
    STALE_MT5 = "stale_mt5", "Stale MT5 data"
    UNKNOWN = "unknown", "Unknown"


class MappingSource(models.TextChoices):
    """How the MT5 broker symbol was resolved from the screenshot instrument."""

    BROKER_SYMBOL_EXACT = "broker_symbol_exact", "Explicit broker-symbol mapping"
    CANONICAL = "canonical", "Canonical instrument mapping"
    NONE = "none", "Not resolved"


class AlignmentSource(models.TextChoices):
    """Where the screenshot anchor timestamp came from."""

    VISIBLE_TIMESTAMP = "visible_timestamp", "Visible chart timestamp"
    USER_PROVIDED = "user_provided", "User-provided capture time"
    CAPTURE_METADATA = "capture_metadata", "Screenshot capture metadata"
    MT5_LAST_COMPLETED = "mt5_last_completed", "Assumed from the latest MT5 candle"
    NONE = "none", "Unavailable"


class ComparisonMethod(models.TextChoices):
    """The comparison approach recorded for audit purposes."""

    QUALITATIVE_RELATIVE = (
        "qualitative_relative",
        "Qualitative/relative (no fabricated screenshot prices)",
    )


class Severity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"
    CRITICAL = "critical", "Critical"


class AuditKind(models.TextChoices):
    STARTED = "started", "Verification started"
    INSTRUMENT = "instrument", "Instrument matching"
    TIMEFRAME = "timeframe", "Timeframe comparison"
    ALIGNMENT = "alignment", "Timestamp alignment"
    COMPARISON = "comparison", "Candle/structure comparison"
    FRESHNESS = "freshness", "Freshness check"
    STATUS = "status", "Status decision"
    COMPLETED = "completed", "Verification completed"
    ERROR = "error", "Error"


#: Version of the comparison configuration/thresholds recorded on every session.
SYNC_CONFIG_VERSION = "1.0"

#: Placeholder for values that could not be read.
UNKNOWN = "UNKNOWN"


__all__ = [
    "SYNC_CONFIG_VERSION",
    "UNKNOWN",
    "AlignmentSource",
    "AuditKind",
    "CandleMatch",
    "ComparisonMethod",
    "FeedCompatibilityStatus",
    "FreshnessStatus",
    "MappingSource",
    "PriceComparisonMethod",
    "SessionStatus",
    "Severity",
    "StructureAgreement",
    "SyncStatus",
]
