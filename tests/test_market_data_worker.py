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


def test_worker_records_connection_event_on_success(monkeypatch):
    """A clean connect must record a CONNECTION event so the dashboard does not
    stay stuck on a previous disconnect ("last event wins")."""
    from apps.market_data.constants import ConnectionState
    from apps.market_data.dashboard import derived_connection_state

    make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
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
        "success-worker",
    )

    assert MarketDataHealthEvent.objects.filter(kind=HealthKind.CONNECTION).exists()
    assert derived_connection_state() == ConnectionState.CONNECTED


def test_worker_records_connection_event_after_reconnect(monkeypatch):
    """After a disconnect, the next successful cycle records a CONNECTION event
    so the dashboard stops reporting a stale "error"."""
    from apps.market_data.constants import ConnectionState
    from apps.market_data.dashboard import derived_connection_state
    from apps.market_data.services.exceptions import MarketDataError

    make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    gateway = FakeMT5Gateway(
        connect=True,
        rates={("EURUSD", "M1"): _recent_series(5)},
        ticks={"EURUSD": [make_tick(timezone.now() - timedelta(seconds=2))]},
    )
    monkeypatch.setattr(worker_module, "MetaTrader5Client", lambda: gateway)

    class _Stop(Exception):
        pass

    class FlakyManager:
        """First ensure_connected() raises, the second succeeds, then stop."""

        def __init__(self, *args, **kwargs):
            self.calls = 0

        def connect(self):
            return True

        def ensure_connected(self):
            self.calls += 1
            if self.calls == 1:
                raise MarketDataError("lost the terminal")
            return True

        def disconnect(self):
            return None

    monkeypatch.setattr(worker_module, "MT5ConnectionManager", FlakyManager)
    monkeypatch.setattr(worker_module.Command, "_sleep", lambda self, interval, stop: None)

    original_cycle = worker_module.Command._run_cycle_direct

    def _cycle_then_stop(self, *args, **kwargs):
        original_cycle(self, *args, **kwargs)
        # Both cycles have run (disconnect then reconnect): stop the loop.
        raise _Stop()

    monkeypatch.setattr(worker_module.Command, "_run_cycle_direct", _cycle_then_stop)

    with pytest.raises(_Stop):
        call_command(
            "mt5_worker",
            "--symbols",
            "EURUSD",
            "--timeframes",
            "M1",
            "--collector",
            "reconnect-worker",
        )

    kinds = list(
        MarketDataHealthEvent.objects.order_by("occurred_at").values_list("kind", flat=True)
    )
    assert HealthKind.DISCONNECT in kinds
    assert kinds[-1] == HealthKind.CONNECTION  # reconnect is the most recent event
    assert derived_connection_state() == ConnectionState.CONNECTED


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


def test_worker_unions_monitored_instruments_and_timeframes(monkeypatch):
    """The worker adds whatever enabled monitors require, so a monitor created
    from the UI is fed without editing settings."""
    from apps.live_signals.models import InstrumentMonitor

    InstrumentMonitor.objects.create(
        canonical_instrument="GBPUSD", timeframe="M15", market_type="regular"
    )

    command = worker_module.Command()
    _interval, symbols, timeframes, _collector = command._resolve_options(
        {
            "interval": None,
            "symbols": "EURUSD",
            "timeframes": "M1",
            "collector": "",
        }
    )

    assert "EURUSD" in symbols and "GBPUSD" in symbols
    assert "M1" in timeframes and "M15" in timeframes


def test_worker_monitored_pairs_ignores_disabled_monitors():
    from apps.live_signals.models import InstrumentMonitor

    InstrumentMonitor.objects.create(
        canonical_instrument="GBPUSD", timeframe="M5", market_type="regular", enabled=False
    )
    symbols, timeframes = worker_module.Command._monitored_pairs()
    assert "GBPUSD" not in symbols
    assert "M5" not in timeframes
