# book_strategies/services/validation.py
"""Honest validation machinery for book strategies (Step 6).

Design rules, enforced by tests:

- **No future leakage**: the signal at index ``i`` is computed by running the
  detector on ``candles[0..i]`` ONLY; the outcome is the candle ``i+1``. The
  property test asserts replay[i] == standalone detector on the prefix.
- **Chronological out-of-sample split**: the evaluation window is split in
  time; later indices form the OOS set. No shuffling, ever.
- **Next-candle direction != settlement**: metrics measure the direction of the
  following candle's close, not binary-option settlement. A payout expectancy,
  when shown, is labelled hypothetical and uses the caller's payout assumption.
- **No fabricated numbers**: accuracy is ``None`` (and ``sufficient_data`` is
  False) when there are no signals; recall-style statistics are never invented;
  every reported rate carries its sample size and a Wilson 95% interval.
- **Baseline comparison**: every report includes the unconditional majority
  baseline over the same window, so accuracy is never shown in isolation.

Nothing here approves a strategy for live decisions - approval is a separate,
explicit human step (``decision_use_approved``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from apps.book_strategies.constants import SPEC_BY_KEY, BookPatternState
from apps.book_strategies.services.detectors import BOOK_DETECTORS

#: First index evaluated in a replay (covers the longest seed + indicators).
DEFAULT_BURN_IN = 20
#: Signals below this per pooled sample are labelled insufficient for claims.
DEFAULT_MIN_SIGNALS = 30
#: Default payout assumption used ONLY for the clearly-labelled hypothetical
#: expectancy line - never presented as a measured return.
DEFAULT_PAYOUT_RATE = 0.80

METRIC_SCOPE = "next_candle_direction"
DISCLAIMER = (
    "Metric scope is the direction of the NEXT candle's close, measured by "
    "chronological replay without future leakage. This is NOT binary-option "
    "settlement and not a win rate for real trades; slippage, expiry timing, "
    "payout and spread are not modelled."
)


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """Wilson score 95% interval; ``None`` bounds when there are no trials."""
    if trials <= 0:
        return None, None
    p = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    margin = (z / denominator) * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return max(centre - margin, 0.0), min(centre + margin, 1.0)


@dataclass(slots=True)
class ReplaySignal:
    """One completed pattern observed during a chronological replay."""

    index: int
    direction: str
    completed_at: int
    outcome_up: bool
    correct: bool
    state: str


@dataclass(slots=True)
class BookValidationReport:
    strategy_key: str
    dataset: dict[str, Any] = field(default_factory=dict)
    burn_in: int = DEFAULT_BURN_IN
    oos_fraction: float = 0.3
    metric_scope: str = METRIC_SCOPE
    disclaimer: str = DISCLAIMER
    leakage_control: str = (
        "signal at index i computed only from candles[0..i]; outcome taken "
        "from candle i+1"
    )
    splits: dict[str, Any] = field(default_factory=dict)
    sufficient_data: bool = False
    insufficient_reason: str | None = None
    hypothetical_payout_rate: float = DEFAULT_PAYOUT_RATE
    hypothetical_expectancy_per_trade: float | None = None
    baseline_rule: str = "unconditional majority direction of the window"
    signals: list[ReplaySignal] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_key": self.strategy_key,
            "dataset": dict(self.dataset),
            "burn_in": self.burn_in,
            "oos_fraction": self.oos_fraction,
            "metric_scope": self.metric_scope,
            "disclaimer": self.disclaimer,
            "leakage_control": self.leakage_control,
            "splits": {k: dict(v) for k, v in self.splits.items()},
            "sufficient_data": self.sufficient_data,
            "insufficient_reason": self.insufficient_reason,
            "hypothetical_payout_rate": self.hypothetical_payout_rate,
            "hypothetical_expectancy_per_trade": self.hypothetical_expectancy_per_trade,
            "baseline_rule": self.baseline_rule,
            "approved_for_decision_use": False,
        }


class BookValidationService:
    """Chronological replay + in/out-of-sample evaluation of one strategy."""

    def replay(
        self,
        key: str,
        candles: list[dict[str, Any]],
        *,
        burn_in: int = DEFAULT_BURN_IN,
    ) -> list[ReplaySignal]:
        """Run the detector forward through time; return completed signals.

        ``signals[i].completed_at == i`` means the pattern completed exactly on
        closed candle ``i`` - the replay equivalent of "you would have seen it
        here", with no knowledge of candle ``i+1`` or later.
        """
        spec = SPEC_BY_KEY.get(key)
        if spec is None:
            raise KeyError(f"unknown book strategy key: {key!r}")
        detector = BOOK_DETECTORS.get(spec.detector_key) if spec.detector_key else None
        if detector is None:
            return []

        signals: list[ReplaySignal] = []
        # i+1 must exist to score the outcome, so the last scorable index is n-2.
        for i in range(burn_in, len(candles) - 1):
            prefix = candles[: i + 1]
            result = detector(prefix)
            if result.state != BookPatternState.CONFIRMED_PATTERN:
                continue
            if result.completed_at is None or result.completed_at != i:
                # Pattern completed earlier (stale) - not a fresh signal here.
                continue
            if result.direction not in ("bullish", "bearish"):
                continue
            outcome_up = float(candles[i + 1]["close"]) > float(candles[i]["close"])
            correct = (result.direction == "bullish" and outcome_up) or (
                result.direction == "bearish" and not outcome_up
            )
            signals.append(
                ReplaySignal(
                    index=i,
                    direction=result.direction,
                    completed_at=i,
                    outcome_up=outcome_up,
                    correct=correct,
                    state=result.state,
                )
            )
        return signals

    def validate(
        self,
        key: str,
        candles: list[dict[str, Any]],
        *,
        burn_in: int = DEFAULT_BURN_IN,
        oos_fraction: float = 0.3,
        min_signals: int = DEFAULT_MIN_SIGNALS,
        payout_rate: float = DEFAULT_PAYOUT_RATE,
        instrument: str = "",
        timeframe: str = "",
    ) -> BookValidationReport:
        signals = self.replay(key, candles, burn_in=burn_in)
        n = len(candles)
        eval_start = min(burn_in, max(n - 1, 0))
        eval_indices = range(eval_start, max(n - 1, eval_start))  # outcome window
        split_at = eval_start + int((max(n - 1, eval_start) - eval_start) * (1.0 - oos_fraction))

        def window_stats(indices: range | list[int]) -> dict[str, Any]:
            idx = list(indices)
            ups = sum(1 for i in idx if float(candles[i + 1]["close"]) > float(candles[i]["close"]))
            total = len(idx)
            majority = max(ups, total - ups) if total else 0
            return {
                "n_outcome_candles": total,
                "baseline_accuracy": (majority / total) if total else None,
                "baseline_up_count": ups,
            }

        def signal_stats(items: list[ReplaySignal]) -> dict[str, Any]:
            total = len(items)
            correct = sum(1 for s in items if s.correct)
            accuracy = (correct / total) if total else None
            lo, hi = wilson_interval(correct, total)
            return {
                "n_signals": total,
                "n_correct": correct,
                "accuracy": accuracy,
                "wilson_95": [lo, hi],
            }

        in_sample_signals = [s for s in signals if s.index < split_at]
        oos_signals = [s for s in signals if s.index >= split_at]
        in_sample_window = range(eval_start, max(split_at - 1, eval_start))
        oos_window = range(max(split_at - 1, eval_start), max(n - 1, eval_start))

        report = BookValidationReport(
            strategy_key=key,
            dataset={
                "n_candles": n,
                "instrument": instrument,
                "timeframe": timeframe,
                "evaluation_start_index": eval_start,
                "split_index": split_at,
            },
            burn_in=burn_in,
            oos_fraction=oos_fraction,
            hypothetical_payout_rate=payout_rate,
            signals=signals,
        )
        report.splits = {
            "in_sample": {**window_stats(in_sample_window), **signal_stats(in_sample_signals)},
            "out_of_sample": {**window_stats(oos_window), **signal_stats(oos_signals)},
            "pooled": {
                **window_stats(eval_indices),
                **signal_stats(signals),
                "direction_counts": {
                    "bullish": sum(1 for s in signals if s.direction == "bullish"),
                    "bearish": sum(1 for s in signals if s.direction == "bearish"),
                },
            },
        }

        pooled_accuracy = report.splits["pooled"]["accuracy"]
        oos_n = report.splits["out_of_sample"]["n_signals"]
        if not signals:
            report.sufficient_data = False
            report.insufficient_reason = (
                "no completed pattern signals occurred in this candle series - "
                "no accuracy can be computed (and none is invented)"
            )
        elif len(signals) < min_signals or oos_n < max(min_signals // 3, 1):
            report.sufficient_data = False
            report.insufficient_reason = (
                f"only {len(signals)} pooled signals ({oos_n} out-of-sample); "
                f"below the {min_signals}-signal threshold for validation claims"
            )
        else:
            report.sufficient_data = True

        if report.sufficient_data and pooled_accuracy is not None:
            p = pooled_accuracy
            report.hypothetical_expectancy_per_trade = p * payout_rate - (1.0 - p)
        else:
            report.hypothetical_expectancy_per_trade = None
        return report
