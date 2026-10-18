# ai_assistant/services/probability_presenter.py
"""Probability presentation (Step 16).

Retrieves probability estimates only from an approved, validated model.
Never derives a probability by converting a confluence score into a
percentage.
"""

from __future__ import annotations

from typing import Any

PROBABILITY_UNAVAILABLE_MESSAGE = "Probability unavailable — model not calibrated."

#: Explicit probability types. One must never be presented as the other.
NEXT_CANDLE_DIRECTIONAL = "next_candle_directional"
BINARY_SETTLEMENT = "binary_settlement"


class ProbabilityPresenter:
    def present(self, model: dict[str, Any] | None) -> dict[str, Any]:
        if not model:
            return {
                "available": False,
                "message": PROBABILITY_UNAVAILABLE_MESSAGE,
                "calibrated": False,
            }
        if not model.get("is_approved") or not model.get("brier_score"):
            return {
                "available": False,
                "message": PROBABILITY_UNAVAILABLE_MESSAGE,
                "calibrated": False,
                "model_version": model.get("version", ""),
            }
        return {
            "available": True,
            "calibrated": True,
            "value": model.get("probability"),
            "prediction_target": model.get("prediction_target", NEXT_CANDLE_DIRECTIONAL),
            "model_version": model.get("version", ""),
            "calibration_status": model.get("calibration_status", "calibrated"),
            "limitation": "Research estimate only; not a claim of future performance.",
        }

    def from_confluence_score(self, confluence_score: float | None) -> dict[str, Any]:
        """Explicitly refuse to convert confluence into a probability."""
        return {
            "available": False,
            "message": PROBABILITY_UNAVAILABLE_MESSAGE,
            "calibrated": False,
            "reason": "confluence_score_is_not_a_probability",
        }


__all__ = [
    "BINARY_SETTLEMENT",
    "NEXT_CANDLE_DIRECTIONAL",
    "PROBABILITY_UNAVAILABLE_MESSAGE",
    "ProbabilityPresenter",
]
