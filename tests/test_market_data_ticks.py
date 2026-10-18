"""Tick staleness, spread and bounded-storage tests."""

from __future__ import annotations

from datetime import timedelta

import pytest

from apps.market_data.services.tick_service import (
    TickService,
    is_tick_stale,
    persist_ticks,
    purge_old_ticks,
    spread_abs,
    spread_points,
)
from tests.marketdata_fakes import BASE_TIME, FakeMT5Gateway, make_symbol, make_tick


def test_is_tick_stale():
    tick = make_tick(BASE_TIME)
    assert not is_tick_stale(tick, now=BASE_TIME + timedelta(seconds=30), stale_seconds=120)
    assert is_tick_stale(tick, now=BASE_TIME + timedelta(seconds=600), stale_seconds=120)


def test_spread_helpers():
    tick = make_tick(BASE_TIME, bid="1.1000", ask="1.1002")
    assert spread_abs(tick) == tick.ask - tick.bid
    assert spread_points(tick, point=0.0001) is not None
    assert spread_points(tick, point=None) is None


def test_tick_service_latest_with_validation():
    stale_tick = make_tick(BASE_TIME)
    gateway = FakeMT5Gateway(ticks={"EURUSD": [stale_tick]})
    service = TickService(
        gateway, stale_seconds=120, now_fn=lambda: BASE_TIME + timedelta(minutes=10)
    )
    tick, issues = service.latest_with_validation("EURUSD")
    assert tick is stale_tick
    assert any(i.code == "stale_tick" for i in issues)


@pytest.mark.django_db
def test_persist_ticks_is_idempotent():
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    ticks = [make_tick(BASE_TIME), make_tick(BASE_TIME + timedelta(seconds=1))]

    first = persist_ticks(symbol, ticks)
    assert first.inserted == 2
    second = persist_ticks(symbol, ticks)
    assert second.inserted == 0
    assert second.skipped == 2
    assert symbol.ticks.count() == 2


@pytest.mark.django_db
def test_purge_old_ticks_removes_expired_only():
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    old_tick = make_tick(BASE_TIME)
    recent_tick = make_tick(BASE_TIME + timedelta(days=30))
    persist_ticks(symbol, [old_tick, recent_tick])

    deleted = purge_old_ticks(retention_days=7, now=BASE_TIME + timedelta(days=31))
    assert deleted == 1
    assert symbol.ticks.count() == 1


@pytest.mark.django_db
def test_tick_spread_property():
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    persist_ticks(symbol, [make_tick(BASE_TIME, bid="1.1000", ask="1.1002")])
    tick = symbol.ticks.get()
    assert tick.spread == tick.ask - tick.bid
