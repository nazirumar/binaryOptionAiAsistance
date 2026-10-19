# book_strategies/services/backtest.py
"""Deterministic candle-by-candle backtesting (Phase 13, requirement 2).

A backtest here is exactly one thing: the shared causal replay (signal at
index ``i`` computed only from ``candles[0..i]``, outcome from candle ``i+1``)
persisted as a ``BacktestRun`` so research results are reproducible records
instead of numbers living only in a log line.

Honesty rules enforced by tests:

* **Deterministic**: the same candles + config produce byte-identical
  ``results`` and ``metrics``; nothing depends on wall-clock, randomness or
  dict ordering.
* **No future leakage**: results come from ``BookValidationService.replay``,
  whose prefix property is asserted by the no-leakage tests.
* **Never approves**: a run records ``approved_for_decision_use: False`` and
  can never set ``decision_use_approved`` or skip research stages.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from apps.book_strategies.constants import SPEC_BY_KEY, ResearchStatus
from apps.book_strategies.services.validation import (
    DEFAULT_BURN_IN,
    DEFAULT_MIN_SIGNALS,
    DEFAULT_PAYOUT_RATE,
    METRIC_SCOPE,
    BookValidationService,
)
from apps.research.models import BacktestRun, HistoricalDataset

#: ``BacktestRun.strategy_config["kind"]`` for single-strategy runs.
BOOK_RUN_KIND = "book_strategy"
#: ``BacktestRun.strategy_config["kind"]`` for the comparison ranking run.
COMPARISON_RUN_KIND = "book_comparison"

#: Research stages a completed backtest may advance a strategy to - never
#: ``oos_validated`` or ``approved``: those require separate, explicit stages.
BACKTESTABLE_STATUSES = (
    ResearchStatus.EXTRACTED,
    ResearchStatus.IMPLEMENTED,
    ResearchStatus.RECOGNITION_TESTED,
)


class BookBacktestService:
    """Run and persist one deterministic backtest for one book strategy."""

    def __init__(self, validation: BookValidationService | None = None) -> None:
        self.validation = validation or BookValidationService()

    def run(
        self,
        key: str,
        candles: list[dict[str, Any]],
        *,
        burn_in: int = DEFAULT_BURN_IN,
        oos_fraction: float = 0.3,
        payout_rate: float = DEFAULT_PAYOUT_RATE,
        instrument: str = "",
        timeframe: str = "",
        dataset: HistoricalDataset | None = None,
        owner=None,
        min_signals: int = DEFAULT_MIN_SIGNALS,
    ) -> BacktestRun:
        """Backtest ``key`` over ``candles`` and persist the run."""
        spec = SPEC_BY_KEY.get(key)
        if spec is None or not spec.detector_key:
            raise KeyError(f"{key!r} has no registered detector to backtest")

        report = self.validation.validate(
            key,
            candles,
            burn_in=burn_in,
            oos_fraction=oos_fraction,
            payout_rate=payout_rate,
            instrument=instrument,
            timeframe=timeframe,
            min_signals=min_signals,
        )
        payload = report.as_dict()
        payload["signals"] = [asdict(signal) for signal in report.signals]
        payload["dataset"]["detector_key"] = spec.detector_key

        run = BacktestRun(
            name=f"book:{key} {instrument}/{timeframe}".strip(),
            status="completed",
            dataset=dataset,
            owner=owner,
            strategy_config={
                "kind": BOOK_RUN_KIND,
                "strategy_key": key,
                "detector_key": spec.detector_key,
                "burn_in": burn_in,
                "oos_fraction": oos_fraction,
                "min_signals": min_signals,
            },
            results={
                "validation": payload,
                "determinism": (
                    "pure detector functions over candle prefixes; identical "
                    "input yields identical results"
                ),
                "leakage_control": report.leakage_control,
            },
            metrics=self._metrics(payload),
            sample_count=len(report.signals),
        )
        run.save()
        return run

    @staticmethod
    def _metrics(payload: dict[str, Any]) -> dict[str, Any]:
        pooled = payload["splits"]["pooled"]
        return {
            "metric_scope": METRIC_SCOPE,
            "splits": payload["splits"],
            "sufficient_data": payload["sufficient_data"],
            "insufficient_reason": payload["insufficient_reason"],
            "accuracy_status": "measured" if pooled["n_signals"] else "no_signals",
            "approved_for_decision_use": False,
        }

    @staticmethod
    def advance_research_status(strategy) -> bool:
        """Record that a real backtest exists - and nothing beyond that.

        Moves the row at most to ``backtested``; ``oos_validated`` and
        ``approved`` are never set here (they require their own completed
        evidence plus an explicit human decision).
        """
        if strategy.detector_key and strategy.research_status in BACKTESTABLE_STATUSES:
            strategy.research_status = ResearchStatus.BACKTESTED
            strategy.save(update_fields=["research_status", "updated_at"])
            return True
        return False


__all__ = ["BOOK_RUN_KIND", "COMPARISON_RUN_KIND", "BookBacktestService"]
