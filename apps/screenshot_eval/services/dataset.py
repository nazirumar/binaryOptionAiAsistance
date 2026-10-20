# screenshot_eval/services/dataset.py
"""Screenshot dataset (Checkpoint 1).

A *case* is a human-curated screenshot: instrument, timeframe, capture time,
market type, quality, visible candle count, expected label and provenance.
This service creates cases from already-uploaded
:class:`~apps.chart_vision.models.ChartScreenshot` rows. It never invents a
screenshot, a label or a provenance value - anything unknown stays ``unknown``
until a reviewer fills it in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db import transaction

from apps.chart_vision.models import ChartScreenshot
from apps.screenshot_eval.constants import (
    CaseKind,
    MarketType,
    Provenance,
    ReviewState,
    ScreenshotQuality,
)
from apps.screenshot_eval.models import ScreenshotCase


@dataclass(slots=True)
class CaseInput:
    """Reviewer-supplied fields for one case (all optional but explicit)."""

    label: str = ""
    instrument: str = ""
    timeframe: str = ""
    market_type: str = MarketType.UNKNOWN
    quality: str = ScreenshotQuality.UNKNOWN
    visible_candle_count: int = 0
    case_kind: str = CaseKind.UNLABELLED
    expected_strategy_keys: list[str] = field(default_factory=list)
    expected_direction: str = ""
    coordinates_reliable: bool = False
    source: str = Provenance.UNKNOWN
    provenance: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    screenshot_timestamp: Any = None


class ScreenshotDatasetService:
    """Create and review dataset cases (never fabricates a case)."""

    def create_case(
        self,
        *,
        owner,
        screenshot: ChartScreenshot,
        data: CaseInput,
    ) -> ScreenshotCase:
        """Create one case from an owned, accepted screenshot.

        Ownership is enforced by the caller (the view/command passes a
        screenshot the owner is allowed to see); this service additionally
        refuses a screenshot that is not this owner's to prevent IDOR.
        """
        if screenshot.owner_id != owner.pk:
            raise PermissionError("cannot create a case for another user's screenshot")
        return ScreenshotCase.objects.create(
            owner=owner,
            screenshot=screenshot,
            label=data.label or f"Screenshot #{screenshot.pk}",
            notes=data.notes,
            instrument=data.instrument,
            timeframe=data.timeframe,
            screenshot_timestamp=data.screenshot_timestamp,
            market_type=data.market_type,
            quality=data.quality,
            visible_candle_count=data.visible_candle_count,
            case_kind=data.case_kind,
            expected_strategy_keys=list(data.expected_strategy_keys),
            expected_direction=data.expected_direction,
            coordinates_reliable=data.coordinates_reliable,
            source=data.source,
            provenance=dict(data.provenance),
        )

    @transaction.atomic
    def review(
        self,
        *,
        case: ScreenshotCase,
        reviewer,
        review_state: str,
        case_kind: str | None = None,
        expected_strategy_keys: list[str] | None = None,
        expected_direction: str | None = None,
        notes: str | None = None,
    ) -> ScreenshotCase:
        """Record a reviewer verdict, optionally correcting the label.

        The correction updates the case's *human label* only; it never touches
        stored predictions or recognition runs (that is the whole point of the
        review queue's separation of concerns).
        """
        if not reviewer.is_staff and reviewer.pk != case.owner_id:
            raise PermissionError("only the owner or a staff reviewer may review a case")
        case.review_state = review_state
        case.reviewed_by = reviewer
        from django.utils import timezone

        case.reviewed_at = timezone.now()
        if case_kind is not None:
            case.case_kind = case_kind
        if expected_strategy_keys is not None:
            case.expected_strategy_keys = list(expected_strategy_keys)
        if expected_direction is not None:
            case.expected_direction = expected_direction
        if notes is not None:
            case.notes = notes
        case.save()
        return case

    @staticmethod
    def labelled_queryset():
        """Cases that count as ground truth (reviewer confirmed/corrected)."""
        return ScreenshotCase.objects.filter(
            review_state__in=(ReviewState.CONFIRMED, ReviewState.CORRECTED)
        )


__all__ = ["CaseInput", "ScreenshotDatasetService"]
