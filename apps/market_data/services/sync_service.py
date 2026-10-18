"""Orchestration: fetch -> validate -> persist -> log, with health reporting.

This is the single place that writes sync logs and health events so that the
worker, the API-triggered tasks and the manual management commands all behave
identically and idempotently.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from apps.market_data.constants import (
    HealthKind,
    MappingStatus,
    Severity,
    SyncKind,
    SyncStatus,
)
from apps.market_data.services.candle_service import CandleService, persist_candles
from apps.market_data.services.data_validator import (
    summarise_issues,
    validate_symbol_mapping,
)
from apps.market_data.services.exceptions import MarketDataError, OTCFeedMismatchError
from apps.market_data.services.health import record_health_event
from apps.market_data.services.mt5_client import MT5Gateway
from apps.market_data.services.tick_service import TickService, persist_ticks

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(slots=True)
class _LogCounters:
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    detail: dict[str, Any] | None = None


class MarketDataSyncService:
    """Runs sync operations against a connected gateway."""

    def __init__(
        self,
        client: MT5Gateway,
        *,
        profile=None,
        collector: str = "",
        now_fn: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.client = client
        self.profile = profile
        self.collector = collector
        self._now = now_fn

    # -- helpers ------------------------------------------------------------
    def _start_log(self, kind: str, *, symbol=None, timeframe: str = ""):
        from apps.market_data.models import MarketDataSyncLog

        return MarketDataSyncLog.objects.create(
            profile=self.profile,
            symbol=symbol,
            kind=kind,
            timeframe=timeframe,
            status=SyncStatus.RUNNING,
            started_at=self._now(),
            collector=self.collector,
        )

    def _finish_log(
        self,
        log,
        *,
        status: str,
        counters: _LogCounters,
        error_message: str = "",
    ):
        log.status = status
        log.finished_at = self._now()
        log.rows_fetched = counters.fetched
        log.rows_inserted = counters.inserted
        log.rows_updated = counters.updated
        log.rows_skipped = counters.skipped
        log.error_message = error_message
        log.detail = counters.detail or {}
        log.save(
            update_fields=[
                "status",
                "finished_at",
                "rows_fetched",
                "rows_inserted",
                "rows_updated",
                "rows_skipped",
                "error_message",
                "detail",
                "updated_at",
            ]
        )
        return log

    def _guard_mapping(self, symbol):
        """Refuse to sync a mapping that is invalid or OTC-incompatible."""
        validation = validate_symbol_mapping(symbol)
        if validation.has_errors:
            record_health_event(
                kind=HealthKind.MAPPING,
                severity=Severity.ERROR,
                message=summarise_issues(validation.issues),
                profile=self.profile,
                symbol=symbol,
                detail={"issues": [i.code for i in validation.issues]},
                collector=self.collector,
            )
            symbol.mapping_status = MappingStatus.INVALID
            symbol.last_validated_at = self._now()
            symbol.save(update_fields=["mapping_status", "last_validated_at", "updated_at"])
            raise OTCFeedMismatchError(f"Invalid symbol mapping for {symbol}")
        symbol.mapping_status = MappingStatus.VALID
        symbol.last_validated_at = self._now()
        symbol.save(update_fields=["mapping_status", "last_validated_at", "updated_at"])

    def _record_validation_events(self, *, symbol, timeframe: str, issues) -> None:
        for issue in issues:
            record_health_event(
                kind=HealthKind.VALIDATION,
                severity=issue.severity,
                message=f"{timeframe}: {issue.message}",
                profile=self.profile,
                symbol=symbol,
                detail={"code": issue.code, **issue.context},
                collector=self.collector,
            )

    # -- operations ---------------------------------------------------------
    def sync_candles(self, symbol, timeframe: str, count: int):
        """Fetch and persist recent candles for a mapped symbol/timeframe."""
        log = self._start_log(SyncKind.CANDLES, symbol=symbol, timeframe=timeframe)
        counters = _LogCounters()
        try:
            self._guard_mapping(symbol)
            service = CandleService(self.client, now_fn=self._now)
            fetched = service.fetch(symbol.broker_symbol, timeframe, count, include_forming=True)
            batch = list(fetched.completed)
            if fetched.forming is not None:
                batch.append(fetched.forming)

            persisted = persist_candles(
                symbol,
                timeframe,
                batch,
                collector=self.collector,
                now=fetched.now,
            )
            counters.fetched = persisted.fetched
            counters.inserted = persisted.inserted
            counters.updated = persisted.updated
            counters.skipped = persisted.skipped
            counters.detail = {
                "completed": len(fetched.completed),
                "forming": 1 if fetched.forming is not None else 0,
                "quality": persisted.quality_status,
                "validation": persisted.summary,
            }
            if persisted.issues:
                self._record_validation_events(
                    symbol=symbol, timeframe=timeframe, issues=persisted.issues
                )

            status = SyncStatus.SUCCESS
            if persisted.fetched == 0:
                status = SyncStatus.PARTIAL
                record_health_event(
                    kind=HealthKind.STALE_DATA,
                    severity=Severity.WARNING,
                    message=f"No candles returned for {symbol.broker_symbol} {timeframe}.",
                    profile=self.profile,
                    symbol=symbol,
                    collector=self.collector,
                )
            elif persisted.quality_status == "invalid":
                status = SyncStatus.PARTIAL
            return self._finish_log(log, status=status, counters=counters)
        except MarketDataError as exc:
            logger.warning("market_data.sync_candles.failed", extra={"error": str(exc)})
            record_health_event(
                kind=HealthKind.CONNECTION,
                severity=Severity.ERROR,
                message=f"Candle sync failed: {exc}",
                profile=self.profile,
                symbol=symbol,
                collector=self.collector,
            )
            return self._finish_log(
                log, status=SyncStatus.FAILED, counters=counters, error_message=str(exc)
            )

    def sync_latest_tick(self, symbol):
        """Fetch and persist the latest tick for a mapped symbol."""
        log = self._start_log(SyncKind.TICKS, symbol=symbol)
        counters = _LogCounters()
        try:
            self._guard_mapping(symbol)
            service = TickService(self.client, now_fn=self._now)
            tick, issues = service.latest_with_validation(symbol.broker_symbol)
            if tick is None:
                counters.detail = {"tick": "none"}
                record_health_event(
                    kind=HealthKind.STALE_DATA,
                    severity=Severity.WARNING,
                    message=f"No tick returned for {symbol.broker_symbol}.",
                    profile=self.profile,
                    symbol=symbol,
                    collector=self.collector,
                )
                return self._finish_log(log, status=SyncStatus.PARTIAL, counters=counters)

            persisted = persist_ticks(symbol, [tick], collector=self.collector)
            counters.fetched = persisted.fetched
            counters.inserted = persisted.inserted
            counters.skipped = persisted.skipped
            counters.detail = {"issues": [i.code for i in issues]}
            if issues:
                self._record_validation_events(symbol=symbol, timeframe="", issues=issues)
            return self._finish_log(log, status=SyncStatus.SUCCESS, counters=counters)
        except MarketDataError as exc:
            record_health_event(
                kind=HealthKind.CONNECTION,
                severity=Severity.ERROR,
                message=f"Tick sync failed: {exc}",
                profile=self.profile,
                symbol=symbol,
                collector=self.collector,
            )
            return self._finish_log(
                log, status=SyncStatus.FAILED, counters=counters, error_message=str(exc)
            )

    def discover_symbols(self) -> list[str]:
        """List broker symbols available on the connected terminal."""
        return sorted(self.client.symbols_get())

    def sync_symbols(self) -> tuple:
        """Record a symbols sync log and return ``(log, symbols)``."""
        log = self._start_log(SyncKind.SYMBOLS)
        counters = _LogCounters()
        try:
            symbols = self.discover_symbols()
            counters.fetched = len(symbols)
            counters.detail = {"count": len(symbols)}
            return self._finish_log(log, status=SyncStatus.SUCCESS, counters=counters), symbols
        except MarketDataError as exc:
            return (
                self._finish_log(
                    log, status=SyncStatus.FAILED, counters=counters, error_message=str(exc)
                ),
                [],
            )


__all__ = ["MarketDataSyncService"]
