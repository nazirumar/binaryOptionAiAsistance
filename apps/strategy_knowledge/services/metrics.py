"""CP15: detection validation metrics for the strategy recogniser.

Precision / recall / F1 are computed **only** from reviewer-approved dataset
labels (ground truth) compared against recorded :class:`StrategyDetection`
rows for the analyses those samples point at.

Hard separations enforced here:

* These are *pattern detection* metrics. They say nothing about next-candle
  prediction accuracy, trade outcomes or profitability, and every report
  carries ``metric_scope="pattern_detection"`` plus an explicit disclaimer.
* No fabricated statistics: with zero ground-truth positives, recall is
  reported as ``None`` (undefined), never 100%. Counts are always returned
  alongside rates so a reader can see the sample size behind every number.
* ``None``-rate metrics are never averaged over denominators that do not
  exist.
"""

from __future__ import annotations

from typing import Any

from apps.strategy_knowledge.constants import DetectionStatus, LabelSource
from apps.strategy_knowledge.models import StrategyDatasetSample, StrategyDetection

DISCLAIMER = (
    "Pattern-detection metrics over reviewer-approved labels. These are NOT "
    "prediction-accuracy, trade-win-rate or profitability figures."
)

#: Statuses that count as a positive prediction from the recogniser.
POSITIVE_STATUSES = (DetectionStatus.DETECTED, DetectionStatus.POSSIBLE)


class DetectionMetricsService:
    """Compute per-strategy and overall detection metrics from labels."""

    def compute(self, dataset_version: str) -> dict[str, Any]:
        """Metrics for detections whose analysis is covered by ``dataset_version``.

        A sample contributes ground truth only when it is reviewer-approved
        with ``label_source=reviewer``. Positive ground truth = sample kind
        ``positive``; ``negative``/``lookalike``/``incomplete`` count as
        negatives. ``poor_quality`` and ``otc`` samples are excluded from
        rates and reported separately.
        """
        samples = StrategyDatasetSample.objects.filter(
            dataset_version=dataset_version,
            reviewer_approved=True,
            label_source=LabelSource.REVIEWER,
        ).select_related("definition")

        excluded = list(
            samples.filter(sample_kind__in=("poor_quality", "otc")).values_list("label", flat=True)
        )
        usable = samples.exclude(sample_kind__in=("poor_quality", "otc"))

        # Map analysis_id -> set of ground-truth strategy ids.
        truth: dict[int, set[str]] = {}
        label_index: dict[str, str] = {}
        for sample in usable.select_related("screenshot"):
            strategy_id = sample.definition.strategy_id if sample.definition_id else sample.label
            if strategy_id not in label_index:
                label_index[strategy_id] = strategy_id
            analysis_id = _analysis_id_for(sample)
            if analysis_id is None:
                continue
            bucket = truth.setdefault(analysis_id, set())
            if sample.sample_kind == "positive":
                bucket.add(strategy_id)

        if not truth:
            return _report([], excluded, dataset_version)

        detections = StrategyDetection.objects.filter(
            analysis_id__in=list(truth.keys())
        ).select_related("definition")

        predicted: dict[int, set[str]] = {}
        for detection in detections:
            if detection.status not in POSITIVE_STATUSES:
                continue
            predicted.setdefault(detection.analysis_id, set()).add(detection.definition.strategy_id)

        per_strategy: dict[str, dict[str, int]] = {}

        def cell(key: str) -> dict[str, int]:
            return per_strategy.setdefault(key, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})

        for analysis_id, expected in truth.items():
            got = predicted.get(analysis_id, set())
            keys = set(per_strategy) | {label_index.get(k, k) for k in expected} | set(got)
            for key in keys:
                entry = cell(key)
                positive_truth = key in expected
                positive_pred = key in got
                if positive_truth and positive_pred:
                    entry["tp"] += 1
                elif not positive_truth and positive_pred:
                    entry["fp"] += 1
                elif positive_truth and not positive_pred:
                    entry["fn"] += 1
                else:
                    entry["tn"] += 1

        rows = [
            {"strategy_id": key, **counts, **_rates(counts)}
            for key, counts in sorted(per_strategy.items())
        ]
        return _report(rows, excluded, dataset_version)


def _rates(counts: dict[str, int]) -> dict[str, float | None]:
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall)
        else None
    )
    return {"precision": precision, "recall": recall, "f1": f1}


def _report(
    rows: list[dict[str, Any]], excluded: list[str], dataset_version: str
) -> dict[str, Any]:
    totals = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for row in rows:
        for key in totals:
            totals[key] += row[key]
    overall = _rates(totals)
    return {
        "metric_scope": "pattern_detection",
        "disclaimer": DISCLAIMER,
        "dataset_version": dataset_version,
        "overall": {**totals, **overall},
        "per_strategy": rows,
        "excluded_samples": excluded,
        "ground_truth_source": "reviewer_approved_labels_only",
        "interpretation_note": (
            "recall is None when no ground-truth positive exists for a class "
            "(undefined), never 100%"
        ),
    }


def _analysis_id_for(sample: StrategyDatasetSample) -> int | None:
    """Link a dataset sample to the vision analysis produced from it."""
    screenshot = sample.screenshot
    analysis = (
        screenshot.analyses.order_by("-created_at").values_list("pk", flat=True).first()
        if hasattr(screenshot, "analyses")
        else None
    )
    return analysis


__all__ = ["DISCLAIMER", "POSITIVE_STATUSES", "DetectionMetricsService"]
