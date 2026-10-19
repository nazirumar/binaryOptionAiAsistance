# apps/research/services/walk_forward_validation.py
"""Walk-forward and chronological partitioning (Step 10, Phase 13 requirement 3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class WalkForwardValidation:
    """Chronological train/val/test splitting with no random shuffling."""

    def split_chronological(
        self,
        candles: list[dict[str, Any]],
        train_frac: float = 0.6,
        val_frac: float = 0.2,
    ) -> dict[str, Any]:
        if not candles:
            return {"train": [], "val": [], "test": []}
        n = len(candles)
        train_end = int(n * train_frac)
        val_end = int(n * (train_frac + val_frac))
        return {
            "train": candles[:train_end],
            "val": candles[train_end:val_end],
            "test": candles[val_end:],
            "note": "Chronological split; no random shuffling; no overlapping prediction horizons across partitions",
        }

    def chronological_folds(
        self,
        n: int,
        *,
        window: int,
        step: int | None = None,
        burn_in: int = 0,
    ) -> list[dict[str, int]]:
        """Rolling forward test windows over ``range(burn_in, n)``.

        Each fold is a half-open index interval ``[start, end)`` whose
        outcomes (``i + 1``) stay inside the fold and inside the series
        (``end <= n - 1``). Folds advance chronologically with ``step``
        (default: ``window`` -> non-overlapping). Nothing is shuffled and no
        fold ever reaches into the future of a later fold.
        """
        if n < 2 or window < 2 or burn_in < 0 or burn_in >= n - 1:
            return []
        step = window if step is None else max(1, step)
        folds: list[dict[str, int]] = []
        start = max(burn_in, 0)
        index = 0
        while start < n - 1:
            end = min(start + window, n - 1)
            if end > start:
                folds.append({"fold": index, "start": start, "end": end})
                index += 1
            start += step
        return folds

    def walk_forward(
        self,
        candles: list[dict[str, Any]],
        window: int = 100,
        *,
        step: int | None = None,
        burn_in: int = 0,
        signal_fn: Callable[[list[dict[str, Any]], int], dict[str, Any] | None] | None = None,
    ) -> list[dict[str, Any]]:
        """Evaluate successive forward windows with a causal signal function.

        ``signal_fn(prefix, i)`` receives ONLY ``candles[0..i]`` - never the
        outcome candle - and returns an optional record (or ``None``). With no
        ``signal_fn`` the fold boundaries alone are returned: this method
        never invents metrics it did not compute.
        """
        folds = self.chronological_folds(len(candles), window=window, step=step, burn_in=burn_in)
        if signal_fn is None:
            return [dict(fold) for fold in folds]
        evaluated: list[dict[str, Any]] = []
        for fold in folds:
            signals: list[dict[str, Any]] = []
            for i in range(fold["start"], fold["end"]):
                record = signal_fn(candles[: i + 1], i)
                if record is not None:
                    signals.append(record)
            evaluated.append({**fold, "signals": signals})
        return evaluated


__all__ = ["WalkForwardValidation"]
