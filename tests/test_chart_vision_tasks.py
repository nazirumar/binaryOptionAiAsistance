"""Tests for chart-vision Celery tasks (idempotency, retries, retention)."""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.chart_vision.constants import AnalysisStatus
from apps.chart_vision.models import ChartScreenshot, ScreenshotAnalysis
from apps.chart_vision.services.exceptions import (
    SchemaValidationError,
    VisionProviderUnavailableError,
)
from apps.chart_vision.services.screenshot_analyzer import get_or_create_analysis
from apps.chart_vision.tasks import analyze_screenshot_task, purge_screenshots_task
from tests.factories import UserFactory
from tests.vision_fakes import (
    StaticVisionProvider,
    full_payload,
    make_screenshot,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return UserFactory(username="task-analyst")


def _patch_provider(provider):
    return mock.patch(
        "apps.chart_vision.services.screenshot_analyzer.get_vision_provider",
        return_value=provider,
    )


def test_task_runs_analysis_to_completion(user):
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    with _patch_provider(StaticVisionProvider(payload=full_payload())):
        result = analyze_screenshot_task.delay(analysis.pk)
    analysis.refresh_from_db()
    assert analysis.status == AnalysisStatus.COMPLETED
    assert result.result["status"] == "completed"


def test_task_is_idempotent_for_completed_analysis(user):
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    analysis.status = AnalysisStatus.COMPLETED
    analysis.save(update_fields=["status"])
    with _patch_provider(StaticVisionProvider(payload=full_payload())) as provider:
        result = analyze_screenshot_task.delay(analysis.pk)
    assert result.result["status"] == "already_completed"
    provider.assert_not_called()


def test_task_does_not_retry_schema_failures(user):
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    provider = StaticVisionProvider(raw_text="not json at all")
    with _patch_provider(provider):
        result = analyze_screenshot_task.delay(analysis.pk)
    analysis.refresh_from_db()
    assert result.result["status"] == "failed"
    assert analysis.status == AnalysisStatus.FAILED
    assert analysis.error_code == SchemaValidationError.code


def test_task_retries_retryable_provider_error(user):
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    provider = StaticVisionProvider(
        error=VisionProviderUnavailableError("temporary outage", retryable=True)
    )
    with (
        _patch_provider(provider),
        mock.patch.object(
            analyze_screenshot_task, "retry", side_effect=RuntimeError("retry-called")
        ) as retry,
        pytest.raises(RuntimeError, match="retry-called"),
    ):
        analyze_screenshot_task.delay(analysis.pk)
    retry.assert_called_once()
    analysis.refresh_from_db()
    assert analysis.status == AnalysisStatus.QUEUED


def test_task_does_not_retry_non_retryable_provider_error(user):
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    provider = StaticVisionProvider(
        error=VisionProviderUnavailableError("bad key", retryable=False)
    )
    with (
        _patch_provider(provider),
        mock.patch.object(analyze_screenshot_task, "retry") as retry,
    ):
        result = analyze_screenshot_task.delay(analysis.pk)
    retry.assert_not_called()
    assert result.result["status"] == "failed"


def test_task_handles_missing_analysis():
    result = analyze_screenshot_task.delay(999999)
    assert result.result["status"] == "missing"


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------
def test_purge_deletes_expired_screenshots(user):
    expired = make_screenshot(user)
    ChartScreenshot.objects.filter(pk=expired.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )
    kept = make_screenshot(user)
    result = purge_screenshots_task.delay(30)
    assert result.result["deleted"] == 1
    assert not ChartScreenshot.objects.filter(pk=expired.pk).exists()
    assert ChartScreenshot.objects.filter(pk=kept.pk).exists()


def test_purge_deletes_old_rejected_screenshots(user):
    stale = ChartScreenshot.objects.create(owner=user, status="rejected", image="x.png")
    ChartScreenshot.objects.filter(pk=stale.pk).update(
        created_at=timezone.now() - timedelta(days=60)
    )
    result = purge_screenshots_task.delay(30)
    assert result.result["deleted"] == 1
    assert not ChartScreenshot.objects.filter(pk=stale.pk).exists()


def test_analysis_owner_matches_screenshot_owner(user):
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    assert isinstance(analysis, ScreenshotAnalysis)
    assert analysis.owner == user
