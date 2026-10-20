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


# ---------------------------------------------------------------------------
# Server-clock offset: MT5 timestamps are broker wall-clock, not UTC.
# ---------------------------------------------------------------------------
def test_rate_to_candle_applies_server_offset():
    row = {"time": 1700000000, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.1}
    candle = _rate_to_candle(row, offset_seconds=3 * 3600)
    assert candle.open_time == datetime.fromtimestamp(1700000000 - 3 * 3600, tz=UTC)


def test_tick_to_dto_applies_server_offset_and_keeps_milliseconds():
    row = {"time_msc": 1700000000500, "bid": 1.1, "ask": 1.2}
    tick = _tick_to_dto(row, offset_seconds=3600)
    assert tick.time == datetime.fromtimestamp(1700000000.5 - 3600, tz=UTC)


def test_offset_defaults_to_zero_when_unset():
    """No offset configured/detected must never shift a timestamp."""
    row = {"time": 1700000000, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.1}
    assert _rate_to_candle(row).open_time == datetime.fromtimestamp(1700000000, tz=UTC)


def test_explicit_offset_is_respected_and_not_detected():
    client = MetaTrader5Client(module=_fake_module(), server_offset_seconds=7200)
    assert client._offset() == 7200  # never re-detects when given explicitly


def test_detected_offset_from_live_tick(monkeypatch):
    """The offset is derived from a fresh tick's server epoch vs true UTC."""
    real_now = datetime.now(tz=UTC)
    server_epoch = int(real_now.timestamp()) + 3 * 3600  # server runs UTC+3
    module = _fake_module()
    module.symbol_info_tick = lambda symbol: {
        "time": server_epoch,
        "time_msc": server_epoch * 1000,
        "bid": 1.1,
        "ask": 1.2,
    }
    client = MetaTrader5Client(module=module)
    # Rounded to the nearest minute, so a few seconds of latency is absorbed.
    assert client.detect_server_offset() == 3 * 3600


def test_configured_offset_overrides_detection(monkeypatch):
    from django.test import override_settings

    with override_settings(MT5_SERVER_TZ_OFFSET_MINUTES=180):
        client = MetaTrader5Client(module=_fake_module())
        assert client.detect_server_offset() == 180 * 60


def test_unmeasurable_offset_falls_back_to_zero(monkeypatch):
    """A terminal that cannot be sampled yields 0 - never a guessed shift."""
    module = _fake_module()
    module.symbol_info_tick = lambda symbol: None
    client = MetaTrader5Client(module=module)
    assert client.detect_server_offset() == 0

