"""Read-only context builders for the market-data dashboard page."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.market_data.constants import ConnectionState, HealthKind, Severity
from apps.market_data.models import (
    MarketCandle,
    MarketDataHealthEvent,
    MarketDataSyncLog,
    MarketSymbol,
    MarketTick,
    WorkerHeartbeat,
)


def derived_connection_state(profile=None) -> str:
    query = MarketDataHealthEvent.objects.filter(
        kind__in=[HealthKind.CONNECTION, HealthKind.DISCONNECT]
    )
    if profile is not None:
        query = query.filter(profile=profile)
    event = query.order_by("-occurred_at").first()
    if event is None:
        return ConnectionState.UNKNOWN
    return (
        ConnectionState.CONNECTED if event.kind == HealthKind.CONNECTION else ConnectionState.ERROR
    )


def dashboard_context(profile=None) -> dict[str, Any]:
    """Assemble everything the MT5 dashboard card needs (no live MT5 call)."""
    now = timezone.now()
    ttl = int(getattr(settings, "MT5_WORKER_HEARTBEAT_TTL_SECONDS", 90))

    symbols = MarketSymbol.objects.filter(is_active=True)
    symbol = None
    if profile is not None:
        symbol = symbols.filter(profile=profile).order_by("canonical").first()
    if symbol is None:
        # Fall back to a shared/global mapping so the page still shows data.
        symbol = symbols.filter(profile__isnull=True).order_by("canonical").first()
    if symbol is None:
        symbol = symbols.order_by("canonical").first()

    latest_tick = None
    tick_age = None
    spread = None
    if symbol is not None:
        latest_tick = MarketTick.objects.filter(symbol=symbol).order_by("-time").first()
        if latest_tick is not None:
            tick_age = round((now - latest_tick.time).total_seconds(), 1)
            spread = latest_tick.spread

    last_candle = None
    if symbol is not None:
        last_candle = (
            MarketCandle.objects.filter(symbol=symbol, is_complete=True)
            .order_by("-open_time")
            .first()
        )

    heartbeats = []
    for heartbeat in WorkerHeartbeat.objects.all()[:10]:
        age = (now - heartbeat.last_seen).total_seconds()
        heartbeats.append(
            {
                "worker_id": heartbeat.worker_id,
                "status": heartbeat.status,
                "last_seen": heartbeat.last_seen,
                "age_seconds": round(age, 1),
                "stale": age > ttl,
            }
        )

    return {
        "connection_state": derived_connection_state(profile),
        "profile": profile,
        "broker": getattr(profile, "broker", "") or "—",
        "server": getattr(profile, "server", "") or settings.MT5_SERVER or "—",
        "masked_login": getattr(profile, "masked_login", "") or "—",
        "symbol": symbol,
        "latest_tick": latest_tick,
        "tick_age_seconds": tick_age,
        "tick_stale": (tick_age is not None and tick_age > int(settings.MT5_STALE_TICK_SECONDS)),
        "spread": spread,
        "last_candle": last_candle,
        "last_sync": MarketDataSyncLog.objects.order_by("-started_at").first(),
        "heartbeats": heartbeats,
        "recent_events": MarketDataHealthEvent.objects.filter(
            severity__in=[Severity.ERROR, Severity.CRITICAL, Severity.WARNING]
        ).order_by("-occurred_at")[:8],
        "worker_ttl": ttl,
    }
