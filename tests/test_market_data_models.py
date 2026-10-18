"""Market data model constraint tests."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.market_data.models import (
    MarketCandle,
    MarketDataHealthEvent,
    MarketDataSyncLog,
    MT5ConnectionProfile,
    WorkerHeartbeat,
)
from tests.marketdata_fakes import BASE_TIME, make_candle, make_symbol, make_tick


@pytest.mark.django_db
def test_profile_masked_login():
    profile = MT5ConnectionProfile.objects.create(name="Demo", login=987654321, server="Acme")
    assert profile.masked_login == "*******21"


@pytest.mark.django_db
def test_candle_unique_constraint():
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    candle = make_candle(BASE_TIME)
    MarketCandle.objects.create(
        symbol=symbol,
        timeframe="M1",
        open_time=candle.open_time,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        MarketCandle.objects.create(
            symbol=symbol,
            timeframe="M1",
            open_time=candle.open_time,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
        )


@pytest.mark.django_db
def test_tick_unique_constraint():
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    tick = make_tick(BASE_TIME)
    from apps.market_data.services.tick_service import persist_ticks

    persist_ticks(symbol, [tick])
    assert symbol.ticks.count() == 1


@pytest.mark.django_db
def test_model_str_methods():
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSDm")
    assert "EURUSD -> EURUSDm" in str(symbol)

    log = MarketDataSyncLog.objects.create(kind="candles", timeframe="M1", started_at=BASE_TIME)
    assert "candles" in str(log)

    event = MarketDataHealthEvent.objects.create(
        kind="connection", severity="info", message="ok", occurred_at=BASE_TIME
    )
    assert "connection" in str(event)

    heartbeat = WorkerHeartbeat.objects.create(worker_id="w1", last_seen=BASE_TIME)
    assert "w1" in str(heartbeat)
