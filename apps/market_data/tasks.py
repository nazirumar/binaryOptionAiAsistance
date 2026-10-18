"""Celery tasks for market data collection.

These tasks run on a host that has the MetaTrader5 package and a terminal (a
Windows worker). On other hosts they fail fast with a recorded health event
rather than raising unhandled exceptions.
"""

from __future__ import annotations

import logging

from celery import shared_task

from apps.market_data.constants import HealthKind, Severity, SyncStatus
from apps.market_data.services.connection_manager import (
    ConnectionConfig,
    MT5ConnectionManager,
)
from apps.market_data.services.exceptions import MarketDataError
from apps.market_data.services.health import record_connection_event, record_health_event
from apps.market_data.services.mt5_client import MetaTrader5Client
from apps.market_data.services.sync_service import MarketDataSyncService
from apps.market_data.services.tick_service import purge_old_ticks

logger = logging.getLogger(__name__)


def _open_connection(profile=None):
    """Create a connected manager for a profile (or the shared settings)."""
    client = MetaTrader5Client()
    config = (
        ConnectionConfig.from_profile(profile)
        if profile is not None
        else ConnectionConfig.from_settings()
    )
    manager = MT5ConnectionManager(client, config)
    manager.connect()
    return manager, client


def _record_failure(exc: Exception, profile=None, collector: str = "celery") -> None:
    record_health_event(
        kind=HealthKind.CONNECTION,
        severity=Severity.ERROR,
        message=f"MT5 task failure: {exc}",
        profile=profile,
        collector=collector,
    )


@shared_task(name="market_data.check_connection")
def check_connection_task(profile_id: int | None = None) -> dict:
    """Connect, evaluate health, persist state and disconnect."""
    from apps.market_data.models import MT5ConnectionProfile

    profile = MT5ConnectionProfile.objects.filter(pk=profile_id).first() if profile_id else None
    try:
        manager, _ = _open_connection(profile)
    except MarketDataError as exc:
        logger.warning("market_data.check_connection.failed", extra={"error": str(exc)})
        _record_failure(exc, profile=profile)
        if profile is not None:
            from apps.market_data.constants import ConnectionState

            profile.state = ConnectionState.ERROR
            profile.save(update_fields=["state", "updated_at"])
        return {"connected": False, "error": str(exc)}

    try:
        health = manager.health_check()
        if profile is not None:
            from django.utils import timezone

            profile.state = health.state
            if health.connected:
                profile.last_connected_at = timezone.now()
            profile.save(update_fields=["state", "last_connected_at", "updated_at"])
        record_connection_event(
            connected=health.connected,
            message=(
                "Connected to MT5."
                if health.connected
                else "MT5 connect reported but not connected."
            ),
            profile=profile,
            detail={"server": health.server, "account": health.masked_login, "build": health.build},
        )
        return {
            "connected": health.connected,
            "state": health.state,
            "server": health.server,
            "masked_login": health.masked_login,
        }
    finally:
        manager.disconnect()


@shared_task(name="market_data.sync_candles")
def sync_candles_task(symbol_id: int, timeframe: str, count: int = 300) -> dict:
    """Fetch and persist candles for a mapped symbol/timeframe."""
    from apps.market_data.models import MarketSymbol

    symbol = MarketSymbol.objects.filter(pk=symbol_id).select_related("profile").first()
    if symbol is None:
        return {"status": "missing", "symbol_id": symbol_id}
    profile = symbol.profile
    try:
        manager, client = _open_connection(profile)
    except MarketDataError as exc:
        _record_failure(exc, profile=profile)
        return {"status": SyncStatus.FAILED, "error": str(exc)}
    try:
        service = MarketDataSyncService(client, profile=profile, collector="celery")
        log = service.sync_candles(symbol, timeframe, count)
        return {
            "status": log.status,
            "inserted": log.rows_inserted,
            "updated": log.rows_updated,
            "skipped": log.rows_skipped,
        }
    finally:
        manager.disconnect()


@shared_task(name="market_data.sync_ticks")
def sync_ticks_task(symbol_id: int) -> dict:
    """Fetch and persist the latest tick for a mapped symbol."""
    from apps.market_data.models import MarketSymbol

    symbol = MarketSymbol.objects.filter(pk=symbol_id).select_related("profile").first()
    if symbol is None:
        return {"status": "missing", "symbol_id": symbol_id}
    profile = symbol.profile
    try:
        manager, client = _open_connection(profile)
    except MarketDataError as exc:
        _record_failure(exc, profile=profile)
        return {"status": SyncStatus.FAILED, "error": str(exc)}
    try:
        service = MarketDataSyncService(client, profile=profile, collector="celery")
        log = service.sync_latest_tick(symbol)
        return {"status": log.status, "inserted": log.rows_inserted, "skipped": log.rows_skipped}
    finally:
        manager.disconnect()


@shared_task(name="market_data.purge_ticks")
def purge_ticks_task(retention_days: int | None = None) -> dict:
    """Delete ticks older than the retention window."""
    deleted = purge_old_ticks(retention_days=retention_days)
    return {"deleted": deleted}
