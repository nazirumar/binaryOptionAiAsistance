"""Windows MT5 data collection worker.

Run this on a Windows host that has the MetaTrader 5 terminal and the
``MetaTrader5`` Python package installed::

    python manage.py mt5_worker --symbols EURUSD,XAUUSD --timeframes M1,M5

The worker connects to the terminal, collects candles and the latest tick for
each configured mapping, persists them idempotently (or pushes them to a remote
server with ``--push-url``), writes heartbeats and health events, reconnects on
failure with bounded backoff, and shuts down cleanly on Ctrl+C / SIGTERM.
"""

from __future__ import annotations

import logging
import os
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.market_data.constants import HealthKind, Severity, WorkerStatus
from apps.market_data.services.candle_service import CandleService
from apps.market_data.services.connection_manager import (
    ConnectionConfig,
    MT5ConnectionManager,
    mask_account,
)
from apps.market_data.services.exceptions import MarketDataError, SymbolMappingError
from apps.market_data.services.health import record_health_event, upsert_heartbeat
from apps.market_data.services.mt5_client import MetaTrader5Client
from apps.market_data.services.remote_ingest import RemoteIngestClient, RemoteIngestError
from apps.market_data.services.symbol_mapper import SymbolMapper
from apps.market_data.services.sync_service import MarketDataSyncService
from apps.market_data.services.tick_service import TickService
from apps.market_data.services.timeframe_mapper import is_supported

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the MetaTrader 5 data collection worker (Windows host only)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--interval", type=int, default=None, help="Seconds between cycles.")
        parser.add_argument(
            "--symbols", type=str, default="", help="Comma-separated canonical codes."
        )
        parser.add_argument(
            "--timeframes", type=str, default="", help="Comma-separated timeframes."
        )
        parser.add_argument("--count", type=int, default=300, help="Candles per symbol/timeframe.")
        parser.add_argument("--once", action="store_true", help="Run a single cycle and exit.")
        parser.add_argument("--collector", type=str, default="", help="Worker identifier.")
        parser.add_argument("--profile", type=int, default=None, help="MT5ConnectionProfile id.")
        parser.add_argument(
            "--push-url", type=str, default="", help="Remote server base URL (push mode)."
        )
        parser.add_argument(
            "--worker-token", type=str, default="", help="Worker token for push mode."
        )

    # -- setup --------------------------------------------------------------
    def _resolve_options(self, options):
        interval = options["interval"] or settings.MT5_WORKER_POLL_INTERVAL_SECONDS
        symbols = [
            s.strip().upper()
            for s in (options["symbols"] or ",".join(settings.MT5_CANDLE_SYNC_SYMBOLS)).split(",")
            if s.strip()
        ]
        timeframes = [
            t.strip().upper()
            for t in (options["timeframes"] or ",".join(settings.MT5_CANDLE_SYNC_TIMEFRAMES)).split(
                ","
            )
            if t.strip()
        ]
        unsupported = [t for t in timeframes if not is_supported(t)]
        if unsupported:
            raise CommandError(f"Unsupported timeframe(s): {', '.join(unsupported)}")
        collector = options["collector"] or f"worker-{os.getpid()}"
        return interval, symbols, timeframes, collector

    def _resolve_profile(self, profile_id):
        if not profile_id:
            return None
        from apps.market_data.models import MT5ConnectionProfile

        profile = MT5ConnectionProfile.objects.filter(pk=profile_id).first()
        if profile is None:
            raise CommandError(f"MT5ConnectionProfile {profile_id} not found.")
        return profile

    def _resolve_mappings(self, symbols, profile, collector):
        mappings = []
        for code in symbols:
            try:
                mappings.append(SymbolMapper.resolve(code, profile))
            except SymbolMappingError as exc:
                self.stderr.write(self.style.WARNING(str(exc)))
                record_health_event(
                    kind=HealthKind.MAPPING,
                    severity=Severity.WARNING,
                    message=str(exc),
                    profile=profile,
                    collector=collector,
                )
        return mappings

    # -- cycle --------------------------------------------------------------
    def _run_cycle_direct(self, service, mappings, timeframes, count):
        ok = True
        for symbol in mappings:
            for timeframe in timeframes:
                log = service.sync_candles(symbol, timeframe, count)
                if log.status not in {"success", "partial"}:
                    ok = False
            tick_log = service.sync_latest_tick(symbol)
            if tick_log.status not in {"success", "partial"}:
                ok = False
        return ok

    def _run_cycle_push(self, client, remote, mappings, timeframes, count, collector):
        candle_service = CandleService(client)
        tick_service = TickService(client)
        ok = True
        for symbol in mappings:
            for timeframe in timeframes:
                fetched = candle_service.fetch(symbol.broker_symbol, timeframe, count)
                batch = list(fetched.completed)
                if fetched.forming is not None:
                    batch.append(fetched.forming)
                if not batch:
                    continue
                try:
                    remote.ingest_candles(
                        canonical=symbol.canonical,
                        broker_symbol=symbol.broker_symbol,
                        is_otc=symbol.is_otc,
                        timeframe=timeframe,
                        candles=batch,
                        collector=collector,
                        profile_id=symbol.profile_id,
                    )
                except RemoteIngestError as exc:
                    logger.warning("mt5_worker.push.candles_failed", extra={"error": str(exc)})
                    ok = False
            tick = tick_service.fetch_latest(symbol.broker_symbol)
            if tick is not None:
                try:
                    remote.ingest_ticks(
                        canonical=symbol.canonical,
                        broker_symbol=symbol.broker_symbol,
                        is_otc=symbol.is_otc,
                        ticks=[tick],
                        collector=collector,
                        profile_id=symbol.profile_id,
                    )
                except RemoteIngestError as exc:
                    logger.warning("mt5_worker.push.ticks_failed", extra={"error": str(exc)})
                    ok = False
        return ok

    # -- main ---------------------------------------------------------------
    def handle(self, *args, **options) -> None:
        interval, symbols, timeframes, collector = self._resolve_options(options)
        profile = self._resolve_profile(options["profile"])
        config = (
            ConnectionConfig.from_profile(profile) if profile else ConnectionConfig.from_settings()
        )

        if not symbols:
            raise CommandError("No symbols configured. Pass --symbols or set MT5_SYNC_SYMBOLS.")

        mappings = self._resolve_mappings(symbols, profile, collector)
        if not mappings:
            raise CommandError(
                "No valid symbol mappings; create mappings before running the worker."
            )

        push_url = options["push_url"]
        token = options["worker_token"] or settings.MT5_WORKER_TOKEN
        remote = None
        if push_url:
            remote = RemoteIngestClient(push_url, token)

        self.stdout.write(
            self.style.NOTICE(
                f"MT5 worker '{collector}' starting: server={config.server or 'settings'} "
                f"account={mask_account(config.login) or 'settings'} "
                f"symbols={[m.canonical for m in mappings]} timeframes={timeframes} "
                f"mode={'push' if remote else 'direct'}"
            )
        )

        stop = {"flag": False}

        def _handle_signal(signum, frame) -> None:
            stop["flag"] = True
            logger.info("mt5_worker.shutdown_requested", extra={"signal": signum})

        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    signal.signal(sig, _handle_signal)
                except (ValueError, OSError):  # pragma: no cover - platform dependent
                    pass

        client = MetaTrader5Client()
        manager = MT5ConnectionManager(client, config)
        try:
            manager.connect()
        except MarketDataError as exc:
            record_health_event(
                kind=HealthKind.CONNECTION,
                severity=Severity.ERROR,
                message=f"Worker could not connect: {exc}",
                profile=profile,
                collector=collector,
            )
            raise CommandError(f"Could not connect to MT5: {exc}") from exc

        service = MarketDataSyncService(client, profile=profile, collector=collector)
        try:
            while not stop["flag"]:
                try:
                    manager.ensure_connected()
                except MarketDataError as exc:
                    record_health_event(
                        kind=HealthKind.DISCONNECT,
                        severity=Severity.ERROR,
                        message=f"Worker lost connection: {exc}",
                        profile=profile,
                        collector=collector,
                    )
                    upsert_heartbeat(
                        worker_id=collector, status=WorkerStatus.ERROR, detail={"error": str(exc)}
                    )
                    if options["once"]:
                        break
                    self._sleep(interval, stop)
                    continue

                if remote is not None:
                    ok = self._run_cycle_push(
                        client, remote, mappings, timeframes, options["count"], collector
                    )
                    try:
                        remote.heartbeat(
                            worker_id=collector,
                            status=WorkerStatus.ONLINE if ok else WorkerStatus.DEGRADED,
                            detail={
                                "symbols": [m.canonical for m in mappings],
                                "timeframes": timeframes,
                            },
                        )
                    except RemoteIngestError as exc:
                        logger.warning("mt5_worker.heartbeat_failed", extra={"error": str(exc)})
                else:
                    ok = self._run_cycle_direct(service, mappings, timeframes, options["count"])
                    upsert_heartbeat(
                        worker_id=collector,
                        status=WorkerStatus.ONLINE if ok else WorkerStatus.DEGRADED,
                        detail={
                            "symbols": [m.canonical for m in mappings],
                            "timeframes": timeframes,
                        },
                    )

                if options["once"]:
                    break
                self._sleep(interval, stop)
        finally:
            manager.disconnect()
            self.stdout.write(self.style.NOTICE("MT5 worker stopped."))

    def _sleep(self, interval: int, stop: dict) -> None:
        """Sleep in one-second slices so shutdown is responsive."""
        for _ in range(max(1, int(interval))):
            if stop["flag"]:
                return
            time.sleep(1)
