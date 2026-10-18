"""MT5 worker command tests (direct and push modes, disconnection handling)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.market_data.constants import HealthKind
from apps.market_data.management.commands import mt5_worker as worker_module
from apps.market_data.models import (
    MarketCandle,
    MarketDataHealthEvent,
    MarketTick,
    WorkerHeartbeat,
)
from tests.marketdata_fakes import FakeMT5Gateway, make_symbol, make_tick

pytestmark = pytest.mark.django_db


def _recent_series(count: int = 5):
    from tests.marketdata_fakes import candle_series

    start = timezone.now() - timedelta(minutes=count + 2)
    return candle_series(count, "M1", start=start)


def test_worker_direct_mode_collects_and_persists(monkeypatch):
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    gateway = FakeMT5Gateway(
        connect=True,
        rates={("EURUSD", "M1"): _recent_series(5)},
        ticks={"EURUSD": [make_tick(timezone.now() - timedelta(seconds=2))]},
    )
    monkeypatch.setattr(worker_module, "MetaTrader5Client", lambda: gateway)

    call_command(
        "mt5_worker",
        "--once",
        "--symbols",
        "EURUSD",
        "--timeframes",
        "M1",
        "--collector",
        "unit-worker",
    )

    assert MarketCandle.objects.filter(symbol=symbol).count() >= 3
    assert MarketTick.objects.filter(symbol=symbol).count() == 1
    assert WorkerHeartbeat.objects.filter(worker_id="unit-worker").exists()
    assert gateway.shutdown_called is True


def test_worker_records_health_on_connection_failure(monkeypatch):
    make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    gateway = FakeMT5Gateway(connect=False, error=(-1, "cannot reach terminal"))
    monkeypatch.setattr(worker_module, "MetaTrader5Client", lambda: gateway)

    with pytest.raises(CommandError):
        call_command(
            "mt5_worker",
            "--once",
            "--symbols",
            "EURUSD",
            "--timeframes",
            "M1",
            "--collector",
            "fail-worker",
        )
    assert MarketDataHealthEvent.objects.filter(kind=HealthKind.CONNECTION).exists()


def test_worker_skips_unknown_symbol_mapping(monkeypatch):
    gateway = FakeMT5Gateway(connect=True)
    monkeypatch.setattr(worker_module, "MetaTrader5Client", lambda: gateway)

    with pytest.raises(CommandError):
        # No mapping exists, so the worker refuses to start.
        call_command("mt5_worker", "--once", "--symbols", "ZZZUSD", "--timeframes", "M1")

    assert MarketDataHealthEvent.objects.filter(kind=HealthKind.MAPPING).exists()


def test_worker_push_mode_posts_to_remote(monkeypatch):
    make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    gateway = FakeMT5Gateway(
        connect=True,
        rates={("EURUSD", "M1"): _recent_series(5)},
        ticks={"EURUSD": [make_tick(timezone.now() - timedelta(seconds=2))]},
    )
    monkeypatch.setattr(worker_module, "MetaTrader5Client", lambda: gateway)

    captured: dict = {}

    class FakeRemote:
        def __init__(self, base_url, token):
            captured["base_url"] = base_url
            captured["token"] = token
            captured["candles"] = []
            captured["ticks"] = []
            captured["beats"] = []

        def ingest_candles(self, **kwargs):
            captured["candles"].append(kwargs)

        def ingest_ticks(self, **kwargs):
            captured["ticks"].append(kwargs)

        def heartbeat(self, **kwargs):
            captured["beats"].append(kwargs)

    monkeypatch.setattr(worker_module, "RemoteIngestClient", FakeRemote)

    call_command(
        "mt5_worker",
        "--once",
        "--symbols",
        "EURUSD",
        "--timeframes",
        "M1",
        "--collector",
        "push-worker",
        "--push-url",
        "https://server.example",
        "--worker-token",
        "tok",
    )

    assert captured["base_url"] == "https://server.example"
    assert captured["candles"]
    assert captured["ticks"]
    assert captured["beats"]
