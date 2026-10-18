"""Structured processing-event logging for chart vision.

Kept in a dependency-light module so upload/API/dashboard code can record audit
events without importing the full analysis pipeline.
"""

from __future__ import annotations

from typing import Any

from apps.chart_vision.constants import EventKind, Severity
from apps.chart_vision.models import (
    ChartScreenshot,
    ScreenshotAnalysis,
    VisionProcessingEvent,
)


def record_event(
    *,
    analysis: ScreenshotAnalysis | None = None,
    screenshot: ChartScreenshot | None = None,
    kind: str,
    message: str = "",
    severity: str = Severity.INFO,
    detail: dict[str, Any] | None = None,
) -> VisionProcessingEvent:
    """Append a structured processing event (never stores secrets)."""
    return VisionProcessingEvent.objects.create(
        analysis=analysis,
        screenshot=screenshot,
        kind=kind,
        message=message[:255],
        severity=severity,
        detail=detail or {},
    )


__all__ = ["EventKind", "record_event"]
