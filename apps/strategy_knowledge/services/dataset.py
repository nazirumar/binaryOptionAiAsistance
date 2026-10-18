"""CP14: strategy dataset workflow — reviewer labels are the only ground truth.

The workflow keeps vision candidates, course references and human review in
separate ``label_source`` lanes so an unverified model guess can never become
"truth" by accumulation:

1. A sample is created from a screenshot (optionally seeded with a vision
   candidate label, stored as ``vision_candidate`` / not approved).
2. A reviewer confirms or corrects the label (``reviewer`` +
   ``reviewer_approved=True`` switches ``label_source`` to ``reviewer``).
3. Only reviewer-approved samples enter metric ground truth.

Poor-quality and OTC screenshots are first-class sample kinds — they are
labelled and excluded from price-based confirmation rather than silently
mixed in.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, QuerySet

from apps.chart_vision.models import ChartScreenshot
from apps.strategy_knowledge.constants import (
    DatasetSampleKind,
    LabelSource,
)
from apps.strategy_knowledge.models import (
    StrategyDatasetSample,
    StrategyDefinition,
)


class DatasetWorkflowError(ValueError):
    """Raised for invalid workflow transitions (never swallowed)."""


class StrategyDatasetWorkflow:
    """Create, review and export labelled dataset samples."""

    # -- creation ----------------------------------------------------------

    def add_candidate(
        self,
        screenshot: ChartScreenshot,
        *,
        label: str,
        sample_kind: str = DatasetSampleKind.POSITIVE,
        definition: StrategyDefinition | None = None,
        instrument: str = "",
        timeframe: str = "",
        market_type: str = "",
        candle_refs: list[int] | None = None,
        notes: str = "",
    ) -> StrategyDatasetSample:
        """Add an *unverified* candidate sample (vision or self-labelled).

        ``label_source`` is always ``vision_candidate`` here — creation is never
        a review. Approval requires :meth:`approve`.
        """
        if sample_kind not in DatasetSampleKind.values:
            raise DatasetWorkflowError(f"unknown sample kind: {sample_kind}")
        return StrategyDatasetSample.objects.create(
            screenshot=screenshot,
            definition=definition,
            label=str(label)[:80],
            sample_kind=sample_kind,
            label_source=LabelSource.VISION_CANDIDATE,
            reviewer=None,
            reviewer_approved=False,
            instrument=instrument,
            timeframe=timeframe,
            market_type=market_type,
            candle_refs=list(candle_refs or []),
            notes=notes,
        )

    # -- review ------------------------------------------------------------

    def approve(
        self,
        sample: StrategyDatasetSample,
        reviewer,
        *,
        label: str | None = None,
        sample_kind: str | None = None,
        label_confidence: float | None = None,
        notes: str = "",
    ) -> StrategyDatasetSample:
        """Reviewer confirms (optionally corrects) a sample's label.

        Approval flips ``label_source`` to ``reviewer``; the previous candidate
        text is preserved in ``notes`` when the label changes, so corrections
        remain auditable.
        """
        if reviewer is None or not getattr(reviewer, "is_authenticated", True):
            raise DatasetWorkflowError("approval requires an authenticated reviewer")
        if label is not None and label != sample.label:
            prior = f"[prior candidate label: {sample.label}]"
            sample.notes = (sample.notes + "\n" if sample.notes else "") + prior
            sample.label = str(label)[:80]
        if sample_kind is not None:
            if sample_kind not in DatasetSampleKind.values:
                raise DatasetWorkflowError(f"unknown sample kind: {sample_kind}")
            sample.sample_kind = sample_kind
        if label_confidence is not None:
            if not 0.0 <= label_confidence <= 1.0:
                raise DatasetWorkflowError("label_confidence must be within [0, 1]")
            sample.label_confidence = label_confidence
        if notes:
            sample.notes = (sample.notes + "\n" if sample.notes else "") + notes
        sample.reviewer = reviewer
        sample.reviewer_approved = True
        sample.label_source = LabelSource.REVIEWER
        sample.save()
        return sample

    def reject(
        self, sample: StrategyDatasetSample, reviewer, *, notes: str = ""
    ) -> StrategyDatasetSample:
        """Reviewer marks a sample as not usable (label stands, approval false)."""
        if reviewer is None:
            raise DatasetWorkflowError("rejection requires a reviewer")
        sample.reviewer = reviewer
        sample.reviewer_approved = False
        if notes:
            sample.notes = (sample.notes + "\n" if sample.notes else "") + notes
        sample.save(update_fields=["reviewer", "reviewer_approved", "notes", "updated_at"])
        return sample

    # -- queries -----------------------------------------------------------

    @staticmethod
    def ground_truth(dataset_version: str) -> QuerySet:
        """Reviewer-approved samples for a dataset version (metric input only)."""
        return StrategyDatasetSample.objects.filter(
            dataset_version=dataset_version,
            reviewer_approved=True,
            label_source=LabelSource.REVIEWER,
        )

    @staticmethod
    def pending_review() -> QuerySet:
        return StrategyDatasetSample.objects.filter(reviewer_approved=False).exclude(
            label_source=LabelSource.REVIEWER
        )

    @staticmethod
    def summary(dataset_version: str) -> dict[str, Any]:
        """Composition of a dataset version — counts only, no metrics."""
        rows = StrategyDatasetSample.objects.filter(dataset_version=dataset_version)
        by_kind = dict(
            rows.values("sample_kind").annotate(c=Count("id")).values_list("sample_kind", "c")
        )
        approved = rows.filter(reviewer_approved=True, label_source=LabelSource.REVIEWER).count()
        pending = rows.filter(reviewer_approved=False).count()
        return {
            "dataset_version": dataset_version,
            "total": rows.count(),
            "by_kind": by_kind,
            "reviewer_approved": approved,
            "pending_review": pending,
        }


__all__ = ["DatasetWorkflowError", "StrategyDatasetWorkflow"]
