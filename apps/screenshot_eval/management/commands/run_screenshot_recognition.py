# screenshot_eval/management/commands/run_screenshot_recognition.py
"""Run recognition over stored screenshot cases (Checkpoint 2).

Without ``--candles`` the run records the vision-mapper candidates only (the
screenshot is qualitative). With ``--symbol``/``--timeframe`` the command loads
compatible stored MT5 candles (complete, quality-ok) and runs the deterministic
detectors too. Nothing is fabricated when candles are absent.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.book_strategies.services.sources import mt5_candle_groups
from apps.screenshot_eval.models import ScreenshotCase
from apps.screenshot_eval.services.recognition import ScreenshotRecognitionService


class Command(BaseCommand):
    help = "Run Phase 14 screenshot recognition over stored cases."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--case-id", type=int, default=None)
        parser.add_argument("--all-cases", action="store_true")
        parser.add_argument("--symbol", default="", help="MT5 canonical symbol for OHLC.")
        parser.add_argument("--timeframe", default="", help="Timeframe for OHLC.")

    def handle(self, *args, **options) -> None:
        if options["case_id"]:
            case = ScreenshotCase.objects.filter(pk=options["case_id"]).first()
            if case is None:
                raise CommandError(f"case {options['case_id']} not found")
            cases = [case]
        elif options["all_cases"]:
            cases = list(ScreenshotCase.objects.order_by("pk"))
        else:
            raise CommandError("choose --case-id or --all-cases")

        candles = None
        data_source = ""
        feed_market_type = ""
        if options["symbol"] and options["timeframe"]:
            groups = mt5_candle_groups(
                symbol=options["symbol"], timeframe=options["timeframe"]
            )
            key = (options["symbol"], options["timeframe"])
            candles = groups.get(key)
            if not candles:
                raise CommandError(
                    f"no complete quality-ok candles for {key}; nothing is fabricated"
                )
            data_source = f"mt5:{options['symbol']}:{options['timeframe']}"
            feed_market_type = "regular"

        service = ScreenshotRecognitionService()
        for case in cases:
            outcome = service.run(
                case=case,
                owner=case.owner,
                candles=candles,
                data_source=data_source,
                feed_market_type=feed_market_type,
            )
            self.stdout.write(
                f"case #{case.pk} {case.label}: run #{outcome.run.pk} "
                f"recognitions={len(outcome.recognitions)} ohlc={bool(candles)}"
            )
        self.stdout.write(self.style.SUCCESS(f"ran recognition over {len(cases)} case(s)"))
