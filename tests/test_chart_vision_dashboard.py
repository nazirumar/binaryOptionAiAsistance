"""Tests for the chart-vision dashboard pages."""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.chart_vision.dashboard import DISCLAIMER
from apps.chart_vision.models import ChartScreenshot, ScreenshotAnalysis
from tests.factories import UserFactory
from tests.vision_fakes import make_screenshot, png_bytes, uploaded_file

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return UserFactory(username="dash-analyst")


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


def test_vision_page_requires_login(client):
    response = client.get(reverse("dashboard:vision"))
    assert response.status_code == 302
    assert "login" in response["Location"]


def test_vision_page_renders_with_disclaimer(auth_client):
    response = auth_client.get(reverse("dashboard:vision"))
    assert response.status_code == 200
    content = response.content.decode()
    assert DISCLAIMER in content
    assert "Upload a screenshot" in content


def test_dashboard_upload_creates_screenshot_and_analysis(auth_client, user):
    response = auth_client.post(
        reverse("dashboard:vision-upload"),
        {"image": uploaded_file(png_bytes())},
    )
    assert response.status_code == 302
    screenshot = ChartScreenshot.objects.get(owner=user)
    assert response["Location"] == reverse("dashboard:vision-detail", args=[screenshot.pk])
    analysis = ScreenshotAnalysis.objects.get(screenshot=screenshot)
    # Eager Celery + mock provider: the job ran during the request.
    assert analysis.status in {"completed", "partial", "insufficient_evidence"}


def test_dashboard_upload_rejects_bad_file(auth_client, user):
    response = auth_client.post(
        reverse("dashboard:vision-upload"),
        {"image": uploaded_file(b"not an image", name="x.png")},
        follow=True,
    )
    assert response.status_code == 200
    assert not ChartScreenshot.objects.filter(owner=user).exists()
    assert "rejected" in response.content.decode().lower()


def test_dashboard_upload_without_file(auth_client, user):
    response = auth_client.post(reverse("dashboard:vision-upload"), {}, follow=True)
    assert response.status_code == 200
    assert not ChartScreenshot.objects.exists()


def test_vision_detail_renders(auth_client, user):
    screenshot = make_screenshot(user)
    response = auth_client.get(reverse("dashboard:vision-detail", args=[screenshot.pk]))
    assert response.status_code == 200
    content = response.content.decode()
    assert DISCLAIMER in content
    assert reverse("chart_vision:screenshot-image", args=[screenshot.pk]) in content


def test_vision_detail_hides_other_users_screenshot(auth_client, user):
    other = UserFactory(username="dash-other")
    screenshot = make_screenshot(other)
    response = auth_client.get(reverse("dashboard:vision-detail", args=[screenshot.pk]))
    assert response.status_code == 404


def test_vision_status_fragment(auth_client, user):
    screenshot = make_screenshot(user)
    response = auth_client.get(reverse("dashboard:vision-status", args=[screenshot.pk]))
    assert response.status_code == 200


def test_dashboard_index_links_to_vision(auth_client):
    response = auth_client.get(reverse("dashboard:index"))
    assert response.status_code == 200
    assert reverse("dashboard:vision") in response.content.decode()
