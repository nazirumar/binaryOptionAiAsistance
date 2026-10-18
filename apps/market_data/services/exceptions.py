"""Domain exceptions for the market data application."""

from __future__ import annotations


class MarketDataError(Exception):
    """Base class for all market-data errors."""


class MT5UnavailableError(MarketDataError):
    """The MetaTrader5 Python package or a terminal is not available."""


class MT5ConnectionError(MarketDataError):
    """The terminal could not be initialized or the connection was lost."""


class MT5DataError(MarketDataError):
    """The terminal returned no data or unusable data."""


class UnsupportedTimeframeError(MarketDataError):
    """A timeframe outside the supported set was requested."""


class SymbolMappingError(MarketDataError):
    """A canonical instrument has no valid MT5 symbol mapping."""


class OTCFeedMismatchError(MarketDataError):
    """A regular broker feed was requested as a substitute for an OTC instrument."""


class WorkerAuthError(MarketDataError):
    """A worker request failed authentication."""
