"""Candle retrieval, completeness detection and idempotent persistence.

A candle returned by MT5 is **not** assumed to be complete. Completeness is
derived from the candle's open time, its timeframe duration, the current UTC
time and a configurable feed-delay allowance.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import transaction

from apps.market_data.constants import DataSource, QualityStatus
from apps.market_data.services.data_validator import (
    ValidationIssue,
    summarise_issues,
    validate_candle_series,
)
from apps.market_data.services.dto import Candle
from apps.market_data.services.exceptions import UnsupportedTimeframeError
from apps.market_data.services.mt5_client import MT5Gateway
from apps.market_data.services.timeframe_mapper import duration, is_supported

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _feed_delay(feed_delay_seconds: int | None) -> int:
    if feed_delay_seconds is not None:
        return feed_delay_seconds
    return int(getattr(settings, "MT5_FEED_DELAY_SECONDS", 5))


def is_candle_complete(
    open_time: datetime,
    timeframe: str,
    *,
    now: datetime | None = None,
    feed_delay_seconds: int | None = None,
) -> bool:
    """Return whether a candle's period has fully closed (plus feed delay)."""
    if not is_supported(timeframe):
        raise UnsupportedTimeframeError(f"Unsupported timeframe {timeframe!r}")
    now = now or _utc_now()
    expected_close = open_time + duration(timeframe)
    return now >= expected_close + timedelta(seconds=_feed_delay(feed_delay_seconds))


def split_completed_and_forming(
    candles: list[Candle],
    timeframe: str,
    *,
    now: datetime | None = None,
    feed_delay_seconds: int | None = None,
) -> tuple[list[Candle], list[Candle]]:
    """Partition candles into completed and still-forming ones."""
    now = now or _utc_now()
    completed: list[Candle] = []
    forming: list[Candle] = []
    for candle in candles:
        target = (
            completed
            if is_candle_complete(
                candle.open_time, timeframe, now=now, feed_delay_seconds=feed_delay_seconds
            )
            else forming
        )
        target.append(candle)
    completed.sort(key=lambda c: c.open_time)
    forming.sort(key=lambda c: c.open_time)
    return completed, forming


@dataclass(slots=True, frozen=True)
class CandleFetchResult:
    completed: list[Candle]
    forming: Candle | None
    now: datetime


@dataclass(slots=True)
class CandlePersistResult:
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    quality_status: str = QualityStatus.OK
    issues: list[ValidationIssue] = field(default_factory=list)
    summary: str = "ok"


class CandleService:
    """Fetches candles from a gateway and separates forming from completed bars."""

    def __init__(
        self,
        client: MT5Gateway,
        *,
        feed_delay_seconds: int | None = None,
        now_fn: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.client = client
        self.feed_delay_seconds = feed_delay_seconds
        self._now = now_fn

    def _require_timeframe(self, timeframe: str) -> None:
        if not is_supported(timeframe):
            raise UnsupportedTimeframeError(f"Unsupported timeframe {timeframe!r}")

    def fetch(
        self,
        broker_symbol: str,
        timeframe: str,
        count: int,
        *,
        include_forming: bool = True,
    ) -> CandleFetchResult:
        """Fetch the most recent ``count`` candles and classify completeness."""
        self._require_timeframe(timeframe)
        now = self._now()
        candles = self.client.copy_rates_from_pos(broker_symbol, timeframe, count=count, start=0)
        completed, forming = split_completed_and_forming(
            candles, timeframe, now=now, feed_delay_seconds=self.feed_delay_seconds
        )
        latest_forming = forming[-1] if forming and include_forming else None
        return CandleFetchResult(completed=completed, forming=latest_forming, now=now)

    def fetch_completed_range(
        self, broker_symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Candle]:
        """Fetch historical completed candles within ``[start, end]`` (UTC)."""
        self._require_timeframe(timeframe)
        candles = self.client.copy_rates_range(broker_symbol, timeframe, start, end)
        now = self._now()
        completed, _ = split_completed_and_forming(
            candles, timeframe, now=now, feed_delay_seconds=self.feed_delay_seconds
        )
        return completed

    def latest_completed_candle(self, broker_symbol: str, timeframe: str) -> Candle | None:
        result = self.fetch(broker_symbol, timeframe, count=3, include_forming=False)
        return result.completed[-1] if result.completed else None

    def current_forming_candle(self, broker_symbol: str, timeframe: str) -> Candle | None:
        result = self.fetch(broker_symbol, timeframe, count=3, include_forming=True)
        return result.forming


def persist_candles(
    symbol,
    timeframe: str,
    candles: list[Candle],
    *,
    source: str = DataSource.MT5,
    collector: str = "",
    now: datetime | None = None,
    feed_delay_seconds: int | None = None,
) -> CandlePersistResult:
    """Idempotently persist candles for a symbol/timeframe.

    Duplicate ``(symbol, timeframe, open_time)`` rows are updated only when their
    values actually changed; identical rows are skipped. Original source values
    are preserved and never interpolated.
    """
    from apps.market_data.models import MarketCandle

    if not is_supported(timeframe):
        raise UnsupportedTimeframeError(f"Unsupported timeframe {timeframe!r}")

    now = now or _utc_now()
    feed_delay = _feed_delay(feed_delay_seconds)
    validation = validate_candle_series(candles, timeframe)
    result = CandlePersistResult(
        fetched=len(candles),
        quality_status=validation.quality_status,
        issues=validation.issues,
        summary=summarise_issues(validation.issues),
    )

    with transaction.atomic():
        for candle in candles:
            complete = is_candle_complete(
                candle.open_time, timeframe, now=now, feed_delay_seconds=feed_delay
            )
            quality = QualityStatus.OK
            if complete and validation.has_errors:
                quality = QualityStatus.INVALID
            elif complete and validation.has_warnings:
                quality = QualityStatus.SUSPECT
            if not complete:
                quality = QualityStatus.INCOMPLETE

            values = {
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "tick_volume": candle.tick_volume,
                "real_volume": candle.real_volume,
                "spread": candle.spread,
                "source": source,
                "is_complete": complete,
                "quality_status": quality,
            }

            existing = MarketCandle.objects.filter(
                symbol=symbol, timeframe=timeframe, open_time=candle.open_time
            ).first()
            if existing is None:
                MarketCandle.objects.create(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=candle.open_time,
                    **values,
                )
                result.inserted += 1
                continue

            if all(getattr(existing, key) == value for key, value in values.items()):
                result.skipped += 1
                continue

            for key, value in values.items():
                setattr(existing, key, value)
            existing.save(update_fields=[*values.keys(), "updated_at"])
            result.updated += 1

    logger.info(
        "market_data.candles.persisted",
        extra={
            "collector": collector,
            "symbol": getattr(symbol, "broker_symbol", str(symbol)),
            "timeframe": timeframe,
            "inserted": result.inserted,
            "updated": result.updated,
            "skipped": result.skipped,
        },
    )
    return result


__all__ = [
    "CandleFetchResult",
    "CandlePersistResult",
    "CandleService",
    "is_candle_complete",
    "persist_candles",
    "split_completed_and_forming",
]
