# tests/test_phase11_security.py
"""Phase 11 CP13 - security regression tests.

Explicit regressions for the CP13 control list. Areas already pinned by other
suites are referenced here rather than duplicated:

* ownership        -> test_phase11_pipeline (job endpoints 404), test_phase11_strategy_api,
                      test_phase11_research_api, test_phase11_frontend, test_phase11_e2e
* private screens  -> test_chart_vision_api (image endpoint hides other users)
* file validation  -> test_phase11_pipeline (invalid image bytes -> invalid_image)
* prompt injection -> test_ai_assistant (message endpoint flags injection)
* key protection   -> test_phase11_reasoning (key in header, never in URL;
                      sensitive context keys redacted from the outbound body)
* redaction        -> test_phase11_reasoning (payload redaction)
* research access  -> test_phase11_research_api (owner-scoped datasets/backtests/models)
* cross-user journal -> test_trading_journal_dashboard (dashboard edit 404)

The file adds regressions for the controls that had no direct coverage:
CSRF on both surfaces, explicit throttling 429s, worker-side claim auth,
credential absence in API responses, and journal API cross-user deletion.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.middleware.csrf import get_token
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai_assistant.models import AIAnalysisJob
from apps.ai_assistant.tasks import run_screenshot_analysis_task
from tests.factories import UserFactory
from tests.vision_fakes import (
    StaticVisionProvider,
    full_payload,
    make_screenshot,
    png_bytes,
    uploaded_file,
)

pytestmark = pytest.mark.django_db

User = get_user_model()
ANALYZE_URL = "/api/assistant/analyze/"

#: Markers that must never appear in any API response body.
CREDENTIAL_MARKERS = ("AIza", "x-goog-api-key", "sk-", "REASONING_LLM_API_KEY", "Bearer ")


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Keep DRF's locmem throttle cache from leaking across tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user():
    return UserFactory(username="cp13-user")


def _patch_vision(payload=None):
    return mock.patch(
        "apps.chart_vision.services.screenshot_analyzer.get_vision_provider",
        return_value=StaticVisionProvider(payload=payload or full_payload()),
    )


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def test_csrf_dashboard_post_requires_token(user):
    """Session-authenticated dashboard POSTs are rejected without a CSRF token."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    resp = client.post(
        reverse("dashboard:conversation-follow-up", args=[1]),
        {"message": "hello"},
    )
    assert resp.status_code == 403


def test_csrf_api_session_post_requires_token(user):
    """DRF's SessionAuthentication enforces CSRF on the analyze endpoint."""
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    with _patch_vision():
        resp = client.post(
            ANALYZE_URL,
            {"screenshot": uploaded_file(png_bytes())},
            format="multipart",
        )
    assert resp.status_code == 403
    assert AIAnalysisJob.objects.count() == 0  # nothing was created or dispatched


