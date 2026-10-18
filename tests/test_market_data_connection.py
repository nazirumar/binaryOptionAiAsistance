"""MT5 connection manager tests (retry, health, graceful shutdown)."""

from __future__ import annotations

import pytest

from apps.market_data.constants import ConnectionState
from apps.market_data.services.connection_manager import (
    ConnectionConfig,
    MT5ConnectionManager,
    mask_account,
    resolve_secret,
)
from apps.market_data.services.dto import AccountInfo, TerminalInfo
from apps.market_data.services.exceptions import MT5ConnectionError, MT5UnavailableError
from tests.marketdata_fakes import FakeMT5Gateway


def _config() -> ConnectionConfig:
    return ConnectionConfig(path="", login=0, password="", server="Broker-Demo", timeout_ms=1000)


def test_mask_account():
    assert mask_account(None) == ""
    assert mask_account(123) == "***"
    assert mask_account(12345678) == "******78"


def test_resolve_secret(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "s3cr3t")
    assert resolve_secret("MY_SECRET") == "s3cr3t"
    assert resolve_secret("") == ""
    assert resolve_secret("MISSING") == ""


def test_connect_success():
    gateway = FakeMT5Gateway(connect=True)
    manager = MT5ConnectionManager(gateway, _config())
    assert manager.connect() is True
    assert manager.is_connected
    assert gateway.initialize_calls[0]["server"] == "Broker-Demo"


def test_connect_retries_with_exponential_backoff():
    gateway = FakeMT5Gateway(connect=[False, False, True], error=(-1, "connection failed"))
    slept: list[float] = []
    manager = MT5ConnectionManager(
        gateway,
        _config(),
        max_retries=3,
        backoff_seconds=1.0,
        backoff_max_seconds=30.0,
        sleep=slept.append,
    )
    assert manager.connect() is True
    assert slept == [1.0, 2.0]


def test_connect_exhausts_retries_and_raises():
    gateway = FakeMT5Gateway(connect=[False, False, False], error=(-1, "connection failed"))
    slept: list[float] = []
    manager = MT5ConnectionManager(
        gateway,
        _config(),
        max_retries=3,
        backoff_seconds=1.0,
        backoff_max_seconds=30.0,
        sleep=slept.append,
    )
    with pytest.raises(MT5ConnectionError):
        manager.connect()
    assert slept == [1.0, 2.0]
    assert not manager.is_connected


def test_connect_propagates_unavailable_error():
    class UnavailableGateway(FakeMT5Gateway):
        def initialize(self, **kwargs):
            raise MT5UnavailableError("package missing")

    manager = MT5ConnectionManager(UnavailableGateway(), _config())
    with pytest.raises(MT5UnavailableError):
        manager.connect()


def test_health_check_disconnected():
    manager = MT5ConnectionManager(FakeMT5Gateway(connect=True), _config())
    health = manager.health_check()
    assert health.state == ConnectionState.DISCONNECTED
    assert health.connected is False


def test_health_check_connected_masks_login():
    account = AccountInfo(login=12345678, server="Broker-Demo", company="Broker Co")
    gateway = FakeMT5Gateway(
        connect=True,
        terminal=TerminalInfo(name="MetaTrader 5", company="Broker Co", connected=True, build=4700),
        account=account,
    )
    manager = MT5ConnectionManager(gateway, _config())
    manager.connect()
    health = manager.health_check()
    assert health.connected is True
    assert health.state == ConnectionState.CONNECTED
    assert health.masked_login == "******78"
    assert "12345678" not in health.masked_login


def test_disconnect_is_graceful_and_idempotent():
    gateway = FakeMT5Gateway(connect=True)
    manager = MT5ConnectionManager(gateway, _config())
    manager.connect()
    manager.disconnect()
    assert gateway.shutdown_called is True
    assert manager.is_connected is False
    # A second disconnect must not raise.
    manager.disconnect()


def test_context_manager_connects_and_disconnects():
    gateway = FakeMT5Gateway(connect=True)
    manager = MT5ConnectionManager(gateway, _config())
    with manager as active:
        assert active.is_connected
    assert gateway.shutdown_called is True


def test_password_never_appears_in_repr():
    gateway = FakeMT5Gateway(connect=True)
    config = ConnectionConfig(server="Broker", login=42, password="topsecret")
    manager = MT5ConnectionManager(gateway, config)
    assert "topsecret" not in repr(manager)
