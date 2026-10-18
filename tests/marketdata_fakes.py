"""Fakes and helpers for market-data tests.

The real ``MetaTrader5`` package is Windows-only; every test uses
:class:`FakeMT5Gateway` (or a scripted variant) so the suite stays hermetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from apps.market_data.services.dto import AccountInfo, Candle, SymbolInfo, TerminalInfo, Tick

BASE_TIME = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def make_candle(
    open_time: datetime,
    *,
    o: str = "1.1000",
    h: str = "1.1050",
    low: str = "1.0950",
    c: str = "1.1020",
    tick_volume: int = 100,
    spread: int = 10,
    real_volume: int | None = None,
) -> Candle:
    return Candle(
        open_time=open_time,
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
        tick_volume=tick_volume,
        spread=spread,
        real_volume=real_volume,
    )


def make_tick(
    time: datetime,
    *,
    bid: str | None = "1.1000",
    ask: str | None = "1.1002",
    last: str | None = "1.1001",
    volume: int = 5,
) -> Tick:
    def _decimal(value: str | None) -> Decimal | None:
        return Decimal(value) if value is not None else None

    return Tick(
        time=time,
        bid=_decimal(bid),
        ask=_decimal(ask),
        last=_decimal(last),
        volume=volume,
        flags=2,
    )


def candle_series(
    count: int,
    timeframe: str = "M1",
    *,
    start: datetime = BASE_TIME,
    step: timedelta | None = None,
) -> list[Candle]:
    from apps.market_data.services.timeframe_mapper import duration

    step = step or duration(timeframe)
    series = []
    for index in range(count):
        close = Decimal("1.1000") + Decimal(index) / Decimal(10000)
        series.append(
            make_candle(
                start + index * step,
                o=str(close),
                h=str(close + Decimal("0.0005")),
                low=str(close - Decimal("0.0005")),
                c=str(close + Decimal("0.0002")),
            )
        )
    return series


class FakeMT5Gateway:
    """In-memory :class:`~apps.market_data.services.mt5_client.MT5Gateway`."""

    def __init__(
        self,
        *,
        connect: bool | list[bool] = True,
        rates: dict[tuple[str, str], list[Candle]] | None = None,
        ticks: dict[str, list[Tick]] | None = None,
        symbols: list[str] | None = None,
        symbol_infos: dict[str, SymbolInfo] | None = None,
        terminal: TerminalInfo | None = None,
        account: AccountInfo | None = None,
        error: tuple[int | None, str] = (0, "no error"),
    ) -> None:
        self._connect_sequence = connect if isinstance(connect, list) else None
        self._single_connect = connect if isinstance(connect, bool) else True
        self.rates = rates or {}
        self.ticks = ticks or {}
        self.symbols = symbols or []
        self.symbol_infos = symbol_infos or {}
        self.terminal = terminal
        self.account = account
        self.error = error

        self.initialized = False
        self.shutdown_called = False
        self.initialize_calls: list[dict[str, Any]] = []
        self.selected: list[tuple[str, bool]] = []

    # -- lifecycle
    def initialize(self, **kwargs: Any) -> bool:
        self.initialize_calls.append(kwargs)
        if self._connect_sequence is not None:
            result = (
                self._connect_sequence.pop(0) if self._connect_sequence else self._single_connect
            )
        else:
            result = self._single_connect
        self.initialized = result
        if result and self.terminal is None:
            self.terminal = TerminalInfo(
                name="FakeTerminal", company="Fake", connected=True, build=4700
            )
        return result

    def shutdown(self) -> None:
        self.shutdown_called = True
        self.initialized = False

    def last_error(self) -> tuple[int | None, str]:
        return self.error

    def terminal_info(self) -> TerminalInfo | None:
        return self.terminal if self.initialized else None

    def account_info(self) -> AccountInfo | None:
        return self.account

    # -- symbols
    def symbols_get(self) -> list[str]:
        return list(self.symbols)

    def symbol_info(self, symbol: str) -> SymbolInfo | None:
        return self.symbol_infos.get(symbol)

    def symbol_select(self, symbol: str, enable: bool) -> bool:
        self.selected.append((symbol, enable))
        return True

    def symbol_info_tick(self, symbol: str) -> Tick | None:
        values = self.ticks.get(symbol, [])
        return values[-1] if values else None

    # -- rates / ticks
    def copy_rates_from_pos(
        self, symbol: str, timeframe: str, count: int, start: int = 0
    ) -> list[Candle]:
        # MT5 semantics: position 0 is the most recent bar.
        values = list(self.rates.get((symbol, timeframe), []))
        if count <= 0:
            return []
        end = len(values) - start
        begin = max(0, end - count)
        return values[begin:end]

    def copy_rates_range(self, symbol, timeframe, start, end) -> list[Candle]:
        return [c for c in self.rates.get((symbol, timeframe), []) if start <= c.open_time <= end]

    def copy_ticks_from(self, symbol: str, start, count: int) -> list[Tick]:
        values = self.ticks.get(symbol, [])
        return [t for t in values if t.time >= start][:count]

    def copy_ticks_range(self, symbol: str, start, end) -> list[Tick]:
        return [t for t in self.ticks.get(symbol, []) if start <= t.time <= end]


def make_symbol(
    *,
    canonical: str = "EURUSD",
    broker_symbol: str = "EURUSD",
    is_otc: bool = False,
    category: str = "forex",
    profile=None,
    **overrides: Any,
):
    """Create a :class:`MarketSymbol` with sensible defaults."""
    from apps.market_data.models import MarketSymbol

    values = {
        "canonical": canonical,
        "broker_symbol": broker_symbol,
        "is_otc": is_otc,
        "category": category,
        "profile": profile,
    }
    values.update(overrides)
    return MarketSymbol.objects.create(**values)
