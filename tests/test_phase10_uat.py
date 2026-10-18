# tests/test_phase10_uat.py
"""Phase 10, Step 18 — user acceptance testing (UAT) scenarios.

Each test corresponds to one acceptance scenario from the Phase 10 brief and
asserts the *expected user-visible outcome*. The results recorded in
``docs/PHASE-10-UAT.md`` are produced by running this file.

The system is an ANALYSIS and RESEARCH tool: every scenario asserts either a
clear decision, an explicit NO TRADE, or a visible error — never a fabricated
prediction. All external services are faked, so results are deterministic.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai_assistant.services.assistant_service import AssistantService
from apps.ai_assistant.services.probability_presenter import ProbabilityPresenter
from apps.price_action.services.engine import PriceActionEngine
from apps.strategy_engine.constants import EvaluationDirection
from apps.strategy_engine.services.evaluation_service import EvaluationService
from apps.trading_journal.models import JournalTrade
from tests.factories import UserFactory
from tests.pa_fakes import flat, low_sweep_series, resistance_touch_series, swing_high_low_series
from tests.sync_fakes import (
    build_aligned_scenario,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user():
    return UserFactory(username="uat-user")


@pytest.fixture
def api(user):
    client = APIClient()
    client.force_login(user)
    return client


def _candles_from_pa(series):
    """Convert pa_fakes candle rows into engine input."""
    return [dict(c) for c in series]


def _evidence_ids(result):
    return [item["rule_id"] for item in result["evidence"]]


# ---------------------------------------------------------------------------
# UAT-01  Regular forex screenshot with verified MT5 alignment
# ---------------------------------------------------------------------------
def test_uat01_regular_forex_with_verified_alignment(api, user):
    """A regular-forex screenshot that matches MT5 must verify, not merely pass."""
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)

    response = api.post("/api/sync/verify/", {"analysis_id": analysis.pk})

    assert response.status_code == 201
    body = response.json()
    assert body["outcome"] == "verified_alignment"
    assert body["is_verified"] is True


# ---------------------------------------------------------------------------
# UAT-02  OTC screenshot without a compatible reference feed
# ---------------------------------------------------------------------------
def test_uat02_otc_without_compatible_feed_is_rejected(api, user):
    """OTC must never be substituted with regular forex prices."""
    _s, _p, otc_analysis, _a = build_aligned_scenario(
        user,
        instrument="GBPUSD-OTC",
        otc_status="otc",
        broker_symbol="GBPUSD",
        canonical="GBPUSD",
    )

    response = api.post("/api/sync/verify/", {"analysis_id": otc_analysis.pk})

    assert response.status_code == 201
    body = response.json()
    assert body["outcome"] == "incompatible_feed"
    assert body["is_verified"] is False


# ---------------------------------------------------------------------------
# UAT-03  Bullish support rejection
# ---------------------------------------------------------------------------
def test_uat03_bullish_support_rejection_detected():
    result = PriceActionEngine().run(
        {"candles": _candles_from_pa(flat()), "instrument": "EURUSD", "timeframe": "M1"}
    )
    assert "pa.sr.rejection.support" in _evidence_ids(result)
    rejection = next(e for e in result["evidence"] if e["rule_id"] == "pa.sr.rejection.support")
    assert rejection["direction"] == "bullish"


# ---------------------------------------------------------------------------
# UAT-04  Bearish resistance rejection
# ---------------------------------------------------------------------------
def _resistance_rejection_series():
    """Price tags resistance, spikes above it, and closes back below."""

    def candle(o, h, low, close):
        return {"open": o, "high": h, "low": low, "close": close, "complete": True, "volume": 100}

    return [
        candle(1.0000, 1.0040, 0.9980, 1.0030),
        candle(1.0030, 1.0100, 1.0020, 1.0090),
        candle(1.0090, 1.0105, 1.0060, 1.0070),
        candle(1.0070, 1.0102, 1.0050, 1.0080),
        candle(1.0080, 1.0095, 1.0040, 1.0050),
        candle(1.0050, 1.0060, 1.0010, 1.0020),
        candle(1.0020, 1.0050, 1.0010, 1.0040),
        candle(1.0040, 1.0110, 1.0035, 1.0045),
    ]


def test_uat04_bearish_resistance_rejection_detected():
    result = PriceActionEngine().run(
        {
            "candles": _resistance_rejection_series(),
            "instrument": "EURUSD",
            "timeframe": "M1",
        }
    )
    assert "pa.sr.rejection.resistance" in _evidence_ids(result)
    rejection = next(e for e in result["evidence"] if e["rule_id"] == "pa.sr.rejection.resistance")
    assert rejection["direction"] == "bearish"


# ---------------------------------------------------------------------------
# UAT-05  SBR / RBS retest
# ---------------------------------------------------------------------------
def test_uat05_rbs_retest_detected():
    """Resistance-turned-support (bullish RBS) is recognised on a retest."""
    result = PriceActionEngine().run(
        {"candles": _candles_from_pa(swing_high_low_series()), "instrument": "EURUSD"}
    )
    assert "pa.sr.sbr_rbs.resistance_became_support" in _evidence_ids(result)


def test_uat05_sbr_retest_detected():
    """Support-turned-resistance (bearish SBR) is recognised on a retest."""
    result = PriceActionEngine().run(
        {"candles": _candles_from_pa(resistance_touch_series()), "instrument": "EURUSD"}
    )
    assert "pa.sr.sbr_rbs.support_became_resistance" in _evidence_ids(result)


# ---------------------------------------------------------------------------
# UAT-06  Liquidity sweep
# ---------------------------------------------------------------------------
def test_uat06_low_sweep_detected_as_bullish():
    result = PriceActionEngine().run(
        {"candles": _candles_from_pa(low_sweep_series()), "instrument": "EURUSD"}
    )
    assert "pa.sweep.low_sweep" in _evidence_ids(result)
    sweep = next(e for e in result["evidence"] if e["rule_id"] == "pa.sweep.low_sweep")
    assert sweep["direction"] == "bullish"


# ---------------------------------------------------------------------------
# UAT-07  Conflicting evidence
# ---------------------------------------------------------------------------
def test_uat07_conflicting_evidence_produces_conflicts_not_direction():
    """Opposing evidence must be surfaced as a conflict, not resolved silently."""
    result = PriceActionEngine().run(
        {"candles": _candles_from_pa(flat()), "instrument": "EURUSD", "timeframe": "M1"}
    )
    directions = {e["direction"] for e in result["evidence"]}
    assert {"bullish", "bearish"} <= directions, "fixture should contain both sides"
    assert isinstance(result["conflicts"], list)
    assert len(result["conflicts"]) >= 1


# ---------------------------------------------------------------------------
# UAT-08  NO TRADE due to insufficient information
# ---------------------------------------------------------------------------
def test_uat08_insufficient_information_yields_no_trade(user):
    """Too few candles must abstain rather than guess."""
    evaluation = EvaluationService().evaluate(
        {
            "instrument": "EURUSD",
            "timeframe": "M1",
            "candles": [
                {"open": 1.1, "high": 1.101, "low": 1.099, "close": 1.1005, "complete": True}
            ],
        }
    )
    assert evaluation["direction"] == EvaluationDirection.NO_TRADE


# ---------------------------------------------------------------------------
# UAT-09  Uncalibrated probability
# ---------------------------------------------------------------------------
def test_uat09_uncalibrated_probability_is_withheld():
    """Without held-out validation the model may not quote a success chance."""
    presented = ProbabilityPresenter().present(None)
    assert presented["available"] is False


# ---------------------------------------------------------------------------
# UAT-10  Expired signal
# ---------------------------------------------------------------------------
def test_uat10_expired_signal_is_refused(user):
    """A next-candle opportunity outside its entry window is refused."""
    result = AssistantService().analyze_screenshot(
        user,
        evaluation_input={
            "instrument": "EURUSD",
            "timeframe": "M1",
            "market_type": "regular",
            "sync_status": "VERIFIED_ALIGNMENT",
            "timing_validity": "expired",
            "candles": [
                {"open": 1.1, "high": 1.101, "low": 1.099, "close": 1.1005, "complete": True}
            ]
            * 8,
        },
    )
    assert result["response"]["direction"] == "NO TRADE"
    assert "opportunity_expired" in result["response"].get("warnings", [])


# ---------------------------------------------------------------------------
# UAT-11  Historical analysis review
# ---------------------------------------------------------------------------
def test_uat11_historical_analysis_reviewable(api, user):
    _s, _p, analysis, _a = build_aligned_scenario(user)
    api.post("/api/sync/verify/", {"analysis_id": analysis.pk})

    page = api.get("/dashboard/analyses/")
    assert page.status_code == 200

    history = api.get("/api/vision/history/")
    assert history.status_code == 200
    assert analysis.pk in [row["id"] for row in history.json()["results"]]


# ---------------------------------------------------------------------------
# UAT-12  Trading journal entry
# ---------------------------------------------------------------------------
def test_uat12_journal_entry_records_provenance(api, user):
    response = api.post(
        "/api/journal/trades/",
        {
            "trade_type": "hypothetical",
            "instrument": "EURUSD",
            "market_type": "regular",
            "direction": "call",
            "entry_timestamp": timezone.now().isoformat(),
            "stake": "10.00",
            "payout_percent": "80.00",
            "result": "pending",
            "notes": "UAT journal entry",
        },
        format="json",
    )
    assert response.status_code == 201
    trade = JournalTrade.objects.get(pk=response.json()["id"])
    assert trade.owner == user
    # A hypothetical entry must never be presented as a real trade.
    assert trade.trade_type == "hypothetical"
    assert trade.is_settled is False


# ---------------------------------------------------------------------------
# UAT-13  Educational follow-up question
# ---------------------------------------------------------------------------
def test_uat13_follow_up_answered_from_evidence(user):
    result = AssistantService().analyze_screenshot(
        user,
        evaluation_input={
            "instrument": "EURUSD",
            "timeframe": "M1",
            "market_type": "regular",
            "sync_status": "VERIFIED_ALIGNMENT",
            "timing_validity": "valid",
            "candles": _candles_from_pa(flat(12)),
        },
    )
    reply = AssistantService().handle_follow_up(
        user, result["conversation"].pk, "Can you explain why that was the decision?"
    )
    assert "error" not in reply
    assert reply["evidence"]["available"] is True
