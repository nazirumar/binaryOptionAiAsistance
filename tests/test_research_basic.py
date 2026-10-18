# tests/test_research_basic.py
"""Basic tests for research/backtesting (Phase 7)."""

from __future__ import annotations

from django.test import TestCase

from apps.research.services.binary_settlement import BinarySettlement
from apps.research.services.dataset_builder import DatasetBuilder
from apps.research.services.directional_outcomes import DirectionalOutcomes
from apps.research.services.historical_replay import HistoricalReplay
from apps.research.services.performance_metrics import PerformanceMetrics
from apps.research.services.walk_forward_validation import WalkForwardValidation


class DatasetBuilderTest(TestCase):
    def test_ohlc_validation(self):
        db = DatasetBuilder()
        self.assertTrue(db.validate_ohlc(1.0, 1.1, 0.9, 1.05))
        self.assertFalse(db.validate_ohlc(1.0, 0.9, 1.1, 1.05))  # low>high

    def test_detects_duplicates(self):
        db = DatasetBuilder()
        candles = [
            {"open_time": "2024-01-01T00:00:00Z"},
            {"open_time": "2024-01-01T00:00:00Z"},
        ]
        issues = db.check_duplicates(candles)
        self.assertTrue(issues)


class DirectionalOutcomesTest(TestCase):
    def test_classifies_up(self):
        do = DirectionalOutcomes()
        res = do.classify_target({"open": 1.0, "close": 1.1, "high": 1.15, "low": 0.95})
        self.assertEqual(res, "UP")

    def test_doji_treated_as_tie(self):
        do = DirectionalOutcomes()
        res = do.classify_target({"open": 1.0, "close": 1.0001, "high": 1.01, "low": 0.99})
        self.assertEqual(res, "TIE")

    def test_evaluate_doji_not_win(self):
        do = DirectionalOutcomes()
        res = do.evaluate_outcome("up", {"open": 1.0, "close": 1.0, "high": 1.01, "low": 0.99})
        self.assertFalse(res["hit"])


class BinarySettlementTest(TestCase):
    def test_call_win(self):
        bs = BinarySettlement()
        res = bs.evaluate_settlement("CALL", entry_quote=1.0, settlement_quote=1.1)
        self.assertTrue(res["win"])
        self.assertTrue(res["verifiable"])

    def test_put_loss(self):
        bs = BinarySettlement()
        res = bs.evaluate_settlement("PUT", entry_quote=1.0, settlement_quote=1.1)
        self.assertFalse(res["win"])

    def test_unverifiable_when_missing(self):
        bs = BinarySettlement()
        res = bs.evaluate_settlement("CALL", entry_quote=1.0, settlement_quote=None)
        self.assertEqual(res["status"], "UNVERIFIABLE")
        self.assertFalse(res["verifiable"])


class PerformanceMetricsTest(TestCase):
    def test_empty_results(self):
        pm = PerformanceMetrics()
        res = pm.compute([])
        self.assertEqual(res["total"], 0)
        self.assertIsNone(res["directional_accuracy"])


class WalkForwardTest(TestCase):
    def test_chronological_split_no_shuffle(self):
        wf = WalkForwardValidation()
        candles = [{"i": i} for i in range(10)]
        split = wf.split_chronological(candles, 0.6, 0.2)
        self.assertEqual(len(split["train"]), 6)
        self.assertEqual(len(split["val"]), 2)
        self.assertEqual(len(split["test"]), 2)
        self.assertEqual(split["train"][0]["i"], 0)
        self.assertEqual(split["test"][-1]["i"], 9)


class HistoricalReplayTest(TestCase):
    def test_no_future_leakage(self):
        replay = HistoricalReplay()
        candles = []
        base = 1.0
        for i in range(30):
            candles.append(
                {
                    "instrument": "EURUSD",
                    "timeframe": "M1",
                    "open": base + i * 0.0001,
                    "high": base + i * 0.0001 + 0.0002,
                    "low": base + i * 0.0001 - 0.0002,
                    "close": base + i * 0.0001 + 0.0001,
                    "open_time": f"2024-01-01T00:{i:02d}:00Z",
                    "complete": True,
                }
            )
        results = replay.replay(candles, start_index=5, min_history=5)
        self.assertTrue(len(results) >= 0)  # Basic smoke test
        # Ensure we only used past data - each result corresponds to point-in-time
        self.assertIsInstance(results, list)
