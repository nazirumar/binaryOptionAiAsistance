"""Optional live MT5 integration check.

This command talks to a **real** MetaTrader 5 terminal. It is intentionally not
part of the automated test suite. Run it manually on a Windows host::

    python manage.py mt5_integration_check --symbols EURUSD --timeframes M1

It prints ``SKIPPED`` and exits 0 when no terminal/credentials are configured, so
it will not fail CI.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.market_data.services.candle_service import CandleService
from apps.market_data.services.connection_manager import ConnectionConfig, MT5ConnectionManager
from apps.market_data.services.exceptions import MarketDataError
from apps.market_data.services.mt5_client import MetaTrader5Client
from apps.market_data.services.symbol_mapper import SymbolMapper


class Command(BaseCommand):
    help = "Connect to a real MT5 terminal and verify candle retrieval (manual)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--symbols", type=str, default="")
        parser.add_argument("--timeframes", type=str, default="")

    def handle(self, *args, **options) -> None:
        config = ConnectionConfig.from_settings()
        configured = bool(config.server and config.login) or bool(config.path)
        if not configured:
            self.stdout.write(
                self.style.WARNING(
                    "SKIPPED: set MT5_SERVER/MT5_LOGIN/MT5_PASSWORD (or MT5_PATH) to run a live check."
                )
            )
            return

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

        client = MetaTrader5Client()
        manager = MT5ConnectionManager(client, config)
        try:
            manager.connect()
        except MarketDataError as exc:
            self.stderr.write(self.style.ERROR(f"FAILED to connect: {exc}"))
            raise SystemExit(1) from exc

        try:
            health = manager.health_check()
            self.stdout.write(
                f"Connected: server={health.server!r} account={health.masked_login!r} "
                f"build={health.build} company={health.company!r} connected={health.connected}"
            )
            service = CandleService(client)
            for code in symbols:
                try:
                    symbol = SymbolMapper.resolve(code, None)
                except MarketDataError as exc:
                    self.stderr.write(self.style.WARNING(f"{code}: {exc}"))
                    continue
                for timeframe in timeframes:
                    result = service.fetch(symbol.broker_symbol, timeframe, count=10)
                    latest = result.completed[-1] if result.completed else None
                    forming = "yes" if result.forming is not None else "no"
                    self.stdout.write(
                        f"{symbol.broker_symbol} {timeframe}: {len(result.completed)} completed, "
                        f"forming={forming}, last={latest.close if latest else '-'}"
                    )
        finally:
            manager.disconnect()
        self.stdout.write(self.style.SUCCESS("Integration check finished."))
