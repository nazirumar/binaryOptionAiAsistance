# tests/test_strategy_engine_strategies.py
"""Tests for strategy families A, B, C (Phase 6)."""

from __future__ import annotations

from django.test import TestCase

from apps.strategy_engine.constants import EvaluationDirection, ProbabilityStatus
from apps.strategy_engine.services.bearish_evaluator import BearishEvaluator
from apps.strategy_engine.services.bullish_evaluator import BullishEvaluator
from apps.strategy_engine.services.evaluation_service import EvaluationService


class SRRejectionTest(TestCase):
    def test_bullish_sr_rejection(self):
        be = BullishEvaluator()
        evidence = [
            {
                "rule_id": "pa.sr.zone.support",
                "detector": "support_resistance",
                "direction": "bullish",
            },
            {
                "rule_id": "pa.sr.rejection.support",
                "detector": "support_resistance",
                "direction": "bullish",
            },
            {
                "rule_id": "pa.bsf.source_strength.bullish",
                "detector": "buyer_seller_failure",
                "direction": "bullish",
            },
        ]
        candidates = be.evaluate_all(evidence, [])
        self.assertTrue(any(c.direction == EvaluationDirection.UP for c in candidates))

    def test_bearish_sr_rejection(self):
        be = BearishEvaluator()
        evidence = [
            {
                "rule_id": "pa.sr.zone.resistance",
                "detector": "support_resistance",
                "direction": "bearish",
            },
            {
                "rule_id": "pa.sr.rejection.resistance",
                "detector": "support_resistance",
                "direction": "bearish",
            },
        ]
        candidates = be.evaluate_all(evidence, [])
        self.assertTrue(any(c.direction == EvaluationDirection.DOWN for c in candidates))


class BreakoutRetestTest(TestCase):
    def test_bullish_rbs(self):
        be = BullishEvaluator()
        evidence = [
            {
                "rule_id": "pa.sr.sbr_rbs.resistance_became_support",
                "detector": "support_resistance",
                "direction": "bullish",
            }
        ]
        candidates = be.evaluate_all(evidence, [])
        self.assertTrue(any(c.direction == EvaluationDirection.UP for c in candidates))

    def test_bearish_sbr(self):
        be = BearishEvaluator()
        evidence = [
            {
                "rule_id": "pa.sr.sbr_rbs.support_became_resistance",
                "detector": "support_resistance",
                "direction": "bearish",
            }
        ]
        candidates = be.evaluate_all(evidence, [])
        self.assertTrue(any(c.direction == EvaluationDirection.DOWN for c in candidates))


class LiquiditySweepTest(TestCase):
    def test_bullish_sweep(self):
        be = BullishEvaluator()
        evidence = [
            {
                "rule_id": "pa.sweep.low_sweep",
                "detector": "liquidity_sweeps",
                "direction": "bullish",
                "metrics": {"outcome": "rejection"},
            }
        ]
        candidates = be.evaluate_all(evidence, [])
        self.assertTrue(any(c.direction == EvaluationDirection.UP for c in candidates))

    def test_bearish_sweep(self):
        be = BearishEvaluator()
        evidence = [
            {
                "rule_id": "pa.sweep.high_sweep",
                "detector": "liquidity_sweeps",
                "direction": "bearish",
                "metrics": {"outcome": "rejection"},
            }
        ]
        candidates = be.evaluate_all(evidence, [])
        self.assertTrue(any(c.direction == EvaluationDirection.DOWN for c in candidates))


class ConflictingEvidenceTest(TestCase):
    def test_no_fabricated_probabilities(self):
        svc = EvaluationService()
        result = svc.evaluate(
            {
                "instrument": "EURUSD",
                "timeframe": "H1",
                "candles": [
                    {"open": 1.1, "high": 1.101, "low": 1.099, "close": 1.1005, "complete": True},
                ],
            }
        )
        self.assertEqual(
            result["statistical_probability_status"], ProbabilityStatus.UNAVAILABLE_UNCALIBRATED
        )
        result_str = str(result).lower()
        # No fabricated numerical probabilities - only status field
        self.assertNotIn("probability=0.5", result_str)
        self.assertNotIn("win rate", result_str)
        self.assertNotIn(
            "%", result_str.split("statistical_probability_status")[0]
        )  # Avoid % in status
        self.assertEqual(
            result["statistical_probability_status"], ProbabilityStatus.UNAVAILABLE_UNCALIBRATED
        )
        # Should return NO_TRADE due to insufficient data/conditions
        self.assertIn(result["direction"], [EvaluationDirection.NO_TRADE, "no_trade"])


class DeterministicEvaluationTest(TestCase):
    def test_deterministic_repeated(self):
        svc = EvaluationService()
        input_data = {
            "instrument": "EURUSD",
            "timeframe": "M15",
            "candles": [
                {"open": 1.1000, "high": 1.1010, "low": 1.0990, "close": 1.1005, "complete": True},
                {"open": 1.1005, "high": 1.1015, "low": 1.1000, "close": 1.1010, "complete": True},
            ],
        }
        r1 = svc.evaluate(input_data)
        r2 = svc.evaluate(input_data)
        self.assertEqual(r1["direction"], r2["direction"])
        self.assertEqual(r1["explanation"], r2["explanation"])
