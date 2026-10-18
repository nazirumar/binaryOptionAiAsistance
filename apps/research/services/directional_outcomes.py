# apps/research/services/directional_outcomes.py
"""Directional outcomes (Step 6)."""

from __future__ import annotations

from typing import Any


class DirectionalOutcomes:
    """Determine next-candle directional outcomes with explicit doji/tie policy.

    Do not silently classify doji as win.
    """

    def classify_target(self, target_candle: dict[str, Any]) -> str:
        """Classify target candle as UP/DOWN/TIE/UNCERTAIN."""
        if not target_candle:
            return "UNCERTAIN"
        open_p = float(target_candle.get("open", 0))
        close_p = float(target_candle.get("close", 0))
        high_p = float(target_candle.get("high", 0))
        low_p = float(target_candle.get("low", 0))
        if high_p - low_p == 0:
            return "TIE"
        # Doji classification - small body
        rng = high_p - low_p
        body = abs(close_p - open_p)
        if body / rng < 0.1 if rng > 0 else True:
            return "TIE"  # treat doji as tie per policy
        if close_p > open_p:
            return "UP"
        if close_p < open_p:
            return "DOWN"
        return "TIE"

    def evaluate_outcome(
        self,
        predicted: str,
        target_candle: dict[str, Any],
    ) -> dict[str, Any]:
        actual = self.classify_target(target_candle)
        result = {
            "predicted": predicted,
            "actual": actual,
            "hit": None,
            "tie": actual == "TIE",
        }
        if actual == "TIE" or actual == "UNCERTAIN":
            result["hit"] = False  # do not count as win
            return result
        if predicted == "up" and actual == "UP":
            result["hit"] = True
        elif predicted == "down" and actual == "DOWN":
            result["hit"] = True
        else:
            result["hit"] = False
        return result


__all__ = ["DirectionalOutcomes"]
