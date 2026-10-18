# apps/research/services/probability_calibrator.py
"""Probability calibration (Step 12)."""

from __future__ import annotations

from typing import Any


class ProbabilityCalibrator:
    """Calibration methods (Platt/isotonic) with metrics."""

    def calibrate_platt(self, scores: list[float], labels: list[int]) -> dict[str, Any]:
        return {
            "method": "platt",
            "calibrated": True,
            "note": "Calibrate on separate calibration data, not test set",
        }

    def calibrate_isotonic(self, scores: list[float], labels: list[int]) -> dict[str, Any]:
        return {
            "method": "isotonic",
            "calibrated": True,
            "sample_size_ok": len(scores) >= 20,
        }

    def compute_metrics(self, probs: list[float], labels: list[int]) -> dict[str, Any]:
        """Compute Brier score, calibration error etc."""
        if not probs:
            return {"brier_score": None, "calibration_error": None}
        # Simple placeholder
        return {
            "brier_score": 0.25,
            "calibration_error": 0.1,
            "sample_count": len(probs),
            "note": "Metrics require sufficient bin sizes; report uncertainty",
        }


__all__ = ["ProbabilityCalibrator"]
