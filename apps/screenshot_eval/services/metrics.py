# screenshot_eval/services/metrics.py
"""Forward-testing metrics (Checkpoint 6), with two hard-separated scopes.

* **Recognition scope** (``pattern_recognition``): did the system identify the
  pattern a human labelled on the same screenshot? Precision and recall are
  computed *only* from reviewer-confirmed/corrected cases; below the label
  threshold they are ``None`` with an explicit insufficiency reason. Ground
  truth here is the human label - never the outcome.
* **Prediction scope** (``binary_settlement_outcome``): the directional hit rate
  over **verified** outcomes only. Unverified, refused, tie and unresolved are
  reported separately and never counted.

The two scopes are never combined. ``assert_scope_separation`` can be used by
tests/dashboards to prove a payload does not leak one scope's keys into the
other.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from apps.screenshot_eval.constants import (
    DEFAULT_MIN_LABELS,
    DEFAULT_MIN_VERIFIED,
    PREDICTION_METRIC_SCOPE,
    PREDICTION_SEPARATION,
    REASON_NOT_COMPUTABLE,
    RECOGNITION_METRIC_SCOPE,
    RECOGNITION_SEPARATION,
)

#: Keys that only belong to the prediction scope.
PREDICTION_ONLY_KEYS = frozenset(
    {"hit_rate", "verified_total", "verified_correct", "unverified", "refused", "ties"}
)
#: Keys that only belong to the recognition scope.
RECOGNITION_ONLY_KEYS = frozenset(
    {"precision", "recall", "true_positives", "false_positives", "false_negatives",
     "labelled_cases"}
)


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """Wilson score interval (95% by default). ``(None, None)`` when no trials."""
    if trials <= 0:
        return (None, None)
    phat = successes / trials
    denom = 1 + z * z / trials
    centre = (phat + z * z / (2 * trials)) / denom
    margin = (z * math.sqrt(phat * (1 - phat) / trials + z * z / (4 * trials * trials))) / denom
    lo = max(0.0, centre - margin)
    hi = min(1.0, centre + margin)
    return (lo, hi)


def assert_scope_separation(payload: dict[str, Any]) -> None:
    """Raise if a recognition or prediction payload leaks the other's keys."""
    scope = payload.get("metric_scope")
    if scope == RECOGNITION_METRIC_SCOPE:
        foreign = PREDICTION_ONLY_KEYS.intersection(payload)
        if foreign:
            raise ValueError(f"recognition payload leaks prediction keys: {sorted(foreign)}")
    elif scope == PREDICTION_METRIC_SCOPE:
        foreign = RECOGNITION_ONLY_KEYS.intersection(payload)
        if foreign:
            raise ValueError(f"prediction payload leaks recognition keys: {sorted(foreign)}")


@dataclass(slots=True)
class RecognitionMetrics:
    """Recognition precision/recall from human-labelled cases."""

    labelled_cases: int = 0
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    true_negatives: int = 0
    incomplete_formations: int = 0
    min_labels: int = DEFAULT_MIN_LABELS

    @property
    def precision(self) -> float | None:
        denom = self.true_positives + self.false_positives
        return (self.true_positives / denom) if denom else None

    @property
    def recall(self) -> float | None:
        denom = self.true_positives + self.false_negatives
        return (self.true_positives / denom) if denom else None

    def as_dict(self) -> dict[str, Any]:
        sufficient = self.labelled_cases >= self.min_labels
        precision = self.precision if sufficient else None
        recall = self.recall if sufficient else None
        return {
            "metric_scope": RECOGNITION_METRIC_SCOPE,
            "statement": RECOGNITION_SEPARATION,
            "labelled_cases": self.labelled_cases,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "true_negatives": self.true_negatives,
            "incomplete_formations": self.incomplete_formations,
            "precision": precision,
            "recall": recall,
            "precision_wilson_95": list(
                wilson_interval(self.true_positives, self.true_positives + self.false_positives)
            ),
            "recall_wilson_95": list(
                wilson_interval(self.true_positives, self.true_positives + self.false_negatives)
            ),
            "sufficient_data": sufficient,
            "status": None if sufficient else REASON_NOT_COMPUTABLE,
            "insufficient_reason": (
                None
                if sufficient
                else f"only {self.labelled_cases} human-labelled cases; below the "
                f"{self.min_labels}-label threshold. Recognitions vs labels only - "
                "never mixed with outcome accuracy."
            ),
            "approved_for_decision_use": False,
        }


