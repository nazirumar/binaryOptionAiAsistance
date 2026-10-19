"""Deterministic book-strategy backtests + walk-forward + research ranking.

For every implemented strategy over real candles (MT5 rows or an imported
historical dataset) this command:

1. runs the causal replay validation (persisted as a ``BacktestRun``);
2. scores successive forward windows (walk-forward report);
3. advances ``research_status`` at most to ``backtested`` - never to
   ``oos_validated`` or ``approved`` (``--keep-status`` skips even that);
4. compares + ranks all strategies (rank = research order only; insufficient
   data stays UNRANKED) and persists a comparison ``BacktestRun``;
5. writes a JSON artifact with sample sizes, Wilson intervals and baselines.

Nothing here approves a strategy or invents performance: numbers only appear
when signals exist, and every report carries its own thresholds and warnings.

Usage:
    python manage.py backtest_book_strategies
    python manage.py backtest_book_strategies --dataset-id 3 --out docs/artifacts/book_research.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.book_strategies.constants import IMPLEMENTED_SPEC_KEYS, SPEC_BY_KEY
from apps.book_strategies.services.backtest import (
    COMPARISON_RUN_KIND,
    BookBacktestService,
)
from apps.book_strategies.services.comparison import BookComparisonService
from apps.book_strategies.services.sources import (
    dataset_candles,
    mt5_candle_groups,
    require_groups,
)
from apps.book_strategies.services.validation import (
    DEFAULT_BURN_IN,
    DEFAULT_MIN_SIGNALS,
    DEFAULT_PAYOUT_RATE,
    METRIC_SCOPE,
)
from apps.book_strategies.services.walk_forward import BookWalkForwardService
from apps.research.models import BacktestRun, HistoricalDataset


class Command(BaseCommand):
    help = "Causal backtests, walk-forward windows and research ranking for book strategies."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--symbol", default="", help="Canonical symbol (e.g. EURUSD).")
        parser.add_argument("--timeframe", default="", help="Timeframe (e.g. M1, M5).")
        parser.add_argument("--dataset-id", type=int, default=0,
                            help="Use an imported historical dataset instead of MT5 rows.")
        parser.add_argument("--window", type=int, default=60,
                            help="Walk-forward window size in candles.")
        parser.add_argument("--burn-in", type=int, default=DEFAULT_BURN_IN)
        parser.add_argument("--min-signals", type=int, default=DEFAULT_MIN_SIGNALS)
        parser.add_argument("--payout", type=float, default=DEFAULT_PAYOUT_RATE)
        parser.add_argument("--out", default="docs/artifacts/book_research.json")
        parser.add_argument("--keep-status", action="store_true",
                            help="Do not advance research_status to 'backtested'.")

    def handle(self, *args: object, **options: object) -> str:
        window = int(options["window"])
        burn_in = int(options["burn_in"])
        min_signals = int(options["min_signals"])
        dataset: HistoricalDataset | None = None

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

        backtester = BookBacktestService()
        walk_forward = BookWalkForwardService()
        entries: list[dict[str, Any]] = []
        lines: list[str] = []
        advanced: set[str] = set()

        for (instrument, timeframe), candles in sorted(groups.items()):
            for key in IMPLEMENTED_SPEC_KEYS:
                wf_report = walk_forward.run(
                    key,
                    candles,
                    window=window,
                    burn_in=burn_in,
                    min_signals=min_signals,
                    instrument=instrument,
                    timeframe=timeframe,
                )
                run = backtester.run(
                    key,
                    candles,
                    burn_in=burn_in,
                    payout_rate=float(options["payout"]),
                    instrument=instrument,
                    timeframe=timeframe,
                    dataset=dataset,
                    min_signals=min_signals,
                )
                validation_payload = run.results["validation"]
                entries.append(
                    {
                        "strategy_key": key,
                        "name": SPEC_BY_KEY[key].name,
                        "validation": validation_payload,
                        "walk_forward": wf_report.as_dict(),
                    }
                )
                pooled = validation_payload["splits"]["pooled"]
                wf_pooled = wf_report.pooled
                lines.append(
                    f"{key} {instrument}/{timeframe}: replay {pooled['n_signals']} signals "
                    f"(acc={pooled['accuracy']}), walk-forward {wf_pooled['n_signals']} signals "
                    f"(acc={wf_pooled['accuracy']}), sufficient={wf_report.sufficient_data}"
                )
                if not options["keep_status"]:
                    strategy = _strategy_row(key)
                    if strategy is not None and backtester.advance_research_status(strategy):
                        advanced.add(key)

        comparison = BookComparisonService().compare(entries)
        total_signals = sum(
            (entry["validation"]["splits"]["pooled"]["n_signals"]) for entry in entries
        )
        comparison_run = BacktestRun(
            name=f"book comparison ({len(entries)} runs)",
            status="completed",
            dataset=dataset,
            strategy_config={
                "kind": COMPARISON_RUN_KIND,
                "strategies": [entry["strategy_key"] for entry in entries],
            },
            results={"comparison": comparison.as_dict()},
            metrics={
                "metric_scope": METRIC_SCOPE,
                "ranked_count": comparison.ranked_count,
                "unranked_count": comparison.unranked_count,
                "sample_count": total_signals,
                "approved_for_decision_use": False,
            },
            sample_count=total_signals,
        )
        comparison_run.save()

        artifact = {
            "generated_by": "manage.py backtest_book_strategies",
            "metric_scope": METRIC_SCOPE,
            "min_signals_for_claim": min_signals,
            "walk_forward_window": window,
            "dataset": self._dataset_descriptor(dataset, groups),
            "ranking": comparison.as_dict(),
            "backtests": entries,
        }
        out_path = Path(str(options["out"]))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")

        for line in lines:
            self.stdout.write(line)
        self.stdout.write(
            f"ranking: {comparison.ranked_count} ranked, "
            f"{comparison.unranked_count} unranked (insufficient data)"
        )
        if advanced:
            self.stdout.write(f"research_status advanced to 'backtested': {', '.join(sorted(advanced))}")
        self.stdout.write(
            self.style.SUCCESS(
                f"persisted {len(entries)} backtest runs + 1 comparison run -> {out_path}"
            )
        )
        return f"{len(entries)} backtests, comparison {comparison_run.pk} -> {out_path}"

    @staticmethod
    def _dataset_descriptor(dataset: HistoricalDataset | None, groups: dict) -> dict[str, Any]:
        if dataset is not None:
            provenance = (dataset.metadata or {}).get("provenance", {})
            return {
                "kind": "historical_import",
                "dataset_id": dataset.pk,
                "name": dataset.name,
                "source": dataset.source,
                "source_sha256": provenance.get("source_sha256", ""),
                "candles": dataset.candle_count,
            }
        return {
            "kind": "mt5_rows",
            "groups": [
                {"instrument": instrument, "timeframe": timeframe, "candles": len(candles)}
                for (instrument, timeframe), candles in sorted(groups.items())
            ],
        }


def _strategy_row(key: str):
    from apps.book_strategies.models import BookStrategy

    return BookStrategy.objects.filter(key=key).first()
