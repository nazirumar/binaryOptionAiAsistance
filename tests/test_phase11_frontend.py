# tests/test_phase11_frontend.py
"""Phase 11 CP12 - frontend integration walkthrough.

Walks the documented UI chain end to end without rebuilding any page design:

  upload -> status fragment -> vision result -> sync (MT5) verification
  -> analysis history -> probability/calibration -> AI assistant list
  -> conversation detail (decision, NO TRADE reasons, probability notice,
  calibration status, evidence, MT5 verification) -> follow-up post
  -> cross-user isolation.

Everything runs offline: eager Celery, static vision double, mock reasoning
provider. Session-authenticated Django pages plus the DRF analyze endpoint
share the same walkthrough user.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.chart_vision.models import ChartScreenshot, ScreenshotAnalysis
from tests.factories import UserFactory
from tests.sync_fakes import (
    make_candle,
    make_symbol,
    now_floor,
    screenshot_candles,
    uptrend_prices,
    uptrend_structure,
)
from tests.vision_fakes import StaticVisionProvider, full_payload, png_bytes, uploaded_file

pytestmark = pytest.mark.django_db

ANALYZE_URL = "/api/assistant/analyze/"


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Keep DRF's locmem throttle cache from leaking across tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user():
    return UserFactory(username="cp12-ui")


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def api(user):
    auth = APIClient()
    auth.force_login(user)
    return auth


def _patch_vision(payload):
    """Deterministic offline vision for BOTH the dashboard and API paths."""
    return mock.patch(
        "apps.chart_vision.services.screenshot_analyzer.get_vision_provider",
        return_value=StaticVisionProvider(payload=payload),
    )


def _seed_mt5_series(symbol, prices, *, timeframe: str = "M1"):
    start = now_floor() - timedelta(minutes=len(prices) + 1)
    for index, price in enumerate(prices):
        make_candle(symbol, timeframe, start + timedelta(minutes=index), price)
    return start + timedelta(minutes=len(prices))


def _vision_payload(anchor, prices) -> dict:
    payload = full_payload(
        candles=screenshot_candles(prices),
        market_structure=uptrend_structure(),
    )
    metadata = dict(payload["chart_metadata"])
    metadata["screenshot_timestamp"] = anchor.isoformat().replace("+00:00", "Z")
    payload["chart_metadata"] = metadata
    return payload


# ---------------------------------------------------------------------------
# The complete UI chain (CP12)
# ---------------------------------------------------------------------------
def test_cp12_frontend_chain(auth_client, api, user):
    prices = uptrend_prices()
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    anchor = _seed_mt5_series(symbol, prices)
    payload = _vision_payload(anchor, prices)

    # --- upload -----------------------------------------------------------
    with _patch_vision(payload):
        upload = auth_client.post(
            reverse("dashboard:vision-upload"),
            {"image": uploaded_file(png_bytes())},
        )
    assert upload.status_code == 302
    screenshot = ChartScreenshot.objects.get(owner=user)

    # --- status fragment ---------------------------------------------------
    status = auth_client.get(reverse("dashboard:vision-status", args=[screenshot.pk]))
    assert status.status_code == 200
    status_html = status.content.decode()
    assert "Analysis" in status_html

    # --- vision result page ------------------------------------------------
    detail = auth_client.get(reverse("dashboard:vision-detail", args=[screenshot.pk]))
    assert detail.status_code == 200
    assert "Screenshot #" in detail.content.decode()

    # --- MT5 verification via the dashboard sync flow ----------------------
    analysis = ScreenshotAnalysis.objects.get(screenshot=screenshot)
    verify = auth_client.post(reverse("dashboard:sync-verify"), {"analysis_id": analysis.pk})
    assert verify.status_code == 302
    sync_pk = int(verify["Location"].rstrip("/").split("/")[-1])
    sync_page = auth_client.get(reverse("dashboard:sync-detail", args=[sync_pk]))
    assert sync_page.status_code == 200
    sync_html = sync_page.content.decode()
    # The aligned fixture must surface a real verified-alignment evidence page.
    assert "Verified alignment" in sync_html or "verified_alignment" in sync_html

    # --- analysis history + calibration pages render -----------------------
    analyses = auth_client.get(reverse("dashboard:analyses"))
    assert analyses.status_code == 200
    probability = auth_client.get(reverse("dashboard:probability"))
    assert probability.status_code == 200
    probability_html = probability.content.decode()
    assert "Calibration status" in probability_html

    # --- create the assistant conversation through the real API ------------
    with _patch_vision(payload):
        created = api.post(
            ANALYZE_URL,
            {"screenshot": uploaded_file(png_bytes()), "title": "cp12 chain"},
            format="multipart",
        )
    assert created.status_code == 201, created.content
    body = created.json()
    conversation_id = body["conversation"]["id"]
    summary = body["result_summary"]
    assert summary["direction"] in {"UP", "DOWN", "NO TRADE"}

    # --- conversation list page -------------------------------------------
    listing = auth_client.get(reverse("dashboard:assistant"))
    assert listing.status_code == 200
    list_html = listing.content.decode()
    assert "cp12 chain" in list_html
    assert summary["direction"] in list_html

    # --- conversation detail: result, evidence, calibration, probability ---
    page = auth_client.get(reverse("dashboard:conversation-detail", args=[conversation_id]))
    assert page.status_code == 200
    html = page.content.decode()
    assert summary["direction"] in html
    assert "Assessment" in html
    assert "MT5 verification" in html
    assert "Calibration" in html
    # No approved model in this run: the exact honest notice must be visible.
    assert summary["probability_value"] is None
    assert "Probability unavailable" in html
    assert "model not calibrated" in html
    # Server-derived evidence is on the page (labels + real values).
    assert "Evidence" in html
    assert "Sync status" in html
    assert summary["sync_evidence"]["sync_status"] in html
    assert "Yes" in html or "No" in html  # verified flag rendered as Yes/No
    assert summary["sync_evidence"]["candle_provenance"] in html

    # --- follow-up round trip ---------------------------------------------
    question = "Why did you return that decision?"
    follow = auth_client.post(
        reverse("dashboard:conversation-follow-up", args=[conversation_id]),
        {"message": question},
    )
    assert follow.status_code == 302
    after = auth_client.get(reverse("dashboard:conversation-detail", args=[conversation_id]))
    after_html = after.content.decode()
    assert question in after_html  # the user's message was persisted + rendered
    assert "Assistant" in after_html  # the evidence-grounded reply is present

    # --- NO TRADE reasons surface for an unverifiable submission -----------
    with _patch_vision(full_payload()):
        unverifiable = api.post(
            ANALYZE_URL,
            {"screenshot": uploaded_file(png_bytes()), "title": "cp12 unverifiable"},
            format="multipart",
        )
    assert unverifiable.status_code == 201
    ubody = unverifiable.json()
    usummary = ubody["result_summary"]
    assert usummary["direction"] == "NO TRADE"

    uview = auth_client.get(
        reverse("dashboard:conversation-detail", args=[ubody["conversation"]["id"]])
    )
    assert uview.status_code == 200
    uhtml = uview.content.decode()
    assert "NO TRADE" in uhtml
    assert "Decision reasons" in uhtml
    if usummary.get("primary_reason_code"):
        assert usummary["primary_reason_code"] in uhtml
    for warning in usummary.get("warnings") or []:
        assert warning in uhtml
    assert "Probability unavailable" in uhtml


# ---------------------------------------------------------------------------
# Isolation + empty states
# ---------------------------------------------------------------------------
def test_cp12_conversation_pages_are_owner_scoped(auth_client, api):
    with _patch_vision(full_payload()):
        created = api.post(
            ANALYZE_URL,
            {"screenshot": uploaded_file(png_bytes()), "title": "cp12 private"},
            format="multipart",
        )
    assert created.status_code == 201
    conversation_id = created.json()["conversation"]["id"]

    outsider = UserFactory(username="cp12-outsider")
    other = APIClient()
    other.force_login(outsider)

    assert (
        other.get(reverse("dashboard:conversation-detail", args=[conversation_id])).status_code
        == 404
    )
    assert (
        other.post(
            reverse("dashboard:conversation-follow-up", args=[conversation_id]),
            {"message": "sneaky"},
        ).status_code
        == 404
    )
    listing = other.get(reverse("dashboard:assistant"))
    assert listing.status_code == 200
    assert "cp12 private" not in listing.content.decode()


def test_cp12_empty_states(auth_client):
    listing = auth_client.get(reverse("dashboard:assistant"))
    assert listing.status_code == 200
    assert "No conversations yet" in listing.content.decode()


def test_cp12_pages_require_login(client):
    listing = client.get(reverse("dashboard:assistant"))
    assert listing.status_code == 302
    assert "login" in listing["Location"]
    detail = client.get(reverse("dashboard:conversation-detail", args=[1]))
    assert detail.status_code == 302
