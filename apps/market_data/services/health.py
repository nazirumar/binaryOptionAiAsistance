"""Persistence helpers for market-data health events and worker heartbeats."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from apps.market_data.constants import HealthKind, Severity, WorkerStatus


def record_health_event(
    *,
    kind: str,
    message: str,
    severity: str = Severity.INFO,
    profile=None,
    symbol=None,
    detail: dict[str, Any] | None = None,
    collector: str = "",
    occurred_at: datetime | None = None,
):
    """Create a :class:`MarketDataHealthEvent` and return it."""
    from apps.market_data.models import MarketDataHealthEvent

    return MarketDataHealthEvent.objects.create(
        kind=kind,
        severity=severity,
        message=message[:255],
        detail=detail or {},
        profile=profile,
        symbol=symbol,
        collector=collector,
        occurred_at=occurred_at or datetime.now(tz=UTC),
    )


def record_connection_event(
    *,
    connected: bool,
    message: str = "",
    profile=None,
    detail: dict[str, Any] | None = None,
    collector: str = "",
):
    """Record a connect/disconnect event with the appropriate severity."""
    return record_health_event(
        kind=HealthKind.CONNECTION if connected else HealthKind.DISCONNECT,
        severity=Severity.INFO if connected else Severity.ERROR,
        message=message or ("Connected to MT5." if connected else "Disconnected from MT5."),
        profile=profile,
        detail=detail,
        collector=collector,
    )


def upsert_heartbeat(
    *,
    worker_id: str,
    status: str = WorkerStatus.ONLINE,
    detail: dict[str, Any] | None = None,
    seen_at: datetime | None = None,
):
    """Create or update a worker heartbeat row."""
    from apps.market_data.models import WorkerHeartbeat

    heartbeat, _ = WorkerHeartbeat.objects.update_or_create(
        worker_id=worker_id,
        defaults={
            "status": status,
            "detail": detail or {},
            "last_seen": seen_at or datetime.now(tz=UTC),
        },
    )
    return heartbeat


__all__ = ["record_connection_event", "record_health_event", "upsert_heartbeat"]
