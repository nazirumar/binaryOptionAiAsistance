# ai_assistant/services/probability_presenter.py
"""Probability presentation (Step 16, hardened in Phase 11 CP6).

A probability is displayed **only** when the supplying model passes every
gate below. Each gate has an explicit machine-readable rejection reason; when
any gate fails the caller receives the fixed message
``"Probability unavailable — model not calibrated."`` and nothing else.

Gates
-----
1. A model must be supplied at all.
2. ``is_approved`` must be explicitly ``True`` (truthy strings do not count).
3. A non-empty, versioned model identity (``name``/``version``).
4. A supported, explicit ``prediction_target`` —
   ``next_candle_directional`` or ``binary_settlement``. The two are different
   quantities and are never interchangeable; a **confluence score is not a
   probability** and can never pass through here.
5. A successful held-out calibration evaluation: ``brier_score`` present and
   finite within ``[0, 1]`` (note: ``0.0`` is a *valid perfect* score — the
   old truthy check rejected it), ``calibration_error`` present and finite in
   ``[0, 1]``, and a non-empty ``calibration_method``.
6. A documented held-out evaluation sample size (``sample_count`` /
   ``evaluation_metrics.sample_count``) of at least ``MIN_EVALUATION_SAMPLES``.
7. The probability value itself: present, real, finite and strictly inside
   ``(0, 1)`` — ``NaN``, ``±inf``, negatives, ``0``, ``1`` and values ``> 1``
   are all rejected.
8. Compatibility with the current analysis context: when the caller passes a
   context with ``instrument`` / ``timeframe`` / ``prediction_target``, the
   model must match on every field it declares. An incompatible calibration
   model (e.g. calibrated on M5 EURUSD, applied to M1 GBPUSD) is rejected.
"""

from __future__ import annotations

import math
from typing import Any

PROBABILITY_UNAVAILABLE_MESSAGE = "Probability unavailable — model not calibrated."

#: Explicit probability types. One must never be presented as the other.
NEXT_CANDLE_DIRECTIONAL = "next_candle_directional"
BINARY_SETTLEMENT = "binary_settlement"
SUPPORTED_PREDICTION_TARGETS = (NEXT_CANDLE_DIRECTIONAL, BINARY_SETTLEMENT)

#: The confluence score is an engine artefact, not a probability.
CONFLUENCE_SCORE = "confluence_score"

#: Minimum documented held-out evaluation samples before a calibrated
#: probability may be shown to a user.
MIN_EVALUATION_SAMPLES = 30


