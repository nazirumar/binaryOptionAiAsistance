# apps/dashboard/services/performance_service.py
"""Probability / calibration analytics (Phase 9, Step 7).

Integrates Phase 7 model-validation results. Crucially, the three notions are
kept separate and are never conflated:

* **directional prediction probability** - a calibrated next-candle direction
  probability,
* **binary settlement probability** - a calibrated settlement probability,
* **strategy confluence score** - a deterministic, *uncalibrated* score that is
  never presented as a success probability.

When no approved calibrated model exists the calibration status is reported as
``unavailable_uncalibrated`` and no probability is invented.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Avg, Count, Max, Min

from apps.research.models import CalibratedModel
from apps.strategy_engine.models import StrategyEvaluation

INSUFFICIENT_DATA = "Insufficient validated data."


def _to_float(value) -> float | None:  # type: ignore[no-untyped-def]
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class ProbabilityAnalytics:
    """Calibration and probability analytics for one user."""

    def __init__(self, user) -> None:  # type: ignore[no-untyped-def]
        self.user = user

    def build(self) -> dict[str, Any]:
        return {
            "models": self._models(),
            "calibration_status": self._calibration_status(),
            "probabilities": self._probability_types(),
            "confluence": self._confluence_distribution(),
        }

    def _models(self) -> list[dict[str, Any]]:
        models = CalibratedModel.objects.filter(owner=self.user).order_by("-created_at")
        results = []
        for model in models:
            metrics = model.evaluation_metrics or {}
            results.append(
                {
                    "id": model.pk,
                    "name": model.name,
                    "version": model.version,
                    "is_active": model.is_active,
                    "is_approved": model.is_approved,
                    "calibration_method": model.calibration_method,
                    "brier_score": _to_float(model.brier_score),
                    "log_loss": _to_float(metrics.get("log_loss")),
                    "calibration_error": _to_float(model.calibration_error),
                    "sample_size": metrics.get("sample_size"),
                    "confidence_interval": metrics.get("confidence_interval"),
                    "train_period": _period(model.train_period_start, model.train_period_end),
                    "validation_period": _period(model.val_period_start, model.val_period_end),
                    "test_period": _period(model.test_period_start, model.test_period_end),
                    "reliability_bins": metrics.get("reliability_bins", []),
                }
            )
        return results

    def _calibration_status(self) -> dict[str, Any]:
        approved = CalibratedModel.objects.filter(
            owner=self.user, is_approved=True, is_active=True
        ).exists()
        if approved:
            return {"status": "calibrated", "message": None}
        return {
            "status": "unavailable_uncalibrated",
            "message": INSUFFICIENT_DATA,
        }

    def _probability_types(self) -> dict[str, Any]:
        """Explicitly label probability domains; never merge them."""
        return {
            "directional_prediction": {
                "label": "Directional prediction probability",
                "description": (
                    "Calibrated probability that the next candle closes in the "
                    "predicted direction. Requires an approved calibrated model."
                ),
                "available": CalibratedModel.objects.filter(
                    owner=self.user, is_approved=True
                ).exists(),
            },
            "binary_settlement": {
                "label": "Binary settlement probability",
                "description": (
                    "Calibrated probability of settlement for a specific expiry. "
                    "Never inferred from a directional score."
                ),
                "available": False,  # Requires a settlement-specific model.
            },
            "confluence_score": {
                "label": "Strategy confluence score",
                "description": (
                    "Deterministic, uncalibrated score. It is NOT a success "
                    "probability and must never be shown as one."
                ),
                "is_probability": False,
            },
        }

    def _confluence_distribution(self) -> dict[str, Any]:
        aggregated = StrategyEvaluation.objects.filter(
            owner=self.user, confluence_score__isnull=False
        ).aggregate(
            count=Count("id"),
            average=Avg("confluence_score"),
            minimum=Min("confluence_score"),
            maximum=Max("confluence_score"),
        )
        count = aggregated["count"] or 0
        if count == 0:
            return {"count": 0, "message": INSUFFICIENT_DATA}
        return {
            "count": count,
            "average": round(aggregated["average"] or 0.0, 4),
            "min": round(aggregated["minimum"] or 0.0, 4),
            "max": round(aggregated["maximum"] or 0.0, 4),
        }


def _period(start, end) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
    }


__all__ = ["INSUFFICIENT_DATA", "ProbabilityAnalytics"]