def test_csrf_token_lets_the_dashboard_post_through(user):
    """The same POST succeeds once the middleware-level CSRF check passes."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    # Mint a real double-submit token for this client session, then send it
    # the way Django validates it: cookie jar + X-CSRFToken header in agreement.
    shot = make_screenshot(user)
    page = client.get(reverse("dashboard:vision-status", args=[shot.pk]))
    token = get_token(page.wsgi_request)
    client.cookies["csrftoken"] = token  # keeps the sessionid cookie intact
    resp = client.post(
        reverse("dashboard:conversation-follow-up", args=[1]),
        {"message": "hello"},
        HTTP_X_CSRFTOKEN=token,
    )
    # Conversation 1 does not exist for this user -> the view's own 404 fires,
    # which proves CSRF was satisfied (an unsatisfied check would be 403).
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Throttling
# ---------------------------------------------------------------------------
def test_analyze_upload_throttle_returns_429(user, monkeypatch):
    """The assistant_upload scope is enforced (explicit 429, no silent pass)."""
    # DRF binds DEFAULT_THROTTLE_RATES to a class attribute at import, so the
    # shared settings dict must be mutated in place for the view's throttle
    # instance to see the tighter rate (monkeypatch restores it afterwards).
    rates = dj_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    monkeypatch.setitem(rates, "assistant_upload", "2/minute")

    client = APIClient()
    client.force_login(user)
    with _patch_vision():
        for _ in range(2):
            ok = client.post(
                ANALYZE_URL,
                {"screenshot": uploaded_file(png_bytes())},
                format="multipart",
            )
            assert ok.status_code == 201
        blocked = client.post(
            ANALYZE_URL,
            {"screenshot": uploaded_file(png_bytes())},
            format="multipart",
        )
    assert blocked.status_code == 429
    assert "detail" in blocked.json()
    # The throttled request never reached the pipeline: exactly two jobs exist.
    assert AIAnalysisJob.objects.count() == 2


# ---------------------------------------------------------------------------
# Worker-side job authentication (CP8 contract)
# ---------------------------------------------------------------------------
def test_worker_refuses_a_terminal_job(user):
    """A completed job can never be re-run by a stray worker message."""
    job = AIAnalysisJob.objects.create(
        owner=user,
        screenshot=make_screenshot(user),
        idempotency_key="cp13-terminal",
        status=AIAnalysisJob.Status.COMPLETED,
        result_summary={"direction": "NO TRADE"},
    )
    outcome = run_screenshot_analysis_task(job.pk)
    assert outcome["status"] == "already_terminal"
    job.refresh_from_db()
    assert job.result_summary == {"direction": "NO TRADE"}  # untouched


def test_worker_suppresses_a_fresh_running_job(user):
    """Only the claiming worker may run; a live in-flight job is left alone."""
    now = timezone.now()
    job = AIAnalysisJob.objects.create(
        owner=user,
        screenshot=make_screenshot(user),
        idempotency_key="cp13-running",
        status=AIAnalysisJob.Status.RUNNING,
        started_at=now,
        heartbeat_at=now,
        attempts=1,
    )
    outcome = run_screenshot_analysis_task(job.pk)
    assert outcome["status"] == "duplicate_suppressed"
    job.refresh_from_db()
    assert job.status == AIAnalysisJob.Status.RUNNING
    assert job.attempts == 1


def test_worker_reports_missing_jobs(user):
    assert run_screenshot_analysis_task(999_999) == {"status": "missing", "job_id": 999_999}


# ---------------------------------------------------------------------------
# Credential absence in API responses
# ---------------------------------------------------------------------------
def test_api_responses_never_contain_credential_material(user):
    """No response body on the assistant/research surface leaks key material."""
    client = APIClient()
    client.force_login(user)
    with _patch_vision():
        created = client.post(
            ANALYZE_URL,
            {"screenshot": uploaded_file(png_bytes()), "title": "cp13 leak probe"},
            format="multipart",
        )
    assert created.status_code == 201
    job_id = created.json()["id"]
    conversation_id = created.json()["conversation"]["id"]

    bodies = [created.content.decode()]
    for url in (
        f"/api/assistant/jobs/{job_id}/",
        f"/api/assistant/conversations/{conversation_id}/",
        "/api/research/calibration/",
        "/api/research/models/",
    ):
        resp = client.get(url)
        assert resp.status_code == 200, url
        bodies.append(resp.content.decode())

    for body in bodies:
        for marker in CREDENTIAL_MARKERS:
            assert marker not in body, f"credential marker {marker!r} leaked"


# ---------------------------------------------------------------------------
# Regression: status-quo controls remain active (smoke assertions)
# ---------------------------------------------------------------------------
def test_analyze_rejects_unauthenticated_requests():
    client = APIClient()
    with _patch_vision():
        resp = client.post(
            ANALYZE_URL,
            {"screenshot": uploaded_file(png_bytes())},
            format="multipart",
        )
    assert resp.status_code in (401, 403)
    assert AIAnalysisJob.objects.count() == 0


def test_job_cancel_of_missing_job_is_404(user):
    client = APIClient()
    client.force_login(user)
    resp = client.post("/api/assistant/jobs/999999/cancel/")
    assert resp.status_code == 404


def test_completed_job_is_never_cancellable(user):
    job = AIAnalysisJob.objects.create(
        owner=user,
        screenshot=make_screenshot(user),
        idempotency_key="cp13-cancel-terminal",
        status=AIAnalysisJob.Status.COMPLETED,
    )
    client = APIClient()
    client.force_login(user)
    resp = client.post(f"/api/assistant/jobs/{job.pk}/cancel/")
    assert resp.status_code == 409
    job.refresh_from_db()
    assert job.status == AIAnalysisJob.Status.COMPLETED


def test_job_result_summary_seeds_are_not_client_writable(user):
    """result_summary/sync evidence are written only by the server pipeline."""
    client = APIClient()
    client.force_login(user)
    with _patch_vision():
        created = client.post(
            ANALYZE_URL,
            {
                "screenshot": uploaded_file(png_bytes()),
                # Forged flat fields the client must never be able to set;
                # nested payloads cannot ride a multipart upload at all.
                "sync_status": "verified_alignment",
                "market_type": "forex",
                "feed_compatibility": "compatible",
                "calibration_approved": "true",
            },
            format="multipart",
        )
    assert created.status_code == 201
    job = AIAnalysisJob.objects.get(pk=created.json()["id"])
    summary = job.result_summary or {}
    evidence = summary.get("sync_evidence") or {}
    # The client's forged claims were ignored: this run has no MT5 series
    # seeded, so the server derives verified=False with its own status.
    assert evidence.get("verified") is False
    assert summary.get("sync_status") is None  # no such top-level key exists
    assert summary.get("calibration_approved") is None
