"""Tick retrieval, staleness detection and bounded, idempotent storage.

Tick storage is deliberately bounded: high-frequency ticks are only retained for
a configurable window (see ``MT5_TICK_RETENTION_DAYS``) and purged by a task so
the database does not grow without limit.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from apps.market_data.constants import DataSource
from apps.market_data.services.data_validator import ValidationIssue, validate_tick
from apps.market_data.services.dto import Tick
from apps.market_data.services.mt5_client import MT5Gateway

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _stale_seconds(stale_seconds: int | None) -> int:
    if stale_seconds is not None:
        return stale_seconds
    return int(getattr(settings, "MT5_STALE_TICK_SECONDS", 120))


def is_tick_stale(
    tick: Tick, *, now: datetime | None = None, stale_seconds: int | None = None
) -> bool:
    now = now or _utc_now()
    return (now - tick.time).total_seconds() > _stale_seconds(stale_seconds)


def spread_abs(tick: Tick) -> Decimal | None:
    """Absolute spread (ask - bid) when both sides are present."""
    if tick.bid is None or tick.ask is None:
        return None
    return tick.ask - tick.bid


def spread_points(tick: Tick, point: Decimal | None) -> Decimal | None:
    """Spread expressed in points using the symbol's point size."""
    difference = spread_abs(tick)
    if difference is None or not point:
        return None
    point_decimal = point if isinstance(point, Decimal) else Decimal(str(point))
    return difference / point_decimal


@dataclass(slots=True)
class TickPersistResult:
    fetched: int = 0
    inserted: int = 0
    skipped: int = 0
    issues: list[ValidationIssue] = field(default_factory=list)


class TickService:
    """Fetches ticks from a gateway and reports staleness."""

    def __init__(
        self,
        client: MT5Gateway,
        *,
        stale_seconds: int | None = None,
        now_fn: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.client = client
        self.stale_seconds = stale_seconds
        self._now = now_fn

    def fetch_latest(self, broker_symbol: str) -> Tick | None:
        return self.client.symbol_info_tick(broker_symbol)

    def latest_with_validation(
        self, broker_symbol: str
    ) -> tuple[Tick | None, list[ValidationIssue]]:
        tick = self.fetch_latest(broker_symbol)
        if tick is None:
            return None, []
        issues = validate_tick(
            tick, now=self._now(), stale_seconds=_stale_seconds(self.stale_seconds)
        )
        return tick, issues

    def fetch_range(
        self, broker_symbol: str, start: datetime, end: datetime, *, limit: int | None = None
    ) -> list[Tick]:
        ticks = self.client.copy_ticks_range(broker_symbol, start, end)
        if limit is not None and limit >= 0:
            ticks = ticks[-limit:] if limit else []
        return ticks


def persist_ticks(
    symbol,
    ticks: list[Tick],
    *,
    source: str = DataSource.MT5,
    collector: str = "",
) -> TickPersistResult:
    """Idempotently store ticks, skipping exact duplicates."""
    from apps.market_data.models import MarketTick

    result = TickPersistResult(fetched=len(ticks))
    with transaction.atomic():
        for tick in ticks:
            if MarketTick.objects.filter(symbol=symbol, time=tick.time, source=source).exists():
                result.skipped += 1
                continue
            MarketTick.objects.create(
                symbol=symbol,
                time=tick.time,
                bid=tick.bid,
                ask=tick.ask,
                last=tick.last,
                volume=tick.volume,
                flags=tick.flags,
                source=source,
            )
            result.inserted += 1

    logger.info(
        "market_data.ticks.persisted",
        extra={
            "collector": collector,
            "symbol": getattr(symbol, "broker_symbol", str(symbol)),
            "inserted": result.inserted,
            "skipped": result.skipped,
        },
    )
    return result


def purge_old_ticks(*, retention_days: int | None = None, now: datetime | None = None) -> int:
    """Delete ticks older than the retention window. Returns the count deleted."""
    from apps.market_data.models import MarketTick

    days = retention_days
    if days is None:
        days = int(getattr(settings, "MT5_TICK_RETENTION_DAYS", 7))
    cutoff = (now or _utc_now()) - timedelta(days=days)
    deleted, _ = MarketTick.objects.filter(time__lt=cutoff).delete()
    logger.info(
        "market_data.ticks.purged", extra={"deleted": deleted, "cutoff": cutoff.isoformat()}
    )
    return deleted


__all__ = [
    "TickPersistResult",
    "TickService",
    "is_tick_stale",
    "persist_ticks",
    "purge_old_ticks",
    "spread_abs",
    "spread_points",
]