@dataclass(slots=True)
class PredictionMetrics:
    """Directional hit rate over verified outcomes only."""

    verified_total: int = 0
    verified_correct: int = 0
    ties: int = 0
    unverified: int = 0
    refused: int = 0
    unresolved: int = 0
    up: int = 0
    down: int = 0
    no_trade: int = 0
    min_verified: int = DEFAULT_MIN_VERIFIED

    def as_dict(self) -> dict[str, Any]:
        sufficient = self.verified_total >= self.min_verified
        hit_rate = (self.verified_correct / self.verified_total) if self.verified_total else None
        return {
            "metric_scope": PREDICTION_METRIC_SCOPE,
            "statement": PREDICTION_SEPARATION,
            "verified_total": self.verified_total,
            "verified_correct": self.verified_correct,
            "ties": self.ties,
            "unverified": self.unverified,
            "refused": self.refused,
            "unresolved": self.unresolved,
            "up": self.up,
            "down": self.down,
            "no_trade": self.no_trade,
            "hit_rate": hit_rate,
            "hit_rate_wilson_95": list(wilson_interval(self.verified_correct, self.verified_total)),
            "sufficient_data": sufficient,
            "insufficient_reason": (
                None
                if sufficient
                else f"only {self.verified_total} verified outcomes; below the "
                f"{self.min_verified}-outcome threshold. Unverified/refused/tie/"
                "unresolved are excluded, never counted as correct."
            ),
            "excluded_from_accuracy": self.unverified + self.refused + self.ties + self.unresolved,
            "approved_for_decision_use": False,
        }


