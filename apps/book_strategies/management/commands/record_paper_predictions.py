"""Record paper forward predictions from closed candles (Phase 13, requirement 8).

Creates at most one immutable pre-outcome prediction per
(strategy, signal candle) for recognition-enabled strategies whose detector
confirms a pattern exactly on the latest CLOSED candle. The prediction is
hashed (sha256) and frozen at creation; the outcome candle is resolved later
by ``resolve_paper_predictions``.

These records are research only: recording never changes research_status or
decision_use_approved.

Usage:
    python manage.py record_paper_predictions --symbol EURUSD --timeframe M5
    python manage.py record_paper_predictions --dataset-id 3
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.book_strategies.models import BookStrategy, PaperForwardPrediction
from apps.book_strategies.services.paper_forward import PaperForwardService
from apps.book_strategies.services.sources import (
    dataset_candles,
    mt5_candle_groups,
    require_groups,
)


class Command(BaseCommand):
    help = "Record immutable pre-outcome paper predictions from closed candles."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--symbol", default="")
        parser.add_argument("--timeframe", default="")
        parser.add_argument("--dataset-id", type=int, default=0)
        parser.add_argument("--market-type", dest="market_type", default="regular")

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

        enabled = BookStrategy.objects.filter(recognition_enabled=True).exclude(detector_key="")
        if not enabled.exists():
            self.stdout.write(
                "no strategies have recognition enabled - nothing recorded "
                "(enable recognition on the dashboard; this never approves trading)"
            )

        total = 0
        lines: list[str] = []
        for (instrument, timeframe), candles in sorted(groups.items()):
            source = (
                f"historical_import:{dataset.name}"
                if dataset is not None
                else f"mt5:{instrument}:{timeframe}"
            )
            created = service.record(
                candles,
                instrument=instrument,
                timeframe=timeframe,
                market_type=str(options["market_type"] or ""),
                source=source,
                last_candle_closed=True,
            )
            total += len(created)
            for prediction in created:
                lines.append(
                    f"recorded {prediction.strategy.key} {prediction.direction} "
                    f"{prediction.instrument}/{prediction.timeframe} signal "
                    f"{prediction.signal_candle_open_time:%Y-%m-%d %H:%M} "
                    f"sha256={prediction.payload_sha256[:12]}..."
                )

        for line in lines:
            self.stdout.write(line)
        pending = PaperForwardPrediction.objects.filter(status=PaperForwardPrediction.PENDING).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"recorded {total} new prediction(s); {pending} pending resolution"
            )
        )
        return f"recorded {total} predictions ({pending} pending)"
