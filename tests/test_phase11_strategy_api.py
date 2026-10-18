# tests/test_phase11_strategy_api.py
"""Phase 11 CP2 — the strategy evaluation API is real and forgery-proof.

Proves:

* ``POST /api/strategies/evaluate/`` runs the real ``EvaluationService``
  (no 501), persists the evaluation and returns it;
* **forged client verdicts cannot bypass safety**: request fields named
  ``sync_status`` / ``feed_compatibility`` / ``market_type`` /
  ``timing_validity`` are ignored — the decision uses only server-derived
  evidence, so a forged ``verified_alignment`` still yields NO TRADE;
* ownership is enforced (cross-user references 404/403);
* client candles must be timezone-offset; ambiguous clocks are rejected;
* client-supplied ``price_action_result`` never bypasses the price-action
  engine;
* the rules endpoint returns the persisted configuration.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.chart_vision.models import ScreenshotAnalysis
from apps.market_data.models import MarketCandle, MarketSymbol
from apps.market_sync.constants import (
    FeedCompatibilityStatus,
    FreshnessStatus,
    SessionStatus,
    SyncStatus,
)
from apps.market_sync.models import MarketSyncSession
from apps.strategy_engine.constants import EvaluationDirection
from apps.strategy_engine.models import StrategyEvaluation, StrategyRuleConfiguration

User = get_user_model()

EVALUATE_URL = "/api/strategies/evaluate/"


def _utc_candles(n: int = 8, base: float = 1.1000, start: datetime | None = None):
    """Completed M1 candles ending one minute before ``base_end``."""
    start = start or (datetime.now(tz=UTC) - timedelta(minutes=n + 2)).replace(
        second=0, microsecond=0
    )
    candles = []
    for i in range(n):
        o = base + i * 0.0002
        candles.append(
            {
                "open": round(o, 5),
                "high": round(o + 0.0005, 5),
                "low": round(o - 0.0005, 5),
                "close": round(o + 0.0003, 5),
                "open_time": (start + timedelta(minutes=i)).isoformat(),
                "close_time": (start + timedelta(minutes=i, seconds=59)).isoformat(),
                "complete": True,
            }
        )
    return candles


def _make_analysis(user, username_suffix: str = "") -> ScreenshotAnalysis:
    from tests.vision_fakes import make_screenshot

    screenshot = make_screenshot(user)
    return ScreenshotAnalysis.objects.create(
        screenshot=screenshot,
        owner=user,
        status="completed",
        idempotency_key=f"phase11-cp2-{user.pk}-{screenshot.pk}{username_suffix}",
        chart_metadata={"instrument": "EURUSD", "timeframe": "M1", "market_type": "forex"},
    )


def _make_sync_session(
    user,
    *,
    outcome: str = SyncStatus.VERIFIED_ALIGNMENT,
    analysis: ScreenshotAnalysis | None = None,
    status_value: str = SessionStatus.COMPLETED,
) -> MarketSyncSession:
    return MarketSyncSession.objects.create(
        owner=user,
        analysis=analysis,
        status=status_value,
        outcome=outcome,
        canonical_instrument="EURUSD",
        mt5_timeframe="M1",
        market_type="forex",
        feed_compatibility=FeedCompatibilityStatus.COMPATIBLE
        if outcome == SyncStatus.VERIFIED_ALIGNMENT
        else FeedCompatibilityStatus.INCOMPATIBLE_FEED,
        freshness_status=FreshnessStatus.FRESH,
    )


class EvaluateApiTests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user("cp2-alpha", "pw")
        self.user_b = User.objects.create_user("cp2-beta", "pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user_a)

    def test_endpoint_is_implemented_and_persists(self):
        resp = self.client.post(
            EVALUATE_URL,
            {"instrument": "EURUSD", "timeframe": "M1", "candles": _utc_candles()},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertIn(
            body["direction"],
            (EvaluationDirection.UP, EvaluationDirection.DOWN, EvaluationDirection.NO_TRADE),
        )
        self.assertTrue(StrategyEvaluation.objects.filter(owner=self.user_a).exists())
        # No sync session -> the dual-source policy forces NO TRADE.
        self.assertEqual(body["direction"], EvaluationDirection.NO_TRADE)
        self.assertIn("incompatible_sync", body["reason_codes"])
        self.assertFalse(body["sync_evidence"]["verified"])

    def test_forged_verdict_fields_cannot_bypass_safety(self):
        """A client claiming verified alignment must still get NO TRADE."""
        resp = self.client.post(
            EVALUATE_URL,
            {
                "instrument": "EURUSD",
                "timeframe": "M1",
                "candles": _utc_candles(),
                # All forged "trusted" fields:
                "sync_status": SyncStatus.VERIFIED_ALIGNMENT,
                "feed_compatibility": FeedCompatibilityStatus.COMPATIBLE,
                "data_freshness": FreshnessStatus.FRESH,
                "market_type": "forex",
                "timing_validity": "valid",
                "calibration_approved": True,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["direction"], EvaluationDirection.NO_TRADE)
        self.assertIn("incompatible_sync", body["reason_codes"])
        self.assertEqual(body["sync_status"], "")
        self.assertFalse(body["sync_evidence"]["verified"])

    def test_client_price_action_result_cannot_fabricate_evidence(self):
        resp = self.client.post(
            EVALUATE_URL,
            {
                "instrument": "EURUSD",
                "timeframe": "M1",
                "candles": _utc_candles(),
                "price_action_result": {
                    "evidence": [
                        {
                            "rule_id": "fabricated.bullish.engulfing",
                            "detector": "manual",
                            "direction": "bullish",
                        }
                    ],
                    "context": {"bias": "bullish"},
                },
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertNotIn("fabricated.bullish.engulfing", str(resp.content))

    def test_ambiguous_client_clock_rejected(self):
        resp = self.client.post(
            EVALUATE_URL,
            {
                "instrument": "EURUSD",
                "timeframe": "M1",
                "candles": _utc_candles(),
                "now": "2026-03-01T10:00:00",  # no offset
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("now", str(resp.content))

    def test_offset_client_clock_accepted(self):
        resp = self.client.post(
            EVALUATE_URL,
            {
                "instrument": "EURUSD",
                "timeframe": "M1",
                "candles": _utc_candles(),
                "now": (datetime.now(tz=UTC) + timedelta(hours=1)).isoformat(),  # +01:00
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_client_candles_without_offset_rejected(self):
        candles = _utc_candles()
        candles[0]["open_time"] = "2026-03-01T10:00:00"  # naive
        resp = self.client.post(
            EVALUATE_URL,
            {"instrument": "EURUSD", "timeframe": "M1", "candles": candles},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "invalid_candles")

    def test_unverified_sync_session_still_no_trade(self):
        analysis = _make_analysis(self.user_a)
        session = _make_sync_session(
            self.user_a,
            outcome=SyncStatus.INCOMPATIBLE_FEED,
            analysis=analysis,
        )
        resp = self.client.post(
            EVALUATE_URL,
            {
                "screenshot_analysis_id": analysis.pk,
                "sync_session_id": session.pk,
                "candles": _utc_candles(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["direction"], EvaluationDirection.NO_TRADE)
        self.assertEqual(body["sync_status"], SyncStatus.INCOMPATIBLE_FEED)
        self.assertFalse(body["sync_evidence"]["verified"])

    def test_stale_freshness_verdict_forces_no_trade(self):
        """CP2 regression: the real freshness tokens (stale_screenshot /
        stale_m5) must trigger the STALE_DATA invalidation, not only the
        legacy bare 'stale'."""
        from apps.market_sync.constants import SyncStatus as SS

        analysis = _make_analysis(self.user_a)
        session = MarketSyncSession.objects.create(
            owner=self.user_a,
            analysis=analysis,
            status=SessionStatus.COMPLETED,
            outcome=SS.VERIFIED_ALIGNMENT,
            canonical_instrument="EURUSD",
            mt5_timeframe="M1",
            market_type="forex",
            feed_compatibility=FeedCompatibilityStatus.COMPATIBLE,
            freshness_status=FreshnessStatus.STALE_SCREENSHOT,
        )
        resp = self.client.post(
            EVALUATE_URL,
            {
                "screenshot_analysis_id": analysis.pk,
                "sync_session_id": session.pk,
                "candles": _utc_candles(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["direction"], EvaluationDirection.NO_TRADE)
        self.assertIn("stale_data", body["reason_codes"])

    def test_verified_alignment_unblocks_the_engine_gate(self):
        """With a real VERIFIED_ALIGNMENT session the sync gate passes: the
        INCOMPATIBLE_SYNC reason must be absent (the decision then depends on
        the price-action evidence, never on a client claim)."""
        analysis = _make_analysis(self.user_a)
        session = _make_sync_session(self.user_a, analysis=analysis)
        resp = self.client.post(
            EVALUATE_URL,
            {
                "screenshot_analysis_id": analysis.pk,
                "sync_session_id": session.pk,
                "candles": _utc_candles(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["sync_status"], SyncStatus.VERIFIED_ALIGNMENT)
        self.assertTrue(body["sync_evidence"]["verified"])
        self.assertNotIn("incompatible_sync", body["reason_codes"])

    def test_stored_mt5_candles_preferred_over_client(self):
        symbol = MarketSymbol.objects.create(canonical="EURUSD", broker_symbol="EURUSD")
        now = datetime.now(tz=UTC).replace(second=0, microsecond=0)
        for i in range(8):
            open_time = now - timedelta(minutes=8 - i)
            MarketCandle.objects.create(
                symbol=symbol,
                timeframe="M1",
                open_time=open_time,
                open=1.1 + i * 0.0002,
                high=1.1005 + i * 0.0002,
                low=1.0995 + i * 0.0002,
                close=1.1002 + i * 0.0002,
                is_complete=True,
            )
        analysis = _make_analysis(self.user_a)
        session = _make_sync_session(self.user_a, analysis=analysis)
        resp = self.client.post(
            EVALUATE_URL,
            {
                "screenshot_analysis_id": analysis.pk,
                "sync_session_id": session.pk,
                "candles": _utc_candles(),  # must be ignored in favour of stored
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["sync_evidence"]["candle_provenance"], "stored_mt5")

    def test_cross_user_analysis_reference_is_404(self):
        analysis = _make_analysis(self.user_b, "-b")
        self.client.force_authenticate(self.user_a)
        resp = self.client.post(
            EVALUATE_URL,
            {"screenshot_analysis_id": analysis.pk, "candles": _utc_candles()},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_cross_user_sync_session_reference_is_403(self):
        session = _make_sync_session(self.user_b)
        self.client.force_authenticate(self.user_a)
        resp = self.client.post(
            EVALUATE_URL,
            {"sync_session_id": session.pk, "candles": _utc_candles()},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_missing_evidence_is_404(self):
        resp = self.client.post(
            EVALUATE_URL,
            {"screenshot_analysis_id": 999999, "candles": _utc_candles()},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_history_is_owner_scoped(self):
        _make_sync_session(self.user_b)  # unrelated
        StrategyEvaluation.objects.create(
            owner=self.user_b, instrument="GBPUSD", timeframe="M1", direction="NO TRADE"
        )
        StrategyEvaluation.objects.create(
            owner=self.user_a, instrument="EURUSD", timeframe="M1", direction="NO TRADE"
        )
        resp = self.client.get("/api/strategies/history/")
        self.assertEqual(resp.status_code, 200)
        results = resp.json()["results"]
        self.assertTrue(all(item["instrument"] == "EURUSD" for item in results))

    def test_rules_returns_persisted_configuration(self):
        StrategyRuleConfiguration.objects.create(
            name="baseline",
            is_active=True,
            config_version="v2",
            rule_version="r7",
            config={"min_evidence": 2},
            description="core rules",
        )
        resp = self.client.get("/api/strategies/rules/")
        self.assertEqual(resp.status_code, 200)
        rules = resp.json()["rules"]
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["rule_version"], "r7")
        self.assertEqual(rules[0]["config"]["min_evidence"], 2)


@pytest.mark.django_db
class TestTrustedBuilderUnit:
    def test_builder_never_reads_client_verdicts(self):
        """The builder signature has no parameters for trusted verdicts at
        all — a forged payload cannot even reach it."""
        import inspect

        from apps.strategy_engine.services.trusted_input_builder import TrustedInputBuilder

        params = set(inspect.signature(TrustedInputBuilder.build).parameters)
        for forbidden in (
            "sync_status",
            "feed_compatibility",
            "data_freshness",
            "market_type",
            "timing_validity",
        ):
            assert forbidden not in params
