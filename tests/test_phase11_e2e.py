# tests/test_phase11_e2e.py
"""Phase 11 CP10 — end-to-end integration of the CP1 pipeline flow.

Walks the *new* documented workflow (Phase 11 rewiring, not a rebuild):

  sign in -> POST /api/assistant/analyze/ (multipart screenshot)
  -> durable job created (unique idempotency key)
  -> vision extraction (offline double) -> server-side MT5 verification
  -> trusted evidence -> strategy evaluation -> timing -> probability gates
  -> structured result persisted on the job
  -> GET job status -> conversation follow-up from stored evidence
  -> research endpoints -> dashboard -> journal entry -> cross-user isolation

No network, no MT5 terminal, no live LLM. The live reasoning smoke lives in
tests/test_phase11_reasoning.py behind REASONING_LLM_LIVE_TEST=1; MT5 live
exercising is NOT EXECUTED in this environment (no terminal) and is recorded
as such in docs/PHASE-11-LIVE-VALIDATION.md. Nothing here is silently mocked
under a LIVE label.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.ai_assistant.models import AIAnalysisJob
from apps.ai_assistant.services.assistant_service import AssistantService
from apps.chart_vision.models import ScreenshotAnalysis
from apps.strategy_engine.models import StrategyEvaluation
from apps.trading_journal.models import JournalTrade
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

User = get_user_model()

ANALYZE_URL = "/api/assistant/analyze/"


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Keep DRF's locmem throttle cache from leaking across tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user():
    return UserFactory(username="phase11-e2e")


@pytest.fixture
def api(user):
    client = APIClient()
    client.force_login(user)
    return client


def _patch_vision(payload):
    """Replace the pipeline's vision stage with a deterministic offline double."""
    from apps.chart_vision.services.screenshot_analyzer import ScreenshotAnalyzer

    return mock.patch(
        "apps.ai_assistant.services.screenshot_pipeline.ScreenshotAnalyzer",
        lambda: ScreenshotAnalyzer(provider=StaticVisionProvider(payload=payload)),
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
# The complete Phase 11 workflow
# ---------------------------------------------------------------------------
def test_phase11_pipeline_workflow_end_to_end(api, user):
    prices = uptrend_prices()
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    anchor = _seed_mt5_series(symbol, prices)

    # --- Step 1: sign in ---------------------------------------------------
    assert api.get("/dashboard/").status_code == 200

    # --- Step 2: submit a real screenshot to the assistant -----------------
    payload = _vision_payload(anchor, prices)
    with _patch_vision(payload):
        upload = api.post(
            ANALYZE_URL,
            {"screenshot": uploaded_file(png_bytes()), "title": "e2e chart"},
            format="multipart",
        )
    assert upload.status_code == 201, upload.content
    body = upload.json()

    # --- Step 3: one durable job, executed eagerly in tests ----------------
    job = AIAnalysisJob.objects.get(pk=body["id"])
    assert job.owner == user
    assert body["status"] == AIAnalysisJob.Status.COMPLETED, body.get("error_message")
    assert job.session_id is not None

    summary = body["result_summary"]
    assert summary["direction"] in {"UP", "DOWN", "NO TRADE"}

    # --- Steps 4-5: server-side verification + trusted evidence ------------
    evidence = summary["sync_evidence"]
    assert set(evidence) >= {
        "sync_session_id",
        "sync_status",
        "verified",
        "feed_compatibility",
        "freshness_status",
        "candle_provenance",
    }
    # The MT5 series was seeded and the vision payload is aligned, so the
    # pipeline's own verification must have succeeded — nothing is asserted
    # "verified" from a client; this came from the server-side sync service.
    assert evidence["verified"] is True, evidence
    assert evidence["sync_status"] == "verified_alignment"
    assert evidence["candle_provenance"] in {"stored_mt5", "client_supplied"}
    assert evidence["candle_provenance"] == "stored_mt5", (
        "aligned pipeline must prefer stored MT5 candles"
    )

    # --- Steps 6-7: evaluation persisted with server-derived verdicts ------
    evaluation = StrategyEvaluation.objects.filter(owner=user).order_by("-created_at").first()
    assert evaluation is not None, "no strategy evaluation persisted"
    assert evaluation.sync_status == "verified_alignment"
    assert evaluation.timing_validity in {"valid", "expired", "future_invalid", "uncertain"}

    # --- Step 8: no calibrated model => no probability, exact notice -------
    assert summary["probability_value"] is None
    assert summary["calibration_status"] == "uncalibrated"
    assert "Probability unavailable" in summary["explanation"]

    # --- Step 9: job status endpoint returns the same result ---------------
    status = api.get(f"/api/assistant/jobs/{job.pk}/")
    assert status.status_code == 200
    assert status.json()["result_summary"]["direction"] == summary["direction"]

    # --- Step 10: conversation + evidence-grounded follow-up ---------------
    conversation = body["conversation"]
    assert conversation["id"] == job.conversation_id
    follow_up = AssistantService().handle_follow_up(
        user, conversation["id"], "Why did you return that decision?"
    )
    assert "error" not in follow_up
    assert follow_up["evidence"]["available"] is True

    # --- Step 11: analysis records are linked and visible in history ------
    assert conversation["screenshot_analysis"] is not None
    analysis = ScreenshotAnalysis.objects.get(pk=conversation["screenshot_analysis"])
    assert analysis.status in {"completed", "partial", "insufficient_evidence"}
    history = api.get("/api/vision/history/")
    assert history.status_code == 200
    assert analysis.pk in [row["id"] for row in history.json()["results"]]

    # --- Step 12: research endpoints read the same stored truth ------------
    calibration = api.get("/api/research/calibration/")
    assert calibration.status_code == 200
    assert calibration.json()["calibrated"] is False
    assert calibration.json()["status"] == "unavailable_uncalibrated"

    performance = api.get("/api/research/performance/")
    assert performance.status_code == 200
    assert "runs_total" in performance.json()

    # --- Step 13: dashboard renders with the new artefacts -----------------
    assert api.get("/dashboard/analyses/").status_code == 200

    # --- Step 14: journal entry closes the loop ----------------------------
    entry = api.post(
        "/api/journal/trades/",
        {
            "trade_type": "demo",
            "instrument": "EURUSD",
            "market_type": "regular",
            "direction": "call",
            "entry_timestamp": anchor.isoformat().replace("+00:00", "Z"),
            "entry_quote": "1.1000",
            "stake": "10.00",
            "payout_percent": "80.00",
            "result": "win",
            "settlement_quote": "1.1005",
            "notes": "Paper entry recorded from the Phase 11 E2E run.",
        },
        format="json",
    )
    assert entry.status_code == 201, entry.content
    trade = JournalTrade.objects.get(pk=entry.json()["id"])
    assert trade.owner == user
    assert trade.trade_type == "demo"


# ---------------------------------------------------------------------------
# Idempotency across the full stack
# ---------------------------------------------------------------------------
def test_double_submit_in_the_same_session_replays_the_same_job(api, user):
    prices = uptrend_prices()
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    anchor = _seed_mt5_series(symbol, prices)
    payload = _vision_payload(anchor, prices)

    with _patch_vision(payload):
        first = api.post(
            ANALYZE_URL, {"screenshot": uploaded_file(png_bytes())}, format="multipart"
        )
    assert first.status_code == 201
    job_id = first.json()["id"]

    # The screenshot is referenced by id for the replay (same screenshot,
    # same mode => same idempotency key => no second job, no second vision
    # call, HTTP 200 replay).
    replay = api.post(
        ANALYZE_URL,
        {"screenshot_id": first.json()["screenshot"]},
        format="multipart",
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == job_id
    assert AIAnalysisJob.objects.count() == 1


# ---------------------------------------------------------------------------
# Isolation across the full stack
# ---------------------------------------------------------------------------
def test_phase11_workflow_is_scoped_to_the_owner(api, user):
    other = User.objects.create_user(username="phase11-outsider", password="pw")
    prices = uptrend_prices()
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    anchor = _seed_mt5_series(symbol, prices)
    payload = _vision_payload(anchor, prices)

    with _patch_vision(payload):
        upload = api.post(
            ANALYZE_URL, {"screenshot": uploaded_file(png_bytes())}, format="multipart"
        )
    assert upload.status_code == 201
    job_id = upload.json()["id"]
    conversation_id = upload.json()["conversation"]["id"]

    other_client = APIClient()
    other_client.force_login(other)

    # Job, cancel, conversation and research data are all owner-scoped.
    assert other_client.get(f"/api/assistant/jobs/{job_id}/").status_code == 404
    assert other_client.post(f"/api/assistant/jobs/{job_id}/cancel/").status_code == 404
    assert other_client.get(f"/api/assistant/conversations/{conversation_id}/").status_code == 404
    assert other_client.get("/api/research/backtests/").json()["count"] == 0
    assert other_client.get("/api/research/models/").json()["count"] == 0
    assert other_client.get("/api/strategies/history/").json()["results"] == []


# ---------------------------------------------------------------------------
# Unverifiable path stays honest end to end (no MT5 series seeded)
# ---------------------------------------------------------------------------
def test_unverifiable_submission_ends_no_trade_with_honest_evidence(api, user):
    payload = full_payload()  # aligned to nothing: no MT5 series seeded
    with _patch_vision(payload):
        upload = api.post(
            ANALYZE_URL, {"screenshot": uploaded_file(png_bytes())}, format="multipart"
        )
    assert upload.status_code == 201
    summary = upload.json()["result_summary"]
    assert summary["direction"] == "NO TRADE"
    assert summary["sync_evidence"]["verified"] is False
    assert summary["probability_value"] is None
    assert "Probability unavailable" in summary["explanation"]
