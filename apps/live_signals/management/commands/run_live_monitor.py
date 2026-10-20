# live_signals/management/commands/run_live_monitor.py
"""Run the live-signals monitor once from the command line (Phase 15).

Useful for smoke-testing the pipeline without a Celery beat worker:

    python manage.py run_live_monitor                 # all monitors
    python manage.py run_live_monitor --instrument EURUSD --timeframe M5
    python manage.py run_live_monitor --ensure-only   # create default monitors

Nothing here fabricates data: the command reports exactly what the configured
provider returned (including UNAVAILABLE feeds).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.live_signals.services.monitor import (
    LiveSignalMonitor,
    ensure_monitors,
)
from apps.live_signals.services.providers import get_provider


class Command(BaseCommand):
    help = "Run one pass of the live-signals monitor (closed-candle detection)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--instrument", default="", help="Canonical instrument filter.")
        parser.add_argument("--timeframe", default="", help="Timeframe filter (M1/M2/M3/M5/M15).")
        parser.add_argument(
            "--provider", default="db", help="Candle provider name (db|mt5)."
        )
        parser.add_argument(
            "--ensure-only",
            action="store_true",
            help="Only create the default monitors; do not evaluate.",
        )

    def handle(self, *args: object, **options: object) -> str:
        from django.conf import settings

        monitors = ensure_monitors()
        self.stdout.write(
            f"monitors: {len(monitors)} (from LIVE_SIGNAL_MONITORS="
            f"{getattr(settings, 'LIVE_SIGNAL_MONITORS', [])})"
        )
        if options["ensure_only"]:
            return "monitors ensured"

        instrument = options["instrument"]
        timeframe = options["timeframe"]
        engine = LiveSignalMonitor(provider=get_provider(options["provider"]))

        ran = 0
        for monitor in monitors:
            if instrument and monitor.canonical_instrument != instrument:
                continue
            if timeframe and monitor.timeframe != timeframe:
                continue
            result = engine.run_monitor(monitor)
            ran += 1
            self.stdout.write(
                f"  {result.instrument}/{result.timeframe}: feed={result.feed_state} "
                f"evaluated={result.evaluated} new={result.new_signals} "
                f"expired={result.expired} resolved={result.resolved} "
                f"({result.message})"
            )
        return f"ran {ran} monitor(s)"
