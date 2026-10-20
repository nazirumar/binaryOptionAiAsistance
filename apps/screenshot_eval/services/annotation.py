# screenshot_eval/services/annotation.py
"""Chart annotations (Checkpoint 3).

Honesty rule: annotations are drawn **only** when reliable coordinates exist.
The vision model returns *qualitative* descriptions and relative candle
positions - never pixel geometry - so this service will not synthesise
coordinates. When a reviewer (or a future reliable geometry step) supplies
relative coordinates ``[x0, y0, x1, y1]`` in the 0..1 range, an annotation is
written as ``available``; otherwise it is recorded as ``qualitative`` (label
only) or ``skipped`` with an explicit reason. The original screenshot bytes are
never modified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.screenshot_eval.constants import (
    REASON_UNRELIABLE_COORDS,
    AnnotationStatus,
)
from apps.screenshot_eval.models import (
    ChartAnnotation,
    ScreenshotCase,
    ScreenshotRecognitionRun,
)


@dataclass(slots=True)
class AnnotationRequest:
    """A requested annotation; coordinates are optional and trusted verbatim."""

    kind: str
    label: str = ""
    strategy_key: str = ""
    relative_coordinates: list[float] | None = None
    candle_refs: list[int] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def _coords_are_valid(coords: list[float] | None) -> bool:
    if not coords or len(coords) != 4:
        return False
    try:
        values = [float(v) for v in coords]
    except (TypeError, ValueError):
        return False
    if not all(0.0 <= v <= 1.0 for v in values):
        return False
    x0, y0, x1, y1 = values
    return x1 > x0 and y1 > y0


class AnnotationService:
    """Build annotations for a case, skipping anything unreliable."""

    def annotate(
        self,
        *,
        case: ScreenshotCase,
        owner,
        requests: list[AnnotationRequest],
        run: ScreenshotRecognitionRun | None = None,
    ) -> list[ChartAnnotation]:
        """Persist one :class:`ChartAnnotation` per request.

        A request without valid coordinates is stored as ``skipped`` (reason
        recorded) unless the case itself marks coordinates as unreliable, in
        which case the whole set is skipped - nothing is drawn from a guess.
        """
        rows: list[ChartAnnotation] = []
        case_coords_ok = case.coordinates_reliable
        for request in requests:
            has_coords = _coords_are_valid(request.relative_coordinates)
            if has_coords and case_coords_ok:
                status = AnnotationStatus.AVAILABLE
                coords = [float(v) for v in request.relative_coordinates]  # type: ignore[union-attr]
                reason = ""
            elif not case_coords_ok:
                status = AnnotationStatus.SKIPPED
                coords = None
                reason = REASON_UNRELIABLE_COORDS
            else:
                # Case coordinates are reliable but this specific annotation
                # has no verified geometry: keep the label, never invent a box.
                status = AnnotationStatus.QUALITATIVE
                coords = None
                reason = "no verified coordinates for this element"
            rows.append(
                ChartAnnotation.objects.create(
                    case=case,
                    run=run,
                    owner=owner,
                    kind=request.kind,
                    strategy_key=request.strategy_key,
                    label=request.label,
                    status=status,
                    relative_coordinates=coords,
                    candle_refs=list(request.candle_refs),
                    reason=reason,
                    evidence=dict(request.evidence),
                )
            )
        return rows


__all__ = ["AnnotationRequest", "AnnotationService"]
