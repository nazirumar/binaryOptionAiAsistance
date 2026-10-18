"""Thin, testable wrapper around the Windows-only ``MetaTrader5`` package.

The rest of the application depends only on the :class:`MT5Gateway` protocol and
the DTOs in :mod:`apps.market_data.services.dto`. The real implementation imports
``MetaTrader5`` lazily so the web application and the test suite run on machines
(and CI containers) without the terminal or the package installed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable

from apps.market_data.services.dto import (
    AccountInfo,
    Candle,
    SymbolInfo,
    TerminalInfo,
    Tick,
)
from apps.market_data.services.exceptions import MT5UnavailableError


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _field(row: Any, name: str) -> Any:
    """Read a field from a dict, numpy structured row, or object."""
    if isinstance(row, dict):
        return row.get(name)
    try:
        return row[name]  # numpy structured arrays and namedtuples
    except (KeyError, TypeError, IndexError):
        return getattr(row, name, None)


def _utc_from_seconds(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value), tz=UTC)


def _rate_to_candle(row: Any) -> Candle:
    return Candle(
        open_time=_utc_from_seconds(_field(row, "time")),
        open=_to_decimal(_field(row, "open")) or Decimal(0),
        high=_to_decimal(_field(row, "high")) or Decimal(0),
        low=_to_decimal(_field(row, "low")) or Decimal(0),
        close=_to_decimal(_field(row, "close")) or Decimal(0),
        tick_volume=_to_int(_field(row, "tick_volume")) or 0,
        spread=_to_int(_field(row, "spread")),
        real_volume=_to_int(_field(row, "real_volume")),
    )


def _tick_to_dto(row: Any) -> Tick:
    time_value = _field(row, "time_msc")
    if time_value is not None:
        time_value = int(time_value) / 1000
    else:
        time_value = _field(row, "time")
    return Tick(
        time=datetime.fromtimestamp(float(time_value), tz=UTC),
        bid=_to_decimal(_field(row, "bid")),
        ask=_to_decimal(_field(row, "ask")),
        last=_to_decimal(_field(row, "last")),
        volume=_to_int(_field(row, "volume")),
        flags=_to_int(_field(row, "flags")),
    )


@runtime_checkable
class MT5Gateway(Protocol):
    """The narrow MT5 surface the services depend on."""

    def initialize(
        self,
        *,
        path: str = "",
        login: int = 0,
        password: str = "",
        server: str = "",
        timeout_ms: int = 60000,
        portable: bool = False,
    ) -> bool: ...

    def shutdown(self) -> None: ...

    def last_error(self) -> tuple[int | None, str]: ...

    def terminal_info(self) -> TerminalInfo | None: ...

    def account_info(self) -> AccountInfo | None: ...

    def symbols_get(self) -> list[str]: ...

    def symbol_info(self, symbol: str) -> SymbolInfo | None: ...

    def symbol_select(self, symbol: str, enable: bool) -> bool: ...

    def symbol_info_tick(self, symbol: str) -> Tick | None: ...

    def copy_rates_from_pos(
        self, symbol: str, timeframe: str, count: int, start: int = 0
    ) -> list[Candle]: ...

    def copy_rates_range(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Candle]: ...

    def copy_ticks_from(self, symbol: str, start: datetime, count: int) -> list[Tick]: ...

    def copy_ticks_range(self, symbol: str, start: datetime, end: datetime) -> list[Tick]: ...


class MetaTrader5Client:
    """Real :class:`MT5Gateway` backed by the ``MetaTrader5`` package."""

    def __init__(self, module: Any | None = None) -> None:
        self._module = module

    # -- module access ------------------------------------------------------
    @property
    def mt5(self) -> Any:
        if self._module is None:
            try:
                import MetaTrader5 as mt5
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise MT5UnavailableError(
                    "The MetaTrader5 package is not installed. It is Windows-only; "
                    "run the worker on a Windows host with the package installed."
                ) from exc
            self._module = mt5
        return self._module

    # -- lifecycle ----------------------------------------------------------
    def initialize(
        self,
        *,
        path: str = "",
        login: int = 0,
        password: str = "",
        server: str = "",
        timeout_ms: int = 60000,
        portable: bool = False,
    ) -> bool:
        kwargs: dict[str, Any] = {"timeout": timeout_ms, "portable": portable}
        if path:
            kwargs["path"] = path
        if login:
            kwargs["login"] = login
        if password:
            kwargs["password"] = password
        if server:
            kwargs["server"] = server
        return bool(self.mt5.initialize(**kwargs))

    def shutdown(self) -> None:
        self.mt5.shutdown()

    def last_error(self) -> tuple[int | None, str]:
        info = self.mt5.last_error()
        if isinstance(info, (tuple, list)) and len(info) >= 2:
            return _to_int(info[0]), str(info[1])
        return None, str(info)

    # -- info ---------------------------------------------------------------
    def terminal_info(self) -> TerminalInfo | None:
        raw = self.mt5.terminal_info()
        if raw is None:
            return None
        return TerminalInfo(
            name=str(_field(raw, "name") or ""),
            company=str(_field(raw, "company") or ""),
            path=str(_field(raw, "path") or ""),
            connected=bool(_field(raw, "connected")),
            build=_to_int(_field(raw, "build")),
        )

    def account_info(self) -> AccountInfo | None:
        raw = self.mt5.account_info()
        if raw is None:
            return None
        return AccountInfo(
            login=_to_int(_field(raw, "login")),
            server=str(_field(raw, "server") or ""),
            company=str(_field(raw, "company") or ""),
            currency=str(_field(raw, "currency") or ""),
            trade_mode=_to_int(_field(raw, "trade_mode")),
            leverage=_to_int(_field(raw, "leverage")),
        )

    def symbols_get(self) -> list[str]:
        symbols = self.mt5.symbols_get()
        if not symbols:
            return []
        return [str(_field(s, "name")) for s in symbols]

    def symbol_info(self, symbol: str) -> SymbolInfo | None:
        raw = self.mt5.symbol_info(symbol)
        if raw is None:
            return None
        return SymbolInfo(
            name=str(_field(raw, "name") or symbol),
            description=str(_field(raw, "description") or ""),
            digits=_to_int(_field(raw, "digits")),
            point=_to_decimal(_field(raw, "point")),
            tick_size=_to_decimal(_field(raw, "trade_tick_size")),
            contract_size=_to_decimal(_field(raw, "trade_contract_size")),
            currency_base=str(_field(raw, "currency_base") or ""),
            currency_profit=str(_field(raw, "currency_profit") or ""),
            currency_margin=str(_field(raw, "currency_margin") or ""),
            trade_mode=_to_int(_field(raw, "trade_mode")),
            spread=_to_int(_field(raw, "spread")),
            visible=bool(_field(raw, "visible")),
        )

    def symbol_select(self, symbol: str, enable: bool) -> bool:
        return bool(self.mt5.symbol_select(symbol, enable))

    def symbol_info_tick(self, symbol: str) -> Tick | None:
        raw = self.mt5.symbol_info_tick(symbol)
        if raw is None:
            return None
        return _tick_to_dto(raw)

    # -- rates / ticks ------------------------------------------------------
    def copy_rates_from_pos(
        self,
        symbol: str,
        timeframe: str,
        count: int,
        start: int = 0,
    ) -> list[Candle]:
        from apps.market_data.services.timeframe_mapper import to_mt5

        rates = self.mt5.copy_rates_from_pos(symbol, to_mt5(timeframe), start, count)
        if rates is None:
            return []
        return [_rate_to_candle(row) for row in rates]

    def copy_rates_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        from apps.market_data.services.timeframe_mapper import to_mt5

        rates = self.mt5.copy_rates_range(symbol, to_mt5(timeframe), start, end)
        if rates is None:
            return []
        return [_rate_to_candle(row) for row in rates]

    def copy_ticks_from(self, symbol: str, start: datetime, count: int) -> list[Tick]:
        ticks = self.mt5.copy_ticks_from(symbol, start, count, self.mt5.COPY_TICKS_ALL)
        if ticks is None:
            return []
        return [_tick_to_dto(row) for row in ticks]

    def copy_ticks_range(self, symbol: str, start: datetime, end: datetime) -> list[Tick]:
        ticks = self.mt5.copy_ticks_range(symbol, start, end, self.mt5.COPY_TICKS_ALL)
        if ticks is None:
            return []
        return [_tick_to_dto(row) for row in ticks]
