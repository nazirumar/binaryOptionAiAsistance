"""MetaTrader5Client DTO-conversion tests using an injected fake module."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from apps.market_data.services.mt5_client import (
    MetaTrader5Client,
    _rate_to_candle,
    _tick_to_dto,
)


def test_rate_to_candle_converts_utc_seconds():
    row = {
        "time": 1700000000,
        "open": 1.1000,
        "high": 1.1050,
        "low": 1.0950,
        "close": 1.1020,
        "tick_volume": 42,
        "spread": 7,
        "real_volume": None,
    }
    candle = _rate_to_candle(row)
    assert candle.open_time == datetime.fromtimestamp(1700000000, tz=UTC)
    assert str(candle.close) == "1.102"
    assert candle.tick_volume == 42
    assert candle.spread == 7


def test_tick_to_dto_prefers_millisecond_time():
    row = {
        "time": 1700000000,
        "time_msc": 1700000000500,
        "bid": 1.1,
        "ask": 1.2,
        "last": 0,
        "volume": 0,
        "flags": 3,
    }
    tick = _tick_to_dto(row)
    assert tick.time == datetime.fromtimestamp(1700000000.5, tz=UTC)
    assert str(tick.bid) == "1.1"


def _fake_module() -> SimpleNamespace:
    return SimpleNamespace(
        COPY_TICKS_ALL=2,
        initialize=lambda **kwargs: True,
        shutdown=lambda: None,
        last_error=lambda: (1, "boom"),
        terminal_info=lambda: {
            "name": "MetaTrader 5",
            "company": "Acme",
            "path": "C:/mt5",
            "connected": True,
            "build": 4700,
        },
        account_info=lambda: {
            "login": 12345678,
            "server": "Acme-Demo",
            "company": "Acme",
            "currency": "USD",
            "leverage": 100,
        },
        symbols_get=lambda: [{"name": "EURUSD"}, {"name": "XAUUSD"}],
        symbol_info=lambda symbol: {
            "name": symbol,
            "description": "Euro vs Dollar",
            "digits": 5,
            "point": 0.00001,
            "trade_tick_size": 0.00001,
            "trade_contract_size": 100000,
            "currency_base": "EUR",
            "currency_profit": "USD",
            "currency_margin": "EUR",
            "trade_mode": 4,
            "spread": 12,
            "visible": True,
        },
        symbol_select=lambda symbol, enable: True,
        symbol_info_tick=lambda symbol: {
            "time_msc": 1700000000000,
            "bid": 1.1,
            "ask": 1.2,
            "last": 0,
            "volume": 0,
            "flags": 3,
        },
        copy_rates_from_pos=lambda symbol, tf, start, count: [
            {
                "time": 1700000000,
                "open": 1.1,
                "high": 1.2,
                "low": 1.0,
                "close": 1.15,
                "tick_volume": 1,
                "spread": 1,
                "real_volume": 0,
            }
        ],
        copy_rates_range=lambda symbol, tf, start, end: [],
        copy_ticks_from=lambda symbol, start, count, flags: [
            {"time_msc": 1700000000000, "bid": 1.1, "ask": 1.2, "last": 0, "volume": 0, "flags": 3}
        ],
        copy_ticks_range=lambda symbol, start, end, flags: [],
    )


def test_client_info_methods_use_injected_module():
    client = MetaTrader5Client(module=_fake_module())
    assert client.initialize(server="x") is True
    assert client.last_error() == (1, "boom")
    assert client.terminal_info().name == "MetaTrader 5"
    assert client.account_info().login == 12345678
    assert client.symbols_get() == ["EURUSD", "XAUUSD"]
    info = client.symbol_info("EURUSD")
    assert info.digits == 5
    assert info.point == Decimal("0.00001")
    tick = client.symbol_info_tick("EURUSD")
    assert tick.ask is not None


def test_client_copy_rates_from_pos(monkeypatch):
    monkeypatch.setattr("apps.market_data.services.timeframe_mapper.to_mt5", lambda timeframe: 1)
    client = MetaTrader5Client(module=_fake_module())
    candles = client.copy_rates_from_pos("EURUSD", "M1", count=1)
    assert len(candles) == 1
    assert candles[0].open_time == datetime.fromtimestamp(1700000000, tz=UTC)


def test_client_copy_ticks_from(monkeypatch):
    client = MetaTrader5Client(module=_fake_module())
    ticks = client.copy_ticks_from("EURUSD", datetime(2026, 1, 1, tzinfo=UTC), 1)
    assert len(ticks) == 1
