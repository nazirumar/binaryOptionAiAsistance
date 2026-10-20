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


def _utc_from_seconds(value: Any, offset_seconds: int = 0) -> datetime:
    """Convert an MT5 time field to a true-UTC datetime.

    MT5 reports candle/tick times as a Unix timestamp expressed in the
    **broker server's wall-clock**, not UTC. A terminal on a UTC+3 server
    labels the 15:00 UTC candle as 18:00. ``offset_seconds`` is that server
    offset (seconds to *subtract*); it is detected from the live terminal at
    connect time. It defaults to 0 so nothing is shifted when the offset is
    unknown - a wrong offset would silently move every candle.

    Fractional seconds are preserved (tick times carry milliseconds).
    """
    return datetime.fromtimestamp(float(value) - offset_seconds, tz=UTC)


def _rate_to_candle(row: Any, offset_seconds: int = 0) -> Candle:
    return Candle(
        open_time=_utc_from_seconds(_field(row, "time"), offset_seconds),
        open=_to_decimal(_field(row, "open")) or Decimal(0),
        high=_to_decimal(_field(row, "high")) or Decimal(0),
        low=_to_decimal(_field(row, "low")) or Decimal(0),
        close=_to_decimal(_field(row, "close")) or Decimal(0),
        tick_volume=_to_int(_field(row, "tick_volume")) or 0,
        spread=_to_int(_field(row, "spread")),
        real_volume=_to_int(_field(row, "real_volume")),
    )


def _tick_to_dto(row: Any, offset_seconds: int = 0) -> Tick:
    time_value = _field(row, "time_msc")
    if time_value is not None:
        time_value = int(time_value) / 1000
    else:
        time_value = _field(row, "time")
    return Tick(
        time=_utc_from_seconds(float(time_value), offset_seconds),
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

    def __init__(self, module: Any | None = None, server_offset_seconds: int | None = None) -> None:
        self._module = module
        # Seconds to subtract from MT5's server-clock timestamps to reach true
        # UTC. ``None`` means "detect from the live terminal"; an explicit value
        # (including 0) is respected. See ``detect_server_offset``.
        self._server_offset_seconds = server_offset_seconds

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

    # -- server clock offset ------------------------------------------------
    def _offset(self) -> int:
        """Server-clock offset to subtract, detected once and cached.

        MT5 timestamps are server wall-clock, not UTC. The offset is derived
        from the terminal itself: a fresh tick's ``time`` (server epoch) minus
        the true UTC epoch. It is rounded to the nearest minute to absorb
        network/latency jitter, and falls back to 0 (no shift) when it cannot
        be measured, so an unknown offset never silently moves candles.
        """
        if self._server_offset_seconds is None:
            self._server_offset_seconds = self.detect_server_offset()
        return self._server_offset_seconds

    def detect_server_offset(self) -> int:
        """Measure the broker server's UTC offset in seconds (0 if unknown).

        Prefers the configured ``MT5_SERVER_TZ_OFFSET_MINUTES`` when set, so an
        operator can pin it explicitly. Otherwise samples a live tick.
        """
        from django.conf import settings

        configured = getattr(settings, "MT5_SERVER_TZ_OFFSET_MINUTES", None)
        if configured is not None:
            return int(configured) * 60

        from datetime import UTC as _UTC
        from datetime import datetime as _dt

        try:
            # Any symbol with a fresh tick reveals the server clock. EURUSD is
            # the conventional probe; a missing tick simply yields 0.
            raw = self.mt5.symbol_info_tick("EURUSD")
            server_epoch = _field(raw, "time") if raw is not None else None
            if server_epoch:
                delta = int(server_epoch) - int(_dt.now(tz=_UTC).timestamp())
                # Round to the nearest minute (servers are offset by whole
                # hours/half-hours; this removes sampling latency).
                return int(round(delta / 60.0) * 60)
        except Exception:  # pragma: no cover - terminal dependent
            return 0
        return 0

    def symbol_info_tick(self, symbol: str) -> Tick | None:
        raw = self.mt5.symbol_info_tick(symbol)
        if raw is None:
            return None
        return _tick_to_dto(raw, self._offset())

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
        offset = self._offset()
        return [_rate_to_candle(row, offset) for row in rates]

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
        offset = self._offset()
        return [_rate_to_candle(row, offset) for row in rates]

    def copy_ticks_from(self, symbol: str, start: datetime, count: int) -> list[Tick]:
        ticks = self.mt5.copy_ticks_from(symbol, start, count, self.mt5.COPY_TICKS_ALL)
        if ticks is None:
            return []
        offset = self._offset()
        return [_tick_to_dto(row, offset) for row in ticks]

    def copy_ticks_range(self, symbol: str, start: datetime, end: datetime) -> list[Tick]:
        ticks = self.mt5.copy_ticks_range(symbol, start, end, self.mt5.COPY_TICKS_ALL)
        if ticks is None:
            return []
        offset = self._offset()
        return [_tick_to_dto(row, offset) for row in ticks]
