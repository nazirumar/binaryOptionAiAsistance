# tests/test_strategy_engine_basic.py
"""Basic tests for strategy engine (Phase 6)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.strategy_engine.constants import (
    EvaluationDirection,
    InvalidationReasonCode,
    ProbabilityStatus,
)
from apps.strategy_engine.services.context_evaluator import ContextEvaluator
from apps.strategy_engine.services.evaluation_service import EvaluationService
from apps.strategy_engine.services.invalidation_engine import InvalidationEngine
from apps.strategy_engine.services.timing_validator import TimingValidator

User = get_user_model()


class ContextEvaluatorTest(TestCase):
    def test_uncertain_when_no_structure(self):
        ev = ContextEvaluator()
        result = ev.evaluate([], {})
        self.assertEqual(result, "uncertain")


class TimingValidatorTest(TestCase):
    def test_uncertain_with_no_candles(self):
        tv = TimingValidator()
        validity, _info = tv.validate_timing([], "M1", None)
        self.assertEqual(validity, "uncertain")


class InvalidationEngineTest(TestCase):
    def test_flags_missing_instrument_timeframe(self):
        class DummyInput:
            instrument = ""
            timeframe = ""
            sync_status = "verified_alignment"
            data_freshness = "fresh"
            warnings = []

        ie = InvalidationEngine()
        should, codes, _primary = ie.check_all(DummyInput(), "valid")
        self.assertTrue(should)
        self.assertIn(InvalidationReasonCode.UNCERTAIN_INSTRUMENT, codes)


class EvaluationServiceNoTradeTest(TestCase):
    def test_no_trade_with_insufficient_data(self):
        svc = EvaluationService()
        result = svc.evaluate(
            {
                "instrument": "EURUSD",
                "timeframe": "M1",
                "candles": [
                    {
                        "open": 1.1000,
                        "high": 1.1005,
                        "low": 1.0995,
                        "close": 1.1002,
                        "complete": True,
                    },
                ],
            }
        )
        self.assertEqual(result["direction"], EvaluationDirection.NO_TRADE)
        self.assertEqual(
            result["statistical_probability_status"], ProbabilityStatus.UNAVAILABLE_UNCALIBRATED
        )
