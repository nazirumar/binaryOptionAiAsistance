"""Enumerations and constant registries for the chart-vision domain.

These values are shared by the ORM models, the structured-output schema and the
API serializers so that a single definition governs validation everywhere.
"""

from __future__ import annotations

from django.db import models


class UploadStatus(models.TextChoices):
    """Lifecycle of an uploaded screenshot *file* (before/independent of analysis)."""

    PENDING = "pending", "Pending validation"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"


class AnalysisStatus(models.TextChoices):
    """Lifecycle/outcome of a screenshot analysis run."""

    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    PARTIAL = "partial", "Partial (missing information)"
    INSUFFICIENT = "insufficient_evidence", "Insufficient evidence"
    FAILED = "failed", "Failed"


class ImageFormat(models.TextChoices):
    PNG = "png", "PNG"
    JPEG = "jpeg", "JPEG"
    WEBP = "webp", "WebP"


class ProviderName(models.TextChoices):
    MOCK = "mock", "Mock (development)"
    OPENAI = "openai", "OpenAI-compatible"
    CUSTOM = "custom", "Custom HTTP endpoint"


class EventKind(models.TextChoices):
    UPLOAD = "upload", "Upload"
    VALIDATION = "validation", "Validation"
    PROVIDER_REQUEST = "provider_request", "Provider request"
    PROVIDER_RESPONSE = "provider_response", "Provider response"
    SCHEMA = "schema", "Schema validation"
    PERSIST = "persist", "Persistence"
    QUEUE = "queue", "Job queue"


class Severity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"
    CRITICAL = "critical", "Critical"


class ObservationKind(models.TextChoices):
    SCREENSHOT_QUALITY = "screenshot_quality", "Screenshot quality"
    CHART_METADATA = "chart_metadata", "Chart metadata"
    MARKET_STRUCTURE = "market_structure", "Market structure"
    SUPPORT_RESISTANCE = "support_resistance", "Support / resistance"
    CANDLE_SEQUENCE = "candle_sequence", "Candle sequence"
    MARKET_CYCLE = "market_cycle", "Market cycle"
    LIQUIDITY = "liquidity", "Liquidity"
    VOLUME = "volume", "Volume"


class PatternCategory(models.TextChoices):
    CANDLESTICK = "candlestick", "Candlestick"
    SEQUENCE = "sequence", "Sequence"
    ADVANCED = "advanced", "Advanced course concept"
    STRUCTURE = "structure", "Market structure"


class PatternDirection(models.TextChoices):
    BULLISH = "bullish", "Bullish"
    BEARISH = "bearish", "Bearish"
    NEUTRAL = "neutral", "Neutral"
    UNKNOWN = "unknown", "Unknown"


class ZoneType(models.TextChoices):
    SUPPORT = "support", "Support"
    RESISTANCE = "resistance", "Resistance"
    FLIP = "flip", "Flip zone"
    BROKEN = "broken", "Broken level"


class Trend(models.TextChoices):
    UPTREND = "uptrend", "Uptrend"
    DOWNTREND = "downtrend", "Downtrend"
    RANGING = "ranging", "Ranging"
    UNCLEAR = "unclear", "Unclear"


class CandleClassification(models.TextChoices):
    BULLISH = "bullish", "Bullish"
    BEARISH = "bearish", "Bearish"
    DOJI = "doji", "Doji"
    UNKNOWN = "unknown", "Unknown"


class SizeBand(models.TextChoices):
    NONE = "none", "None"
    SMALL = "small", "Small"
    MEDIUM = "medium", "Medium"
    LARGE = "large", "Large"
    UNKNOWN = "unknown", "Unknown"


class ScreenshotQuality(models.TextChoices):
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"
    UNUSABLE = "unusable", "Unusable"
    UNKNOWN = "unknown", "Unknown"


class ConfidenceBand(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    UNKNOWN = "unknown", "Unknown"


class OTCStatus(models.TextChoices):
    OTC = "otc", "OTC"
    REGULAR = "regular", "Regular market"
    UNKNOWN = "unknown", "Unknown"


class ChartOrientation(models.TextChoices):
    STANDARD = "standard", "Standard (price up)"
    INVERTED = "inverted", "Inverted"
    UNKNOWN = "unknown", "Unknown"


#: Placeholder returned wherever a value cannot be read from the screenshot.
UNKNOWN = "UNKNOWN"

#: The structured-output schema version produced/consumed in this phase.
SCHEMA_VERSION = "1.0"

#: Prompt template version (see ``prompts/chart_analysis_v1.md``).
PROMPT_VERSION = "v1"
