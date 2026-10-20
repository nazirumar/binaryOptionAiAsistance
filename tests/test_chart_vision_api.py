"""Tests for the chart-vision REST API (auth, upload, dedupe, isolation)."""

from __future__ import annotations

from unittest import mock

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.chart_vision.constants import AnalysisStatus
from apps.chart_vision.models import ChartScreenshot, ScreenshotAnalysis
from apps.chart_vision.services.screenshot_analyzer import get_or_create_analysis
from tests.factories import UserFactory
from tests.vision_fakes import (
    StaticVisionProvider,
    full_payload,
    make_screenshot,
    png_bytes,
    uploaded_file,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return UserFactory(username="api-analyst")


@pytest.fixture
def other_user():
    return UserFactory(username="api-other")


@pytest.fixture
def api(user):
    client = APIClient()
    client.force_login(user)
    return client


def _patch_provider(payload=None):
    provider = StaticVisionProvider(payload=payload or full_payload())
    return mock.patch(
        "apps.chart_vision.services.screenshot_analyzer.get_vision_provider",
        return_value=provider,
    )


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("method", "url_name", "args"),
    [
        ("get", "chart_vision:screenshots", []),
        ("get", "chart_vision:history", []),
        ("get", "chart_vision:status", [1]),
        ("get", "chart_vision:analysis-detail", [1]),
    ],
)
def test_endpoints_require_authentication(method, url_name, args):
    client = APIClient()
    response = getattr(client, method)(reverse(url_name, args=args))
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def test_upload_valid_image(api, user):
    response = api.post(
        reverse("chart_vision:screenshots"),
        {"image": uploaded_file(png_bytes())},
        format="multipart",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["screenshot"]["status"] == "accepted"
    assert body["screenshot"]["image_format"] == "png"
    assert body["screenshot"]["width"] == 800
    assert body["screenshot"]["image_url"]
    screenshot = ChartScreenshot.objects.get(pk=body["screenshot"]["id"])
    assert screenshot.owner == user


def test_upload_rejects_unsupported_format(api):
    response = api.post(
        reverse("chart_vision:screenshots"),
        {"image": uploaded_file(b"GIF89a", name="x.gif", content_type="image/gif")},
        format="multipart",
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "image_format_unsupported"


def test_upload_rejects_corrupted_image(api):
    response = api.post(
        reverse("chart_vision:screenshots"),
        {"image": uploaded_file(png_bytes()[:32])},
        format="multipart",
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "image_corrupted"


@override_settings(VISION_MAX_UPLOAD_BYTES=64)
def test_upload_rejects_oversized_image(api):
    response = api.post(
        reverse("chart_vision:screenshots"),
        {"image": uploaded_file(png_bytes())},
        format="multipart",
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "image_too_large"


def test_upload_with_analyze_runs_analysis(api, user):
    with _patch_provider():
        response = api.post(
            reverse("chart_vision:screenshots") + "?analyze=true",
            {"image": uploaded_file(png_bytes())},
            format="multipart",
        )
    assert response.status_code == 201
    analysis_id = response.json()["analysis_id"]
    analysis = ScreenshotAnalysis.objects.get(pk=analysis_id)
    assert analysis.status in {AnalysisStatus.COMPLETED, AnalysisStatus.PARTIAL}
    assert analysis.result  # a structured result was stored


def test_upload_is_owner_scoped_in_list(api, user, other_user):
    ChartScreenshot.objects.create(owner=other_user, status="accepted", image="x.png")
    make_screenshot(user)
    response = api.get(reverse("chart_vision:screenshots"))
    assert response.status_code == 200
    assert response.json()["count"] == 1


# ---------------------------------------------------------------------------
# Private image serving
# ---------------------------------------------------------------------------
def test_private_storage_url_is_not_public():
    from apps.chart_vision.storage import private_screenshot_storage

    with pytest.raises(ValueError):
        private_screenshot_storage.url("anything.png")


def test_image_endpoint_streams_bytes_to_owner(api, user):
    screenshot = make_screenshot(user)
    response = api.get(reverse("chart_vision:screenshot-image", args=[screenshot.pk]))
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    content = b"".join(response.streaming_content)
    assert content.startswith(b"\x89PNG")


def test_image_endpoint_hides_other_users_screenshot(api, other_user):
    screenshot = make_screenshot(other_user)
    response = api.get(reverse("chart_vision:screenshot-image", args=[screenshot.pk]))
    assert response.status_code == 404


def test_analysis_detail_hides_other_users_analysis(api, other_user):
    screenshot = make_screenshot(other_user)
    analysis, _ = get_or_create_analysis(screenshot)
    response = api.get(reverse("chart_vision:analysis-detail", args=[analysis.pk]))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Analyze dedupe
# ---------------------------------------------------------------------------
def test_analyze_deduplicates_in_flight_jobs(api, user):
    screenshot = make_screenshot(user)
    url = reverse("chart_vision:screenshot-analyze", args=[screenshot.pk])
    with mock.patch("apps.chart_vision.tasks.analyze_screenshot_task.delay") as delay:
        first = api.post(url)
        second = api.post(url)
    assert first.status_code == 202
    assert second.status_code == 202
    assert ScreenshotAnalysis.objects.filter(screenshot=screenshot).count() == 1
    assert delay.call_count == 1  # second request did not enqueue a duplicate


def test_analyze_returns_already_analyzed_for_completed(api, user):
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    analysis.status = AnalysisStatus.COMPLETED
    analysis.save(update_fields=["status"])
    with mock.patch("apps.chart_vision.tasks.analyze_screenshot_task.delay") as delay:
        response = api.post(reverse("chart_vision:screenshot-analyze", args=[screenshot.pk]))
    assert response.status_code == 200
    assert delay.call_count == 0


def test_analyze_requeues_failed_analysis(api, user):
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    analysis.status = AnalysisStatus.FAILED
    analysis.error_code = "provider_error"
    analysis.save(update_fields=["status", "error_code"])
    with mock.patch("apps.chart_vision.tasks.analyze_screenshot_task.delay") as delay:
        response = api.post(reverse("chart_vision:screenshot-analyze", args=[screenshot.pk]))
    assert response.status_code == 202
    assert delay.call_count == 1
    analysis.refresh_from_db()
    assert analysis.status == AnalysisStatus.QUEUED


def test_analyze_recovers_a_stuck_running_analysis(api, user):
    """A RUNNING row whose worker died must not block the screenshot forever."""
    from datetime import timedelta

    from django.utils import timezone

    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    ScreenshotAnalysis.objects.filter(pk=analysis.pk).update(
        status=AnalysisStatus.RUNNING,
        started_at=timezone.now() - timedelta(seconds=100000),
    )
    with mock.patch("apps.chart_vision.tasks.analyze_screenshot_task.delay") as delay:
        response = api.post(reverse("chart_vision:screenshot-analyze", args=[screenshot.pk]))
    assert response.status_code == 202
    assert delay.call_count == 1
    analysis.refresh_from_db()
    assert analysis.status == AnalysisStatus.QUEUED


# ---------------------------------------------------------------------------
# Detail / history / status
# ---------------------------------------------------------------------------
def test_analysis_detail_returns_structured_output(api, user):
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    with _patch_provider():
        from apps.chart_vision.services.screenshot_analyzer import ScreenshotAnalyzer

        ScreenshotAnalyzer().analyze(screenshot, analysis)
    response = api.get(reverse("chart_vision:analysis-detail", args=[analysis.pk]))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["result"]["chart_metadata"]["instrument"] == "EURUSD"
    assert body["observations"]
    assert body["patterns"]
    assert body["price_zones"]


def test_status_endpoint(api, user):
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    response = api.get(reverse("chart_vision:status", args=[analysis.pk]))
    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_history_lists_and_filters(api, user):
    for status in (AnalysisStatus.COMPLETED, AnalysisStatus.FAILED):
        screenshot = make_screenshot(user)
        analysis, _ = get_or_create_analysis(screenshot)
        analysis.status = status
        analysis.save(update_fields=["status"])

    response = api.get(reverse("chart_vision:history"))
    assert response.status_code == 200
    assert response.json()["count"] == 2

    filtered = api.get(reverse("chart_vision:history"), {"status": "failed"})
    assert filtered.json()["count"] == 1


def test_history_is_owner_scoped(api, user, other_user):
    other = make_screenshot(other_user)
    get_or_create_analysis(other)
    mine = make_screenshot(user)
    get_or_create_analysis(mine)
    response = api.get(reverse("chart_vision:history"))
    assert response.json()["count"] == 1
