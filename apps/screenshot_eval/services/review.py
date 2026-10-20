# screenshot_eval/services/review.py
"""Error review queue (Checkpoint 7).

Two responsibilities:

1. **Detection** - scan stored recognition runs and predictions and raise
   :class:`~apps.screenshot_eval.models.ReviewQueueItem` rows for the problem
   kinds the checkpoint lists (misidentified pattern, incorrect breakout, false
   level, missing confirmation, wrong timeframe, contradictory evidence,
   incorrect outcome, low vision confidence, incomplete formation).
2. **Correction** - let an authorised reviewer resolve an item and record a
   correction. The correction is stored *on the queue item* and never rewrites
   the original recognition or prediction record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.book_strategies.constants import BookPatternState
from apps.screenshot_eval.models import (
    ForwardPaperPrediction,
    ReviewQueueItem,
    ScreenshotCase,
    ScreenshotRecognition,
)

#: Vision confidence below which a recognition is worth a human look.
LOW_VISION_CONFIDENCE = 0.4


@dataclass(slots=True)
class ReviewBuildResult:
    created: int
    items: list[ReviewQueueItem]


class ReviewQueueService:
    """Raise and resolve review items; never mutate originals."""

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def scan(self, *, owner=None) -> ReviewBuildResult:
        """Raise review items for every currently-detectable problem.

        Idempotent: an already-open item for the same (kind, record) is returned
        unchanged and is not counted as newly created.
        """
        items: list[ReviewQueueItem] = []
        created_count = 0
        for collector in (
            self._scan_recognitions,
            self._scan_predictions,
            self._scan_cases,
        ):
            for item, was_created in collector(owner):
                items.append(item)
                if was_created:
                    created_count += 1
        return ReviewBuildResult(created=created_count, items=items)

    def _scan_recognitions(self, owner):
        rows = ScreenshotRecognition.objects.select_related("run__case", "run__analysis")
        if owner is not None:
            rows = rows.filter(run__owner=owner)
        out: list[tuple[ReviewQueueItem, bool]] = []
        for row in rows:
            case = row.run.case if row.run_id else None
            owner_id = row.run.owner_id if row.run_id else None

            if row.recognition_state == BookPatternState.FORMING:
                out.append(self._raise(
                    case=case, recognition=row, owner_id=owner_id,
                    kind=ReviewQueueItem.Kind.INCOMPLETE_FORMATION,
                    summary=f"{row.strategy_id} is still forming on the screenshot",
                    detail={"state": row.recognition_state},
                ))
            if row.recognition_state == BookPatternState.AWAITING_CONFIRMATION:
                out.append(self._raise(
                    case=case, recognition=row, owner_id=owner_id,
                    kind=ReviewQueueItem.Kind.MISSING_CONFIRMATION,
                    summary=f"{row.strategy_id} awaits its confirmation candle",
                    detail={"state": row.recognition_state},
                ))
            if row.recognition_state == BookPatternState.INVALIDATED:
                out.append(self._raise(
                    case=case, recognition=row, owner_id=owner_id,
                    kind=ReviewQueueItem.Kind.INCORRECT_BREAKOUT,
                    summary=f"{row.strategy_id} invalidated - check breakout detection",
                    detail={"invalidations": row.invalidation_evidence},
                ))
            if row.contradictions:
                out.append(self._raise(
                    case=case, recognition=row, owner_id=owner_id,
                    kind=ReviewQueueItem.Kind.CONTRADICTORY_EVIDENCE,
                    summary=f"{row.strategy_id} carries recorded contradictions",
                    detail={"contradictions": row.contradictions},
                ))
            if row.matches_label is False:
                out.append(self._raise(
                    case=case, recognition=row, owner_id=owner_id,
                    kind=ReviewQueueItem.Kind.MISIDENTIFIED_PATTERN,
                    summary=f"{row.strategy_id} disagrees with the human label",
                    detail={"expected": list(case.expected_strategy_keys) if case else []},
                ))
        return out

    def _scan_cases(self, owner):
        """Case/annotation/vision problems that are not per-recognition."""
        from apps.screenshot_eval.constants import AnnotationStatus
        from apps.screenshot_eval.models import ChartAnnotation

        out: list[tuple[ReviewQueueItem, bool]] = []

        annotations = ChartAnnotation.objects.select_related("case")
        if owner is not None:
            annotations = annotations.filter(owner=owner)
        for annotation in annotations:
            if annotation.status != AnnotationStatus.AVAILABLE and annotation.kind in (
                "support",
                "resistance",
            ):
                out.append(self._raise(
                    case=annotation.case,
                    owner_id=annotation.case.owner_id if annotation.case_id else None,
                    kind=ReviewQueueItem.Kind.FALSE_LEVEL,
                    summary=f"{annotation.kind} not drawn ({annotation.status})",
                    detail={"reason": annotation.reason, "kind": annotation.kind},
                ))

        cases = ScreenshotCase.objects.all()
        if owner is not None:
            cases = cases.filter(owner=owner)
        for case in cases:
            if case.timeframe not in ("M1", "M5", "M15", "M30", "H1", "H4", "D1"):
                out.append(self._raise(
                    case=case, owner_id=case.owner_id,
                    kind=ReviewQueueItem.Kind.WRONG_TIMEFRAME,
                    summary=f"case timeframe {case.timeframe!r} is not a recognized value",
                    detail={"timeframe": case.timeframe},
                ))
            analysis = case.screenshot.analyses.order_by("-created_at").first()
            if (
                analysis is not None
                and analysis.observation_confidence is not None
                and analysis.observation_confidence < LOW_VISION_CONFIDENCE
            ):
                out.append(self._raise(
                    case=case, owner_id=case.owner_id,
                    kind=ReviewQueueItem.Kind.VISION_UNCERTAINTY,
                    summary="vision observation confidence is low",
                    detail={"confidence": analysis.observation_confidence},
                ))
        return out

    def _scan_predictions(self, owner):
        rows = ForwardPaperPrediction.objects.select_related("case", "outcome")
        if owner is not None:
            rows = rows.filter(owner=owner)
        out: list[tuple[ReviewQueueItem, bool]] = []
        for row in rows:
            outcome = getattr(row, "outcome", None)
            if outcome is not None and outcome.verdict == "incorrect":
                out.append(self._raise(
                    case=row.case, prediction=row, owner_id=row.owner_id,
                    kind=ReviewQueueItem.Kind.INCORRECT_OUTCOME,
                    summary=f"{row.strategy_id} outcome was incorrect",
                    detail={"verdict": outcome.verdict, "reason": outcome.reason},
                ))
        return out

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    @transaction.atomic
    def resolve(
        self,
        *,
        item: ReviewQueueItem,
        reviewer,
        resolution_note: str = "",
        correction: dict[str, Any] | None = None,
        dismiss: bool = False,
    ) -> ReviewQueueItem:
        """Resolve or dismiss an item; corrections never rewrite originals."""
        if not reviewer.is_staff and reviewer.pk != item.owner_id:
            raise PermissionError("only the owner or a staff reviewer may resolve an item")
        item.state = (
            ReviewQueueItem.State.DISMISSED if dismiss else ReviewQueueItem.State.RESOLVED
        )
        if correction:
            item.correction = dict(correction)
        item.resolution_note = resolution_note
        item.resolved_by = reviewer
        item.resolved_at = timezone.now()
        item.save()
        return item

    # ------------------------------------------------------------------
    def _raise(
        self,
        *,
        kind: str,
        summary: str,
        owner_id: int | None,
        case: ScreenshotCase | None = None,
        recognition: ScreenshotRecognition | None = None,
        prediction: ForwardPaperPrediction | None = None,
        detail: dict[str, Any] | None = None,
    ) -> tuple[ReviewQueueItem, bool]:
        # De-duplicate: one open item per (kind, linked record).
        existing = ReviewQueueItem.objects.filter(
            kind=kind,
            state=ReviewQueueItem.State.OPEN,
            case=case,
            recognition=recognition,
            prediction=prediction,
        ).first()
        if existing is not None:
            return existing, False
        item = ReviewQueueItem.objects.create(
            case=case,
            recognition=recognition,
            prediction=prediction,
            owner_id=owner_id,
            kind=kind,
            summary=summary[:240],
            detail=detail or {},
        )
        return item, True


__all__ = ["LOW_VISION_CONFIDENCE", "ReviewBuildResult", "ReviewQueueService"]
