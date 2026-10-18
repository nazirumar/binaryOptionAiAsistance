"""Data-transfer objects decoupled from the MetaTrader5 package.

Services depend on these immutable DTOs rather than on ``numpy`` structures or
the ``MetaTrader5`` module, which keeps them easy to test with fakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class Candle:
    """A single OHLC candle. ``open_time`` is timezone-aware UTC."""

    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_volume: int = 0
    spread: int | None = None
    real_volume: int | None = None


@dataclass(slots=True, frozen=True)
class Tick:
    """A single market tick. ``time`` is timezone-aware UTC."""

    time: datetime
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    volume: int | None = None
    flags: int | None = None


@dataclass(slots=True, frozen=True)
class SymbolInfo:
    """Normalised subset of MT5 symbol metadata."""

    name: str
    description: str = ""
    digits: int | None = None
    point: Decimal | None = None
    tick_size: Decimal | None = None
    contract_size: Decimal | None = None
    currency_base: str = ""
    currency_profit: str = ""
    currency_margin: str = ""
    trade_mode: int | None = None
    spread: int | None = None
    visible: bool | None = None


@dataclass(slots=True, frozen=True)
class AccountInfo:
    """Non-secret account metadata (never include the password)."""

    login: int | None = None
    server: str = ""
    company: str = ""
    currency: str = ""
    trade_mode: int | None = None
    leverage: int | None = None


@dataclass(slots=True, frozen=True)
class TerminalInfo:
    """Non-secret terminal metadata."""

    name: str = ""
    company: str = ""
    path: str = ""
    connected: bool = False
    build: int | None = None
