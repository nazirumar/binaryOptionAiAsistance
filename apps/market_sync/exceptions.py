"""Domain exceptions for market synchronization."""

from __future__ import annotations


class MarketSyncError(Exception):
    """Base class for all market-synchronization errors."""


class MissingScreenshotAnalysisError(MarketSyncError):
    """The screenshot has no usable analysis to compare."""


class InstrumentMatchError(MarketSyncError):
    """The screenshot instrument could not be matched to an MT5 symbol."""


class UnsupportedInstrumentError(InstrumentMatchError):
    """The screenshot instrument is not a recognised canonical instrument."""


class AmbiguousInstrumentMappingError(InstrumentMatchError):
    """More than one plausible mapping exists; refusing to guess."""


class TimeframeMatchError(MarketSyncError):
    """The screenshot timeframe could not be determined or is unsupported."""


class MT5DataUnavailableError(MarketSyncError):
    """No stored MT5 candles are available for the resolved symbol/timeframe."""


__all__ = [
    "AmbiguousInstrumentMappingError",
    "InstrumentMatchError",
    "MT5DataUnavailableError",
    "MarketSyncError",
    "MissingScreenshotAnalysisError",
    "TimeframeMatchError",
    "UnsupportedInstrumentError",
]