def _finite(value: Any) -> bool:
    """Real, finite number — strings and booleans are never accepted."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isfinite(float(value))


def _unit_interval(value: Any) -> bool:
    """Finite and inside the closed interval [0, 1]."""
    return _finite(value) and 0.0 <= float(value) <= 1.0


def _strictly_inside(value: Any) -> bool:
    """Finite and strictly inside (0, 1)."""
    return _finite(value) and 0.0 < float(value) < 1.0


def sample_count_of(model: dict[str, Any]) -> int | None:
    """Extract the documented held-out evaluation sample size, if any."""
    metrics = model.get("evaluation_metrics") or {}
    for source in (metrics, model, model.get("model_data") or {}):
        if not isinstance(source, dict):
            continue
        raw = source.get("sample_count")
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int | float) and raw >= 0:
            return int(raw)
    return None


class ProbabilityPresenter:
    """Strict, gate-checked probability presentation."""

    def __init__(self, min_evaluation_samples: int = MIN_EVALUATION_SAMPLES) -> None:
        self.min_evaluation_samples = min_evaluation_samples

    # -- public API -------------------------------------------------------

    def present(
        self,
        model: dict[str, Any] | None,
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a presentation dict for ``model``, or the unavailable notice."""
        if not model:
            return self._reject("no_model")

        target = str(model.get("prediction_target", "") or "")
        if target not in SUPPORTED_PREDICTION_TARGETS:
            return self._reject("unsupported_prediction_target", model)

        if model.get("is_approved") is not True:
            return self._reject("model_not_approved", model)

        version = str(model.get("version", "") or "")
        if not version:
            return self._reject("missing_model_version", model)

        # Calibration evidence. NOTE: ``brier_score`` of 0.0 is a *valid*
        # perfect score; the previous truthy check rejected it.
        brier = model.get("brier_score")
        if brier is None or not _unit_interval(brier):
            return self._reject("invalid_brier_score", model)
        cal_error = model.get("calibration_error")
        if cal_error is None or not _unit_interval(cal_error):
            return self._reject("invalid_calibration_error", model)
        if not str(model.get("calibration_method", "") or ""):
            return self._reject("missing_calibration_method", model)

        sample_count = sample_count_of(model)
        if sample_count is None:
            return self._reject("missing_evaluation_sample_size", model)
        if sample_count < self.min_evaluation_samples:
            return self._reject("insufficient_evaluation_samples", model)

        probability = model.get("probability")
        if probability is None or not _strictly_inside(probability):
            return self._reject("invalid_probability_value", model)

        incompatibility = self._incompatibility(model, context)
        if incompatibility:
            return self._reject(incompatibility, model)

        return {
            "available": True,
            "calibrated": True,
            "value": float(probability),
            "probability_type": target,
            "prediction_target": target,
            "model_name": str(model.get("name", "") or ""),
            "model_version": version,
            "calibration_status": str(model.get("calibration_status", "") or "calibrated"),
            "brier_score": float(brier),
            "calibration_error": float(cal_error),
            "calibration_method": str(model.get("calibration_method", "")),
            "evaluation_sample_count": sample_count,
            "limitation": "Research estimate only; not a claim of future performance.",
        }

    def from_calibrated_model(
        self, model_obj: Any, *, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Present straight from a persisted ``CalibratedModel`` row."""
        if model_obj is None:
            return self.present(None, context=context)
        return self.present(self.to_dict(model_obj), context=context)

    @staticmethod
    def to_dict(model_obj: Any) -> dict[str, Any]:
        """Convert a ``CalibratedModel`` row into the presenter input shape."""
        metrics = getattr(model_obj, "evaluation_metrics", None) or {}
        return {
            "name": getattr(model_obj, "name", ""),
            "version": getattr(model_obj, "version", ""),
            "is_approved": getattr(model_obj, "is_approved", False),
            "is_active": getattr(model_obj, "is_active", False),
            "prediction_target": (
                metrics.get("prediction_target")
                or (getattr(model_obj, "model_data", None) or {}).get("prediction_target")
                or ""
            ),
            "probability": (getattr(model_obj, "model_data", None) or {}).get("probability"),
            "brier_score": getattr(model_obj, "brier_score", None),
            "calibration_error": getattr(model_obj, "calibration_error", None),
            "calibration_method": getattr(model_obj, "calibration_method", ""),
            "evaluation_metrics": metrics,
            "model_data": getattr(model_obj, "model_data", None) or {},
            "instrument": (getattr(model_obj, "model_data", None) or {}).get("instrument"),
            "timeframe": (getattr(model_obj, "model_data", None) or {}).get("timeframe"),
        }

    def from_confluence_score(self, confluence_score: float | None) -> dict[str, Any]:
        """Explicitly refuse to convert confluence into a probability."""
        return {
            "available": False,
            "message": PROBABILITY_UNAVAILABLE_MESSAGE,
            "calibrated": False,
            "reason": "confluence_score_is_not_a_probability",
            "confluence_score": confluence_score,
        }

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _reject(reason: str, model: dict[str, Any] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "available": False,
            "message": PROBABILITY_UNAVAILABLE_MESSAGE,
            "calibrated": False,
            "reason": reason,
        }
        if model:
            result["model_version"] = str(model.get("version", "") or "")
        return result

    @staticmethod
    def _incompatibility(model: dict[str, Any], context: dict[str, Any] | None) -> str:
        """Return a rejection reason when the model is incompatible."""
        if not context:
            return ""
        for field in ("instrument", "timeframe"):
            model_value = str(model.get(field, "") or "").strip().upper()
            context_value = str(context.get(field, "") or "").strip().upper()
            # Only enforce when the model declares the field.
            if model_value and context_value and model_value != context_value:
                return f"incompatible_{field}"
        model_target = str(model.get("prediction_target", "") or "")
        context_target = str(context.get("prediction_target", "") or "")
        if model_target and context_target and model_target != context_target:
            return "incompatible_prediction_target"
        return ""


__all__ = [
    "BINARY_SETTLEMENT",
    "CONFLUENCE_SCORE",
    "MIN_EVALUATION_SAMPLES",
    "NEXT_CANDLE_DIRECTIONAL",
    "PROBABILITY_UNAVAILABLE_MESSAGE",
    "SUPPORTED_PREDICTION_TARGETS",
    "ProbabilityPresenter",
    "sample_count_of",
]
