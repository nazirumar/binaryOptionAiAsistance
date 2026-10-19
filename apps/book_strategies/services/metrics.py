# book_strategies/services/metrics.py
"""Recognition vs. prediction metric separation (Phase 13, requirement 6).

Two different things are measured in this app and they must never be mixed:

* **Recognition accuracy** (scope ``pattern_recognition``): did the
  deterministic recognizer reproduce/identify a pattern as a human reviewer
  would? Ground truth is reviewer labels; where no reviewer-labeled ground
  truth for book patterns exists, recognition accuracy is ``None`` with an
  explicit NOT_COMPUTABLE status - it is never estimated, borrowed from the
  prediction side, or inferred from candle outcomes.
* **Prediction accuracy** (scope ``next_candle_direction``): the direction of
  the following candle's close, computed only by ``services/validation.py``
  and ``services/walk_forward.py`` - never by anything in this module.

``assert_recognition_scope`` / ``assert_prediction_scope`` enforce the wall
in both directions and are used by tests and by the dashboard payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.book_strategies.constants import BookPatternState
from apps.book_strategies.services.validation import METRIC_SCOPE as PREDICTION_METRIC_SCOPE

RECOGNITION_METRIC_SCOPE = "pattern_recognition"

#: Keys that exist only in prediction-side reports.
PREDICTION_ONLY_KEYS = frozenset(
    {
        "splits",
        "signals",
        "accuracy",
        "wilson_95",
        "baseline_accuracy",
        "baseline_rule",
        "hypothetical_expectancy_per_trade",
        "hypothetical_payout_rate",
        "oos_fraction",
        "leakage_control",
        "insufficient_reason",
        "sufficient_data",
    }
)

#: Keys that exist only in recognition-side reports.
RECOGNITION_ONLY_KEYS = frozenset(
    {
        "n_detections",
        "state_counts",
        "data_verification_counts",
        "strategy_counts",
        "recognition_accuracy",
        "recognition_accuracy_status",
        "recognition_accuracy_reason",
        "reproducibility",
    }
)

NOT_COMPUTABLE_STATUS = "NOT_COMPUTABLE_NO_GROUND_TRUTH"
NOT_COMPUTABLE_REASON = (
    "reviewer-labeled ground truth does not exist for book-pattern "
    "recognitions, so recognition accuracy is not computed and never "
    "inferred from candle outcomes"
)

SEPARATION_STATEMENT = (
    "Recognition (observation) metrics only: this report contains no "
    "next-candle direction, hit-rate, baseline or settlement statistics."
)


def assert_recognition_scope(payload: dict[str, Any]) -> None:
    """Raise if a recognition payload leaks prediction metrics into itself."""
    if payload.get("metric_scope") != RECOGNITION_METRIC_SCOPE:
        raise ValueError(
            f"recognition payload must carry metric_scope="
            f"{RECOGNITION_METRIC_SCOPE!r}, got {payload.get('metric_scope')!r}"
        )
    foreign = PREDICTION_ONLY_KEYS.intersection(payload)
    if foreign:
        raise ValueError(
            f"recognition payload contains prediction-scope keys: {sorted(foreign)}"
        )


def assert_prediction_scope(payload: dict[str, Any]) -> None:
    """Raise if a prediction payload carries recognition metrics."""
    if payload.get("metric_scope") != PREDICTION_METRIC_SCOPE:
        raise ValueError(
            f"prediction payload must carry metric_scope="
            f"{PREDICTION_METRIC_SCOPE!r}, got {payload.get('metric_scope')!r}"
        )
    foreign = RECOGNITION_ONLY_KEYS.intersection(payload)
    if foreign:
        raise ValueError(
            f"prediction payload contains recognition-scope keys: {sorted(foreign)}"
        )


@dataclass(slots=True)
class RecognitionMetricsReport:
    n_detections: int = 0
    n_strategies: int = 0
    state_counts: dict[str, int] = field(default_factory=dict)
    data_verification_counts: dict[str, int] = field(default_factory=dict)
    strategy_counts: dict[str, int] = field(default_factory=dict)
    #: Always None until reviewer-labeled book-pattern ground truth exists.
    recognition_accuracy: None = None
    recognition_accuracy_status: str = NOT_COMPUTABLE_STATUS
    recognition_accuracy_reason: str = NOT_COMPUTABLE_REASON
    reproducibility: dict[str, Any] | None = None
    separation_statement: str = SEPARATION_STATEMENT
    metric_scope: str = RECOGNITION_METRIC_SCOPE
    approved_for_decision_use: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_scope": self.metric_scope,
            "n_detections": self.n_detections,
            "n_strategies": self.n_strategies,
            "state_counts": dict(self.state_counts),
            "data_verification_counts": dict(self.data_verification_counts),
            "strategy_counts": dict(self.strategy_counts),
            "recognition_accuracy": None,
            "recognition_accuracy_status": self.recognition_accuracy_status,
            "recognition_accuracy_reason": self.recognition_accuracy_reason,
            "reproducibility": dict(self.reproducibility) if self.reproducibility else None,
            "separation_statement": self.separation_statement,
            "approved_for_decision_use": False,
        }


class RecognitionMetricsService:
    """Aggregate recognition (observation) statistics from stored detections."""

    def build(self) -> RecognitionMetricsReport:
        from apps.book_strategies.models import BookStrategyDetection

        report = RecognitionMetricsReport()
        rows = list(
            BookStrategyDetection.objects.values_list(
                "strategy__key", "state", "data_verification"
            )
        )
        report.n_detections = len(rows)
        report.n_strategies = len({row[0] for row in rows})
        for strategy_key, state, verification in rows:
            report.state_counts[state] = report.state_counts.get(state, 0) + 1
            report.data_verification_counts[verification] = (
                report.data_verification_counts.get(verification, 0) + 1
            )
            report.strategy_counts[strategy_key] = (
                report.strategy_counts.get(strategy_key, 0) + 1
            )
        return report

    @staticmethod
    def verify_reproducibility(key: str, candles: list[dict[str, Any]]) -> dict[str, Any]:
        """Re-run the detector twice on identical input and compare results.

        Reproducibility is a *recognition* property (same input, same state) -
        it says nothing about predictive accuracy and is never presented as
        such.
        """
        from apps.book_strategies.constants import SPEC_BY_KEY
        from apps.book_strategies.services.detectors import BOOK_DETECTORS

        spec = SPEC_BY_KEY.get(key)
        detector = BOOK_DETECTORS.get(spec.detector_key) if spec and spec.detector_key else None
        if detector is None:
            return {"available": False, "reason": "no detector registered for key"}
        first = detector(list(candles))
        second = detector(list(candles))
        identical = (
            first.state == second.state
            and first.direction == second.direction
            and first.completed_at == second.completed_at
        )
        return {
            "available": True,
            "runs": 2,
            "identical": 2 if identical else 1,
            "reproduced": identical,
            "state": first.state,
            "valid_states": list(BookPatternState.ALL),
            "note": (
                "deterministic reproduction check (recognition scope); not a "
                "predictive accuracy figure"
            ),
        }


__all__ = [
    "NOT_COMPUTABLE_STATUS",
    "PREDICTION_METRIC_SCOPE",
    "RECOGNITION_METRIC_SCOPE",
    "RecognitionMetricsReport",
    "RecognitionMetricsService",
    "assert_prediction_scope",
    "assert_recognition_scope",
]
