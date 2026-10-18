"""Celery tasks for chart-vision analysis and retention.

Jobs are idempotent: a completed analysis is never re-run, and a screenshot has
exactly one analysis row per (prompt, schema) version, so repeated API requests
cannot create uncontrolled duplicate work.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.chart_vision.constants import AnalysisStatus, EventKind, Severity, UploadStatus
from apps.chart_vision.models import ChartScreenshot, ScreenshotAnalysis
from apps.chart_vision.services.exceptions import (
    ChartVisionError,
    VisionProviderUnavailableError,
)
from apps.chart_vision.services.screenshot_analyzer import ScreenshotAnalyzer, record_event

logger = logging.getLogger(__name__)

_COMPLETED_STATES = {
    AnalysisStatus.COMPLETED,
    AnalysisStatus.PARTIAL,
    AnalysisStatus.INSUFFICIENT,
}


def _requeue(analysis: ScreenshotAnalysis) -> None:
    analysis.status = AnalysisStatus.QUEUED
    analysis.save(update_fields=["status", "updated_at"])


def _mark_failed(analysis: ScreenshotAnalysis, code: str, message: str) -> None:
    analysis.status = AnalysisStatus.FAILED
    analysis.error_code = code[:60]
    analysis.error_message = message[:2000]
    analysis.finished_at = timezone.now()
    analysis.save(
        update_fields=["status", "error_code", "error_message", "finished_at", "updated_at"]
    )
    record_event(
        analysis=analysis,
        kind=EventKind.QUEUE,
        severity=Severity.ERROR,
        message=f"Analysis job failed: {code}",
    )


@shared_task(bind=True, name="chart_vision.analyze_screenshot")
def analyze_screenshot_task(self, analysis_id: int) -> dict:
    """Run the vision analysis for an existing analysis row."""
    analysis = (
        ScreenshotAnalysis.objects.select_related("screenshot").filter(pk=analysis_id).first()
    )
    if analysis is None:
        return {"status": "missing", "analysis_id": analysis_id}

    # Idempotency: never re-run a successful analysis.
    if analysis.status in _COMPLETED_STATES:
        return {"status": "already_completed", "analysis_id": analysis_id}

    max_attempts = max(1, int(getattr(settings, "VISION_ANALYSIS_MAX_ATTEMPTS", 3)))
    backoff = float(getattr(settings, "VISION_LLM_BACKOFF_SECONDS", 1.5))
    attempt = int(self.request.retries)

    record_event(
        analysis=analysis,
        kind=EventKind.QUEUE,
        message="Analysis job started.",
        detail={"attempt": attempt + 1},
    )
    try:
        ScreenshotAnalyzer().analyze(analysis.screenshot, analysis)
    except VisionProviderUnavailableError as exc:
        if getattr(exc, "retryable", True) and attempt < max_attempts - 1:
            _requeue(analysis)
            raise self.retry(
                exc=exc, countdown=backoff * (2**attempt), max_retries=max_attempts - 1
            ) from exc
        return {"status": "failed", "error_code": getattr(exc, "code", "provider_error")}
    except ChartVisionError as exc:
        # The analyser already recorded a precise failure; do not retry.
        return {"status": "failed", "error_code": getattr(exc, "code", "error")}
    except Exception as exc:  # pragma: no cover - unexpected
        logger.exception("chart_vision.task_unexpected_error")
        if attempt < max_attempts - 1:
            _requeue(analysis)
            raise self.retry(
                exc=exc, countdown=backoff * (2**attempt), max_retries=max_attempts - 1
            ) from exc
        _mark_failed(analysis, "unexpected_error", str(exc))
        return {"status": "failed", "error_code": "unexpected_error"}

    analysis.refresh_from_db()
    return {
        "status": analysis.status,
        "analysis_id": analysis.pk,
        "candles": analysis.candle_count,
    }


@shared_task(name="chart_vision.purge_screenshots")
def purge_screenshots_task(retention_days: int | None = None) -> dict:
    """Delete screenshots (and their files) past the retention window."""
    days = int(retention_days or getattr(settings, "VISION_SCREENSHOT_RETENTION_DAYS", 30))
    cutoff = timezone.now() - timedelta(days=days)
    expired = ChartScreenshot.objects.filter(
        status=UploadStatus.REJECTED, created_at__lt=cutoff
    ) | ChartScreenshot.objects.filter(expires_at__lt=timezone.now())
    deleted = 0
    for screenshot in expired.distinct():
        if screenshot.image:
            screenshot.image.delete(save=False)
        screenshot.delete()
        deleted += 1
    return {"deleted": deleted, "retention_days": days}


__all__ = ["analyze_screenshot_task", "purge_screenshots_task"]
