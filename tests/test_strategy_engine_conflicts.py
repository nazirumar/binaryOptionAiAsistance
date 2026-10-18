# tests/test_strategy_engine_conflicts.py
"""Tests for conflicting evidence and NO_TRADE reason codes."""

from __future__ import annotations

from django.test import TestCase

from apps.strategy_engine.constants import EvaluationDirection, InvalidationReasonCode
from apps.strategy_engine.services.conflict_resolver import ConflictResolver
from apps.strategy_engine.services.evaluation_service import EvaluationService


class ConflictResolverTest(TestCase):
    def test_detects_opposing_evidence(self):
        cr = ConflictResolver()
        evidence = [
            {"direction": "bullish", "rule_id": "r1"},
            {"direction": "bearish", "rule_id": "r2"},
        ]
        contradictions = cr.identify_strong_contradictions(evidence)
        self.assertTrue(contradictions)
        self.assertTrue(cr.has_strong_contradiction(contradictions))

    def test_no_contradiction_when_same_direction(self):
        cr = ConflictResolver()
        evidence = [
            {"direction": "bullish", "rule_id": "r1"},
            {"direction": "bullish", "rule_id": "r2"},
        ]
        contradictions = cr.identify_strong_contradictions(evidence)
        self.assertFalse(contradictions)


class MissingConditionsTest(TestCase):
    def test_no_trade_when_missing_conditions(self):
        svc = EvaluationService()
        result = svc.evaluate(
            {
                "instrument": "EURUSD",
                "timeframe": "H1",
                "candles": [
                    {"open": 1.1, "high": 1.105, "low": 1.095, "close": 1.102, "complete": True},
                ],
            }
        )
        self.assertEqual(result["direction"], EvaluationDirection.NO_TRADE)
        self.assertIn(result["primary_reason_code"], [InvalidationReasonCode.INCOMPATIBLE_SYNC])


class APIAuthTest(TestCase):
    def test_evaluate_endpoint_auth(self):
        from rest_framework.test import APIClient

        client = APIClient()
        resp = client.post("/api/strategies/evaluate/", {"candles": []})
        self.assertIn(resp.status_code, [401, 403])  # authentication required

    def test_evaluate_with_auth(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        User = get_user_model()
        client = APIClient()
        user = User.objects.create_user("u@test.com", "p")
        client.force_authenticate(user)
        # Phase 11 CP2: the endpoint is implemented. With no stored MT5
        # candles and no client candles there is nothing to evaluate -> 400
        # with an explicit machine-readable code (never a 501 stub).
        resp = client.post("/api/strategies/evaluate/", {"candles": [], "instrument": "EURUSD"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "no_reference_candles")


class NO_TRADEReasonCodesTest(TestCase):
    def test_reason_codes_present_for_no_trade(self):
        svc = EvaluationService()
        result = svc.evaluate(
            {
                "instrument": "EURUSD",
                "timeframe": "M5",
                "candles": [
                    {"open": 1.1, "high": 1.101, "low": 1.099, "close": 1.1005, "complete": True},
                ],
            }
        )
        if result["direction"] == EvaluationDirection.NO_TRADE:
            self.assertIsNotNone(result.get("primary_reason_code"))
            self.assertTrue(len(result.get("reason_codes", [])) > 0)
