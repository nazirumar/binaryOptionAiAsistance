"""Market data service layer.

The services are intentionally decoupled from Django ORM details (as far as is
practical) and from the Windows-only ``MetaTrader5`` package so they can be
unit-tested with fakes. See :mod:`apps.market_data.services.mt5_client` for the
gateway protocol.
"""

from __future__ import annotations

from apps.market_data.services.exceptions import (
    MarketDataError,
    MT5ConnectionError,
    MT5DataError,
    MT5UnavailableError,
    OTCFeedMismatchError,
    SymbolMappingError,
    UnsupportedTimeframeError,
    WorkerAuthError,
)

__all__ = [
    "MT5ConnectionError",
    "MT5DataError",
    "MT5UnavailableError",
    "MarketDataError",
    "OTCFeedMismatchError",
    "SymbolMappingError",
    "UnsupportedTimeframeError",
    "WorkerAuthError",
]
