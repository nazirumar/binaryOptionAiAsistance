"""Read-only context builders for the chart-vision dashboard page."""

from __future__ import annotations

from typing import Any

from apps.chart_vision.constants import AnalysisStatus
from apps.chart_vision.models import ChartScreenshot, ScreenshotAnalysis

DISCLAIMER = (
    "Vision observations only — MT5 comparison and final strategy evaluation are not yet available."
)


def analysis_for_screenshot(screenshot: ChartScreenshot) -> ScreenshotAnalysis | None:
    return ScreenshotAnalysis.objects.filter(screenshot=screenshot).order_by("-created_at").first()


def history_for_user(user, *, limit: int = 12):
    queryset = ScreenshotAnalysis.objects.select_related("screenshot").order_by("-created_at")
    if not user.is_superuser:
        queryset = queryset.filter(owner=user)
    return list(queryset[:limit])


def screenshot_detail_context(user, screenshot: ChartScreenshot) -> dict[str, Any]:
    """Everything the detail page needs for one screenshot/analysis."""
    analysis = analysis_for_screenshot(screenshot)
    in_flight = bool(analysis and analysis.is_in_flight)
    return {
        "disclaimer": DISCLAIMER,
        "screenshot": screenshot,
        "analysis": analysis,
        "in_flight": in_flight,
        "metadata": analysis.chart_metadata if analysis else {},
        "result": analysis.result if analysis else {},
        "observations": list(analysis.observations.all()) if analysis else [],
        "patterns": list(analysis.patterns.all()) if analysis else [],
        "price_zones": list(analysis.price_zones.all()) if analysis else [],
        "warnings": analysis.warnings if analysis else [],
        "missing_information": analysis.missing_information if analysis else [],
        "observation_confidence": analysis.observation_confidence if analysis else None,
        "events": list(analysis.events.order_by("-occurred_at")[:10]) if analysis else [],
        "can_analyze": screenshot.is_accepted
        and (analysis is None or analysis.status == AnalysisStatus.FAILED),
    }


def overview_context(user) -> dict[str, Any]:
    """Upload page context: history plus the latest analysis (if any)."""
    history = history_for_user(user)
    return {
        "disclaimer": DISCLAIMER,
        "history": history,
        "has_history": bool(history),
    }


__all__ = [
    "DISCLAIMER",
    "analysis_for_screenshot",
    "history_for_user",
    "overview_context",
    "screenshot_detail_context",
]
