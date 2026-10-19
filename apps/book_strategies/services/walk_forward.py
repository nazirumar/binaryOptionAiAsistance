# book_strategies/services/walk_forward.py
"""Chronological walk-forward validation for book strategies (requirement 3).

Detectors are frozen: every rule comes from the book, nothing is fitted on
the data. Walk-forward therefore measures whether a frozen rule keeps working
in *successive future windows* instead of only in one favourable segment:

* signals come from the shared causal replay (``candles[0..i]`` only);
* the replay's signals are partitioned into chronological, non-overlapping
  test windows produced by ``WalkForwardValidation.chronological_folds``;
* each window and the pooled remainder are scored with sample size + Wilson
  95% interval and the unconditional majority baseline of the same window.

A pooled sample below the minimum-signal threshold yields
``sufficient_data=False`` with an explicit reason: no window is ever
presented as evidence just because it looked good.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.book_strategies.constants import SPEC_BY_KEY
from apps.book_strategies.services.validation import (
    DEFAULT_BURN_IN,
    DEFAULT_MIN_SIGNALS,
    DISCLAIMER,
    METRIC_SCOPE,
    BookValidationService,
    ReplaySignal,
    wilson_interval,
)
from apps.research.services.walk_forward_validation import WalkForwardValidation

WALK_FORWARD_DISCLAIMER = (
    f"{DISCLAIMER} Walk-forward windows are chronological and "
    "non-overlapping; detectors are frozen book rules (no fitting), so a "
    "forward window is an honest out-of-time check, not a tuned backtest."
)

LEAKAGE_CONTROL = (
    "every signal is produced by the causal replay over candles[0..i]; fold "
    "windows only partition time forward and are never shuffled"
)


@dataclass(slots=True)
class WalkForwardReport:
    strategy_key: str
    window: int
    step: int
    burn_in: int
    metric_scope: str = METRIC_SCOPE
    disclaimer: str = WALK_FORWARD_DISCLAIMER
    leakage_control: str = LEAKAGE_CONTROL
    dataset: dict[str, Any] = field(default_factory=dict)
    folds: list[dict[str, Any]] = field(default_factory=list)
    pooled: dict[str, Any] = field(default_factory=dict)
    sufficient_data: bool = False
    insufficient_reason: str | None = None
    baseline_rule: str = "unconditional majority direction of each forward window"
    approved_for_decision_use: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_key": self.strategy_key,
            "window": self.window,
            "step": self.step,
            "burn_in": self.burn_in,
            "metric_scope": self.metric_scope,
            "disclaimer": self.disclaimer,
            "leakage_control": self.leakage_control,
            "dataset": dict(self.dataset),
            "folds": [dict(fold) for fold in self.folds],
            "pooled": dict(self.pooled),
            "sufficient_data": self.sufficient_data,
            "insufficient_reason": self.insufficient_reason,
            "baseline_rule": self.baseline_rule,
            "approved_for_decision_use": False,
        }


class BookWalkForwardService:
    """Score one strategy over successive forward windows."""

    def __init__(
        self,
        validation: BookValidationService | None = None,
        folds_engine: WalkForwardValidation | None = None,
    ) -> None:
        self.validation = validation or BookValidationService()
        self.folds_engine = folds_engine or WalkForwardValidation()

    def run(
        self,
        key: str,
        candles: list[dict[str, Any]],
        *,
        window: int = 60,
        step: int | None = None,
        burn_in: int = DEFAULT_BURN_IN,
        min_signals: int = DEFAULT_MIN_SIGNALS,
        instrument: str = "",
        timeframe: str = "",
    ) -> WalkForwardReport:
        spec = SPEC_BY_KEY.get(key)
        if spec is None:
            raise KeyError(f"unknown book strategy key: {key!r}")

        step = window if step is None else step
        # One causal replay: identical prefix semantics as validation, so the
        # forward windows can never contain a signal computed with its outcome.
        signals = self.validation.replay(key, candles, burn_in=burn_in)
        folds = self.folds_engine.chronological_folds(
            len(candles), window=window, step=step, burn_in=burn_in
        )

        fold_reports: list[dict[str, Any]] = []
        pooled_signals: list[ReplaySignal] = []
        pooled_indices: set[int] = set()
        for fold in folds:
            in_window = [s for s in signals if fold["start"] <= s.index < fold["end"]]
            pooled_signals.extend(in_window)
            window_indices = list(range(fold["start"], fold["end"]))
            pooled_indices.update(window_indices)
            fold_reports.append(
                {
                    "fold": fold["fold"],
                    "start": fold["start"],
                    "end": fold["end"],
                    **self._stats(in_window, candles, window_indices),
                }
            )

        pooled_stats = self._stats(
            pooled_signals, candles, sorted(pooled_indices)
        )
        pooled_stats["direction_counts"] = {
            "bullish": sum(1 for s in pooled_signals if s.direction == "bullish"),
            "bearish": sum(1 for s in pooled_signals if s.direction == "bearish"),
        }
        pooled_stats["folds_scored"] = len(folds)

        report = WalkForwardReport(
            strategy_key=key,
            window=window,
            step=step,
            burn_in=burn_in,
            dataset={
                "n_candles": len(candles),
                "instrument": instrument,
                "timeframe": timeframe,
            },
            folds=fold_reports,
            pooled=pooled_stats,
            insufficient_reason=None,
        )
        if not folds:
            report.sufficient_data = False
            report.insufficient_reason = (
                f"series too short for walk-forward windows "
                f"({len(candles)} candles, burn-in {burn_in}, window {window})"
            )
        elif not pooled_signals:
            report.sufficient_data = False
            report.insufficient_reason = (
                "no completed pattern signals occurred in any forward window - "
                "no accuracy can be computed (and none is invented)"
            )
        elif pooled_stats["n_signals"] < min_signals:
            report.sufficient_data = False
            report.insufficient_reason = (
                f"only {pooled_stats['n_signals']} signals across {len(folds)} "
                f"forward windows; below the {min_signals}-signal threshold "
                "for validation claims"
            )
        else:
            report.sufficient_data = True
        return report

    @staticmethod
    def _stats(
        items: list[ReplaySignal],
        candles: list[dict[str, Any]],
        indices: list[int],
    ) -> dict[str, Any]:
        total = len(items)
        correct = sum(1 for s in items if s.correct)
        accuracy = (correct / total) if total else None
        lo, hi = wilson_interval(correct, total)
        ups = sum(
            1
            for i in indices
            if i + 1 < len(candles)
            and float(candles[i + 1]["close"]) > float(candles[i]["close"])
        )
        n_outcomes = len(indices)
        majority = max(ups, n_outcomes - ups) if n_outcomes else 0
        return {
            "n_signals": total,
            "n_correct": correct,
            "accuracy": accuracy,
            "wilson_95": [lo, hi],
            "n_outcome_candles": n_outcomes,
            "baseline_accuracy": (majority / n_outcomes) if n_outcomes else None,
        }


__all__ = ["WALK_FORWARD_DISCLAIMER", "BookWalkForwardService", "WalkForwardReport"]
