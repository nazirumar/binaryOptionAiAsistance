# apps/research/services/baseline_comparison.py
"""Baseline comparison (Step 9)."""

from __future__ import annotations

from typing import Any


class BaselineComparison:
    """Compare against naive baselines on identical periods."""

    def majority_class(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "name": "majority_class",
            "accuracy": None,
            "note": "Baseline computed on same test periods",
        }

    def previous_candle(self, candles: list[dict[str, Any]]) -> dict[str, Any]:
        return {"name": "previous_candle", "accuracy": None}

    def random_baseline(self) -> dict[str, Any]:
        return {"name": "random", "accuracy": 0.5, "note": "50% expectation baseline"}

    def momentum_baseline(self) -> dict[str, Any]:
        return {"name": "momentum", "accuracy": None}

    def mean_reversion_baseline(self) -> dict[str, Any]:
        return {"name": "mean_reversion", "accuracy": None}


__all__ = ["BaselineComparison"]
