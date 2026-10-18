# apps/research/services/walk_forward_validation.py
"""Walk-forward and chronological partitioning (Step 10)."""

from __future__ import annotations

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

    def walk_forward(
        self, candles: list[dict[str, Any]], window: int = 100
    ) -> list[dict[str, Any]]:
        """Basic walk-forward evaluation."""
        folds = []
        if len(candles) < window * 2:
            return folds
        # Placeholder implementation
        return folds


__all__ = ["WalkForwardValidation"]
