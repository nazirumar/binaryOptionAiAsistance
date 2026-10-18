"""Celery task wiring tests for market data (MT5 mocked)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.market_data import tasks
from apps.market_data.constants import HealthKind
from apps.market_data.models import MarketCandle, MarketDataHealthEvent, MarketTick
from tests.marketdata_fakes import FakeMT5Gateway, candle_series, make_symbol, make_tick

pytestmark = pytest.mark.django_db


def _series(count: int = 5):
    return candle_series(count, "M1", start=timezone.now() - timedelta(minutes=count + 2))


def test_check_connection_task_success(monkeypatch):
    gateway = FakeMT5Gateway(connect=True)
    monkeypatch.setattr(tasks, "MetaTrader5Client", lambda: gateway)

    result = tasks.check_connection_task()
    assert result["connected"] is True
    assert gateway.shutdown_called is True
    assert MarketDataHealthEvent.objects.filter(kind=HealthKind.CONNECTION).exists()


def test_check_connection_task_failure_records_event(monkeypatch):
    gateway = FakeMT5Gateway(connect=False, error=(-1, "no terminal"))
    monkeypatch.setattr(tasks, "MetaTrader5Client", lambda: gateway)

    result = tasks.check_connection_task()
    assert result["connected"] is False
    assert MarketDataHealthEvent.objects.filter(kind=HealthKind.CONNECTION).exists()


def test_sync_candles_task(monkeypatch):
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    gateway = FakeMT5Gateway(connect=True, rates={("EURUSD", "M1"): _series(5)})
    monkeypatch.setattr(tasks, "MetaTrader5Client", lambda: gateway)

    result = tasks.sync_candles_task(symbol.pk, "M1", 5)
    assert result["status"] in {"success", "partial"}
    assert MarketCandle.objects.filter(symbol=symbol).count() >= 3


def test_sync_candles_task_missing_symbol():
    assert tasks.sync_candles_task(999999, "M1", 5)["status"] == "missing"


def test_sync_ticks_task(monkeypatch):
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    gateway = FakeMT5Gateway(
        connect=True, ticks={"EURUSD": [make_tick(timezone.now() - timedelta(seconds=2))]}
    )
    monkeypatch.setattr(tasks, "MetaTrader5Client", lambda: gateway)

    result = tasks.sync_ticks_task(symbol.pk)
    assert result["status"] == "success"
    assert MarketTick.objects.filter(symbol=symbol).count() == 1


def test_purge_ticks_task(monkeypatch):
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    from apps.market_data.services.tick_service import persist_ticks

    persist_ticks(symbol, [make_tick(timezone.now() - timedelta(days=30))])
    result = tasks.purge_ticks_task(retention_days=7)
    assert result["deleted"] == 1
    assert symbol.ticks.count() == 0
