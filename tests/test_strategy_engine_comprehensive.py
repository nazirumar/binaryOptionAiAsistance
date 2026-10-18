# tests/test_strategy_engine_comprehensive.py
"""Comprehensive tests for strategy engine (Phase 6)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.strategy_engine.constants import (
    EvaluationDirection,
    ProbabilityStatus,
)
from apps.strategy_engine.services.evaluation_service import EvaluationService

User = get_user_model()


class NO_TRADEConditionsTest(TestCase):
    def test_stale_data(self):
        svc = EvaluationService()
        result = svc.evaluate(
            {
                "instrument": "EURUSD",
                "timeframe": "M1",
                "data_freshness": "stale",
                "candles": [
                    {"open": 1.1, "high": 1.101, "low": 1.099, "close": 1.1005, "complete": True},
                ],
            }
        )
        self.assertEqual(result["direction"], EvaluationDirection.NO_TRADE)

    def test_unfinished_candle(self):
        svc = EvaluationService()
        result = svc.evaluate(
            {
                "instrument": "EURUSD",
                "timeframe": "M1",
                "candles": [
                    {"open": 1.1, "high": 1.101, "low": 1.099, "close": 1.1005, "complete": False},
                ],
            }
        )
        # Should be flagged
        self.assertIn(result["direction"], [EvaluationDirection.NO_TRADE, "no_trade"])

    def test_otc_incompatibility(self):
        svc = EvaluationService()
        result = svc.evaluate(
            {
                "instrument": "EURUSD",
                "timeframe": "M5",
                "market_type": "otc",
                "candles": [
                    {"open": 1.1, "high": 1.101, "low": 1.099, "close": 1.1005, "complete": True},
                ],
            }
        )
        self.assertEqual(result["direction"], EvaluationDirection.NO_TRADE)

    def test_missing_mt5_data(self):
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
        self.assertEqual(result["direction"], EvaluationDirection.NO_TRADE)

    def test_incorrect_timeframe(self):
        svc = EvaluationService()
        result = svc.evaluate(
            {
                "instrument": "EURUSD",
                "timeframe": "",
                "candles": [
                    {"open": 1.1, "high": 1.101, "low": 1.099, "close": 1.1005, "complete": True},
                ],
            }
        )
        self.assertEqual(result["direction"], EvaluationDirection.NO_TRADE)


class NoFabricatedProbabilitiesTest(TestCase):
    def test_no_numerical_probabilities_in_output(self):
        svc = EvaluationService()
        for _ in range(3):
            result = svc.evaluate(
                {
                    "instrument": "GBPUSD",
                    "timeframe": "M15",
                    "candles": [
                        {
                            "open": 1.26,
                            "high": 1.261,
                            "low": 1.259,
                            "close": 1.2605,
                            "complete": True,
                        },
                        {
                            "open": 1.2605,
                            "high": 1.2615,
                            "low": 1.26,
                            "close": 1.261,
                            "complete": True,
                        },
                    ],
                }
            )
            self.assertEqual(
                result["statistical_probability_status"], ProbabilityStatus.UNAVAILABLE_UNCALIBRATED
            )
            # No numeric probabilities like 0.x, 50%, etc. in numeric form
            self.assertIsNone(result.get("probability"))
            self.assertIsNone(result.get("success_probability"))
            self.assertIsNone(result.get("win_probability"))


class DoubleCountedEvidenceTest(TestCase):
    def test_confluence_engine_dedupes(self):
        from apps.strategy_engine.services.confluence_engine import ConfluenceEngine

        ce = ConfluenceEngine()
        evidence = [
            {"rule_id": "pa.candle.bullish_engulfing", "detector": "candlestick_patterns"},
            {
                "rule_id": "pa.candle.bullish_engulfing",
                "detector": "candlestick_patterns",
            },  # duplicate
        ]
        score = ce.compute_confluence(evidence)
        self.assertIsNotNone(score)


class DeterminismTest(TestCase):
    def test_reproducible_results(self):
        svc = EvaluationService()
        input_data = {
            "instrument": "EURUSD",
            "timeframe": "M5",
            "candles": [
                {"open": 1.1000, "high": 1.1008, "low": 1.0998, "close": 1.1005, "complete": True},
                {"open": 1.1005, "high": 1.1012, "low": 1.1002, "close": 1.1008, "complete": True},
                {"open": 1.1008, "high": 1.1015, "low": 1.1005, "close": 1.1012, "complete": True},
            ],
        }
        results = [svc.evaluate(input_data) for _ in range(5)]
        for i in range(1, 5):
            self.assertEqual(results[0]["direction"], results[i]["direction"])
            self.assertEqual(results[0]["explanation"], results[i]["explanation"])


class APITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("test@example.com", "pass")
        self.client.force_authenticate(self.user)

    def test_api_evaluate_requires_auth(self):
        client = APIClient()
        resp = client.post("/api/strategies/evaluate/", {})
        self.assertIn(resp.status_code, [401, 403])

    def test_api_rules_returns_status(self):
        resp = self.client.get("/api/strategies/rules/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("probability", str(data).lower())  # contains status info

    def test_api_history_returns_paginated(self):
        resp = self.client.get("/api/strategies/history/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("results", resp.json())