class ScreenshotMetricsService:
    """Build both scopes plus per-segment breakdowns from stored records."""

    def __init__(
        self,
        *,
        min_labels: int = DEFAULT_MIN_LABELS,
        min_verified: int = DEFAULT_MIN_VERIFIED,
    ) -> None:
        self.min_labels = min_labels
        self.min_verified = min_verified

    # ---- recognition scope -------------------------------------------------
    def _recognition(self) -> RecognitionMetrics:
        from apps.screenshot_eval.constants import CaseKind, ReviewState
        from apps.screenshot_eval.models import ScreenshotCase, ScreenshotRecognition

        metrics = RecognitionMetrics(min_labels=self.min_labels)
        labelled = ScreenshotCase.objects.filter(
            review_state__in=(ReviewState.CONFIRMED, ReviewState.CORRECTED)
        )
        metrics.labelled_cases = labelled.count()
        metrics.incomplete_formations = labelled.filter(case_kind=CaseKind.INCOMPLETE).count()

        for case in labelled:
            expected = set(case.expected_strategy_keys or [])
            # "Detections" for the case: any strategy whose recognition state is
            # CONFIRMED_PATTERN (a positive recognition) across its runs.
            rows = ScreenshotRecognition.objects.filter(
                run__case=case, recognition_state="CONFIRMED_PATTERN"
            )
            detected = {r.strategy_key for r in rows}
            if expected:
                for key in expected:
                    if key in detected:
                        metrics.true_positives += 1
                    else:
                        metrics.false_negatives += 1
                for _key in detected - expected:
                    metrics.false_positives += 1
            else:
                # A negative example: any detection is a false positive.
                metrics.false_positives += len(detected)
                if not detected:
                    metrics.true_negatives += 1
        return metrics

    # ---- prediction scope --------------------------------------------------
    def _prediction(
        self, predictions: list[Any] | None = None
    ) -> PredictionMetrics:
        from apps.screenshot_eval.constants import PredictionDirection, PredictionStatus
        from apps.screenshot_eval.models import ForwardPaperPrediction

        rows = (
            list(predictions)
            if predictions is not None
            else list(ForwardPaperPrediction.objects.select_related("outcome"))
        )
        metrics = PredictionMetrics(min_verified=self.min_verified)
        for row in rows:
            if row.direction == PredictionDirection.UP:
                metrics.up += 1
            elif row.direction == PredictionDirection.DOWN:
                metrics.down += 1
            else:
                metrics.no_trade += 1
                continue
            if row.status == PredictionStatus.VERIFIED:
                outcome = getattr(row, "outcome", None)
                if outcome is not None and outcome.counts_as_verified:
                    if outcome.verdict == "correct":
                        metrics.verified_correct += 1
                        metrics.verified_total += 1
                    elif outcome.verdict == "incorrect":
                        metrics.verified_total += 1
                    elif outcome.verdict == "tie":
                        metrics.ties += 1
            elif row.status == PredictionStatus.TIE:
                metrics.ties += 1
            elif row.status == PredictionStatus.UNVERIFIED:
                metrics.unverified += 1
            elif row.status == PredictionStatus.UNRESOLVED:
                metrics.unresolved += 1
        return metrics

    def build(
        self, predictions: list[Any] | None = None
    ) -> dict[str, Any]:
        recognition = self._recognition()
        prediction = self._prediction(predictions)
        return {
            "recognition": recognition.as_dict(),
            "prediction": prediction.as_dict(),
            "separation_note": (
                "Recognition metrics and prediction metrics are separate scopes "
                "and are never combined into a single accuracy figure."
            ),
            "approved_for_decision_use": False,
        }

    # ---- segmentation ------------------------------------------------------
    def by_segment(self, dimension: str) -> dict[str, Any]:
        """Segmented verified-outcome counts by strategy/instrument/timeframe/market."""
        from apps.screenshot_eval.constants import PredictionDirection, PredictionStatus
        from apps.screenshot_eval.models import ForwardPaperPrediction

        field_name = {
            "strategy": "strategy_key",
            "instrument": "instrument",
            "timeframe": "timeframe",
            "market_type": "market_type",
        }.get(dimension)
        if field_name is None:
            raise ValueError(f"unknown segment dimension: {dimension!r}")

        buckets: dict[str, dict[str, int]] = {}
        for row in ForwardPaperPrediction.objects.select_related("outcome"):
            key = str(getattr(row, field_name) or "unknown")
            bucket = buckets.setdefault(
                key,
                {"total": 0, "up": 0, "down": 0, "no_trade": 0,
                 "verified_total": 0, "verified_correct": 0, "excluded": 0},
            )
            bucket["total"] += 1
            if row.direction == PredictionDirection.UP:
                bucket["up"] += 1
            elif row.direction == PredictionDirection.DOWN:
                bucket["down"] += 1
            else:
                bucket["no_trade"] += 1
            if row.direction == PredictionDirection.NO_TRADE:
                continue
            outcome = getattr(row, "outcome", None)
            if row.status == PredictionStatus.VERIFIED and outcome and outcome.counts_as_verified:
                bucket["verified_total"] += 1
                if outcome.verdict == "correct":
                    bucket["verified_correct"] += 1
            else:
                bucket["excluded"] += 1
        for bucket in buckets.values():
            n = bucket["verified_total"]
            bucket["hit_rate"] = (bucket["verified_correct"] / n) if n else None
        return {"dimension": dimension, "buckets": buckets}


__all__ = [
    "PREDICTION_ONLY_KEYS",
    "RECOGNITION_ONLY_KEYS",
    "PredictionMetrics",
    "RecognitionMetrics",
    "ScreenshotMetricsService",
    "assert_scope_separation",
    "wilson_interval",
]
