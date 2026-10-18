"""Candle retrieval, completeness and idempotent persistence tests."""

from __future__ import annotations

from datetime import timedelta

import pytest

from apps.market_data.services.candle_service import (
    CandleService,
    is_candle_complete,
    persist_candles,
    split_completed_and_forming,
)
from apps.market_data.services.timeframe_mapper import duration
from tests.marketdata_fakes import (
    BASE_TIME,
    FakeMT5Gateway,
    candle_series,
    make_candle,
    make_symbol,
)


def test_is_candle_complete_respects_period_and_feed_delay():
    now = BASE_TIME + duration("M1")
    # Exactly at the close, with zero feed delay -> complete.
    assert is_candle_complete(BASE_TIME, "M1", now=now, feed_delay_seconds=0)
    # With feed delay, not yet complete.
    assert not is_candle_complete(BASE_TIME, "M1", now=now, feed_delay_seconds=5)
    # Well after close -> complete.
    assert is_candle_complete(
        BASE_TIME, "M1", now=BASE_TIME + timedelta(seconds=90), feed_delay_seconds=5
    )


def test_forming_candle_is_never_complete():
    now = BASE_TIME + timedelta(seconds=30)
    assert not is_candle_complete(BASE_TIME, "M1", now=now, feed_delay_seconds=0)


def test_split_completed_and_forming():
    candles = candle_series(3, "M1")
    now = candles[-1].open_time + timedelta(seconds=10)
    completed, forming = split_completed_and_forming(candles, "M1", now=now, feed_delay_seconds=0)
    assert len(completed) == 2
    assert len(forming) == 1
    assert forming[0].open_time == candles[-1].open_time


def test_candle_service_fetch_separates_forming():
    candles = candle_series(5, "M1")
    gateway = FakeMT5Gateway(rates={("EURUSD", "M1"): candles})
    now = candles[-1].open_time + timedelta(seconds=5)
    service = CandleService(gateway, feed_delay_seconds=0, now_fn=lambda: now)
    result = service.fetch("EURUSD", "M1", count=5)
    assert len(result.completed) == 4
    assert result.forming is not None
    assert result.forming.open_time == candles[-1].open_time


def test_candle_service_latest_completed():
    candles = candle_series(5, "M1")
    gateway = FakeMT5Gateway(rates={("EURUSD", "M1"): candles})
    now = candles[-1].open_time + timedelta(seconds=5)
    service = CandleService(gateway, feed_delay_seconds=0, now_fn=lambda: now)
    assert service.latest_completed_candle("EURUSD", "M1").open_time == candles[-2].open_time


@pytest.mark.django_db
def test_persist_candles_is_idempotent():
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    candles = candle_series(3, "M1")
    now = candles[-1].open_time + timedelta(seconds=120)

    first = persist_candles(symbol, "M1", candles, now=now, feed_delay_seconds=0)
    assert first.inserted == 3
    assert first.updated == 0

    second = persist_candles(symbol, "M1", candles, now=now, feed_delay_seconds=0)
    assert second.inserted == 0
    assert second.skipped == 3

    assert symbol.candles.count() == 3


@pytest.mark.django_db
def test_persist_candles_updates_changed_values():
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    candle = make_candle(BASE_TIME, c="1.1020")
    now = BASE_TIME + timedelta(seconds=120)
    persist_candles(symbol, "M1", [candle], now=now, feed_delay_seconds=0)

    changed = make_candle(BASE_TIME, c="1.1099")
    result = persist_candles(symbol, "M1", [changed], now=now, feed_delay_seconds=0)
    assert result.updated == 1
    assert symbol.candles.get().close == changed.close


@pytest.mark.django_db
def test_persist_marks_forming_candle_incomplete():
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    candle = make_candle(BASE_TIME)
    now = BASE_TIME + timedelta(seconds=10)  # still forming
    persist_candles(symbol, "M1", [candle], now=now, feed_delay_seconds=0)
    stored = symbol.candles.get()
    assert stored.is_complete is False
    assert stored.quality_status == "incomplete"


@pytest.mark.django_db
def test_persist_never_fabricates_missing_candles():
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    series = [make_candle(BASE_TIME), make_candle(BASE_TIME + 3 * duration("M1"))]
    now = BASE_TIME + duration("M1") * 10
    persist_candles(symbol, "M1", series, now=now, feed_delay_seconds=0)
    # Only the two supplied candles are stored; the gap is never back-filled.
    assert symbol.candles.count() == 2
