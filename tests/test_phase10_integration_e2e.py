# tests/test_phase10_integration_e2e.py
"""Phase 10, Step 9 — deterministic end-to-end integration tests.

Walks the complete documented workflow end to end:

  sign in -> upload screenshot -> image validation -> vision extraction ->
  instrument/timeframe identified -> MT5 data requested -> feed compatibility
  verified -> price-action detectors -> strategy evaluation -> timing rules ->
  probability only when calibrated -> assistant explanation -> dashboard ->
  analysis history -> evidence-grounded follow-up -> journal entry

Every external service is faked: no network, no MT5 terminal and no live LLM.
The purpose is to prove the *wiring* of all nine phases works together and that
the honesty/data-integrity guards hold at each step. Live round trips are
covered by the separate (optional) live suite, not here.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient

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


#: Every current-price API call resets throttle state so the single test does
#: not trip the vision/sync/journal rate limits while walking the workflow.
@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user():
    return UserFactory(username="e2e-operator")


@pytest.fixture
def api(user):
    client = APIClient()
    client.force_login(user)
    return client


def _patch_vision(payload):
    """Replace the vision provider with a deterministic, offline double."""
    return mock.patch(
        "apps.chart_vision.services.screenshot_analyzer.get_vision_provider",
        return_value=StaticVisionProvider(payload=payload),
    )


def _seed_mt5_series(symbol, prices, *, timeframe: str = "M1"):
    """Write an MT5 candle series ending one minute ago.

    Mirrors the real worker's layout (completed candles, newest closed minute)
    and returns the anchor: the open of the candle that follows the series,
    which is what a screenshot timestamp must match to be aligned.
    """
    start = now_floor() - timedelta(minutes=len(prices) + 1)
    for index, price in enumerate(prices):
        make_candle(symbol, timeframe, start + timedelta(minutes=index), price)
    return start + timedelta(minutes=len(prices))


def _vision_payload(anchor, prices) -> dict:
    """A schema-valid vision payload aligned to the seeded MT5 series."""
    payload = full_payload(
        candles=screenshot_candles(prices),
        market_structure=uptrend_structure(),
    )
    metadata = dict(payload["chart_metadata"])
    metadata["screenshot_timestamp"] = anchor.isoformat().replace("+00:00", "Z")
    payload["chart_metadata"] = metadata
    return payload


def _candle_dicts(prices):
    """MT5-shaped OHLC dicts for the strategy engine."""
    return [
        {
            "open": p.open,
            "high": p.high,
            "low": p.low,
            "close": p.close,
            "complete": True,
        }
        for p in prices
    ]


# ---------------------------------------------------------------------------
# The complete workflow
# ---------------------------------------------------------------------------
def test_full_analysis_workflow_end_to_end(api, user):
    prices = uptrend_prices()
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    anchor = _seed_mt5_series(symbol, prices)

    # --- Step 1: the user signs in ---------------------------------------
    assert api.get("/dashboard/").status_code == 200

    # --- Steps 2-5: upload, validation, vision extraction, identification -
    payload = _vision_payload(anchor, prices)
    with _patch_vision(payload):
        upload = api.post(
            "/api/vision/screenshots/?analyze=true",
            {"image": uploaded_file(png_bytes())},
            format="multipart",
        )
    assert upload.status_code == 201, upload.content
    body = upload.json()

    # Step 3: image validation succeeded.
    assert body["screenshot"]["status"] == "accepted"
    assert body["screenshot"]["image_format"] == "png"

    # Step 4: the vision provider produced structured observations.
    analysis = ScreenshotAnalysis.objects.get(pk=body["analysis_id"])
    assert analysis.status == "completed"
    observations = analysis.result
    assert observations["candles"], "vision returned no candle observations"

    # Step 5: instrument and timeframe were identified.
    assert analysis.chart_metadata["instrument"] == "EURUSD"
    assert analysis.chart_metadata["timeframe"] == "M1"
    assert observations["chart_metadata"]["instrument"] == "EURUSD"

    # --- Steps 6-7: MT5 data requested, feed compatibility verified -------
    verify = api.post("/api/sync/verify/", {"analysis_id": analysis.pk})
    assert verify.status_code == 201, verify.content
    sync = verify.json()
    assert sync["outcome"] == "verified_alignment"
    assert sync["is_verified"] is True
    assert sync["mt5_broker_symbol"] == "EURUSD"

    # --- Steps 8-12: detectors, evaluation, timing, probability, assistant -
    evaluation_input = {
        "instrument": "EURUSD",
        "timeframe": "M1",
        "market_type": "regular",
        "sync_status": "VERIFIED_ALIGNMENT",
        "timing_validity": "valid",
        "candles": _candle_dicts(prices),
    }
    result = AssistantService().analyze_screenshot(user, evaluation_input=evaluation_input)
    response = result["response"]

    # Step 8/9: the deterministic engines ran and produced a decision.
    assert response["direction"] in {"UP", "DOWN", "NO TRADE"}
    evaluation = StrategyEvaluation.objects.filter(owner=user).order_by("-created_at").first()
    assert evaluation is not None, "no strategy evaluation was persisted"
    assert evaluation.sync_status == "VERIFIED_ALIGNMENT"

    # Step 10: timing rules were applied.
    assert evaluation.timing_validity == "valid"

    # Step 11: no calibrated model exists, so no probability may be quoted.
    assert response.get("probability_value") is None
    assert (
        response.get("probability_calibration_status")
        in {
            "uncalibrated",
            "unavailable",
            None,
        }
        or "calibrat" in str(response.get("probability_calibration_status", "")).lower()
    )

    # Step 12: the assistant produced a non-empty explanation.
    conversation = result["conversation"]
    assistant_message = conversation.messages.filter(role="assistant").first()
    assert assistant_message is not None and assistant_message.content.strip()

    # --- Steps 13-14: dashboard and analysis history ----------------------
    assert api.get("/dashboard/").status_code == 200
    assert api.get("/dashboard/analyses/").status_code == 200

    history = api.get("/api/vision/history/")
    assert history.status_code == 200
    history_ids = [row["id"] for row in history.json()["results"]]
    assert analysis.pk in history_ids, "analysis missing from history"

    evaluations = api.get("/api/strategies/history/")
    assert evaluations.status_code == 200
    assert evaluation.pk in [row["id"] for row in evaluations.json()["results"]]

    # --- Step 15: a follow-up is answered from stored evidence ------------
    follow_up = AssistantService().handle_follow_up(
        user, conversation.pk, "Why did you return that decision?"
    )
    assert "error" not in follow_up
    assert follow_up["evidence"]["available"] is True, "follow-up had no stored evidence"

    # --- Step 16: the user records a journal entry ------------------------
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
            "notes": "Paper entry recorded from the E2E run.",
        },
        format="json",
    )
    assert entry.status_code == 201, entry.content
    trade = JournalTrade.objects.get(pk=entry.json()["id"])
    assert trade.owner == user
    assert trade.trade_type == "demo", "demo trade must never be labelled real"


# ---------------------------------------------------------------------------
# Isolation across the full stack
# ---------------------------------------------------------------------------
def test_workflow_is_scoped_to_the_owner(api, user):
    """A second user sees none of the first user's workflow artefacts."""
    other = User.objects.create_user(username="e2e-outsider", password="pw")
    prices = uptrend_prices()
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    anchor = _seed_mt5_series(symbol, prices)

    payload = _vision_payload(anchor, prices)
    with _patch_vision(payload):
        upload = api.post(
            "/api/vision/screenshots/?analyze=true",
            {"image": uploaded_file(png_bytes())},
            format="multipart",
        )
    analysis_id = upload.json()["analysis_id"]

    # The other user cannot read the analysis, the sync result, the
    # evaluation or the journal entry of the first user.
    other_client = APIClient()
    other_client.force_login(other)

    assert other_client.get(f"/api/vision/analyses/{analysis_id}/").status_code == 404
    assert other_client.post("/api/sync/verify/", {"analysis_id": analysis_id}).status_code in (
        403,
        404,
    )
    history = other_client.get("/api/vision/history/").json()["results"]
    assert analysis_id not in [row["id"] for row in history]
