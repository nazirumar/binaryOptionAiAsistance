"""Resolve paper predictions from the next completed candle (Phase 13).

For every pending prediction whose outcome candle (opening exactly when the
signal candle closes) is present and COMPLETE in the supplied data, the
outcome is recorded once: next-candle close direction vs. the signal close.
Forming candles, missing windows and off-by-one windows resolve nothing.

Resolution is next-candle direction - not binary settlement. Settlement needs
platform quotes and is evaluated separately (services/settlement.py).

Usage:
    python manage.py resolve_paper_predictions --symbol EURUSD --timeframe M5
    python manage.py resolve_paper_predictions --dataset-id 3
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.book_strategies.services.paper_forward import PaperForwardService
from apps.book_strategies.services.sources import (
    dataset_candles,
    mt5_candle_groups,
    require_groups,
)


class Command(BaseCommand):
    help = "Resolve pending paper predictions from completed outcome candles."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--symbol", default="")
        parser.add_argument("--timeframe", default="")
        parser.add_argument("--dataset-id", type=int, default=0)

    def handle(self, *args: object, **options: object) -> str:
        service = PaperForwardService()
        dataset = None
        if int(options["dataset_id"] or 0):
            try:
                dataset, loaded = dataset_candles(int(options["dataset_id"]))
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            groups = {
                (dataset.instrument or "imported", dataset.timeframe or "M1"): loaded
            }
        else:
            groups = mt5_candle_groups(
                symbol=str(options["symbol"] or ""),
                timeframe=str(options["timeframe"] or ""),
            )
            try:
                require_groups(groups)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc

        total = 0
        lines: list[str] = []
        for (instrument, timeframe), candles in sorted(groups.items()):
            # Same source label record() used: one feed's candles can only
            # resolve predictions recorded from that feed.
            source = (
                f"historical_import:{dataset.name}"
                if dataset is not None
                else f"mt5:{instrument}:{timeframe}"
            )
            resolved = service.resolve(
                candles,
                instrument=instrument,
                timeframe=timeframe,
                source=source,
            )
            total += len(resolved)
            for prediction in resolved:
                lines.append(
                    f"resolved {prediction.strategy.key} {prediction.direction} "
                    f"signal {prediction.signal_candle_open_time:%Y-%m-%d %H:%M}: "
                    f"outcome {'UP' if prediction.outcome_up else 'DOWN'}, "
                    f"correct={prediction.outcome_correct}"
                )

        for line in lines:
            self.stdout.write(line)
        self.stdout.write(self.style.SUCCESS(f"resolved {total} prediction(s)"))
        return f"resolved {total}"
