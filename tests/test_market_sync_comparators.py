"""Unit tests for the candle, structure, price, feed and freshness comparators.

These are pure/deterministic: no MT5 terminal and no network are involved.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from apps.chart_vision.constants import CandleClassification, SizeBand
from apps.market_sync.constants import (
    CandleMatch,
    FeedCompatibilityStatus,
    FreshnessStatus,
    PriceComparisonMethod,
    StructureAgreement,
)
from apps.market_sync.services.candle_comparator import CandleComparator
from apps.market_sync.services.dto import AlignmentResult, InstrumentMatch
from apps.market_sync.services.feed_compatibility import FeedCompatibilityAssessor
from apps.market_sync.services.freshness_validator import FreshnessValidator
from apps.market_sync.services.price_level_comparator import (
    PriceLevelComparator,
    parse_price_labels,
)
from apps.market_sync.services.structure_comparator import StructureComparator
from tests.sync_fakes import CONFIG, Price, flat_prices, uptrend_prices

ANCHOR = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


def _alignment(index_to_time: dict[int, datetime]) -> AlignmentResult:
    return AlignmentResult(
        anchor=ANCHOR,
        source="visible_timestamp",
        confidence=0.9,
        uncertain=False,
        mt5_open_times=index_to_time,
    )


def _shot(**overrides) -> dict:
    candle = {
        "index": 0,
        "position": "middle",
        "classification": CandleClassification.BULLISH,
        "body_size": SizeBand.LARGE,
        "upper_wick": SizeBand.SMALL,
        "lower_wick": SizeBand.SMALL,
        "high_px": 100,
        "low_px": 200,
        "confidence": 0.8,
    }
    candle.update(overrides)
    return candle


class CandleComparatorTests(SimpleTestCase):
    def setUp(self):
        self.comparator = CandleComparator(CONFIG)
        # Strong bullish candle: large body, tiny wicks.
        self.bullish = Price(open=1.0000, high=1.0100, low=1.0000, close=1.0090)

    def test_matching_candle(self):
        comparison = self.comparator.compare(
            [_shot()], {ANCHOR: self.bullish}, _alignment({0: ANCHOR})
        )
        record = comparison.alignments[0]
        self.assertEqual(record.match_result, CandleMatch.MATCHED)
        self.assertTrue(record.direction_match)
        self.assertTrue(record.body_match)
        self.assertTrue(record.wick_match)
        self.assertEqual(comparison.matched_count, 1)
        self.assertEqual(comparison.direction_agreement, 1.0)

    def test_direction_disagreement(self):
        comparison = self.comparator.compare(
            [_shot(classification=CandleClassification.BEARISH)],
            {ANCHOR: self.bullish},
            _alignment({0: ANCHOR}),
        )
        record = comparison.alignments[0]
        self.assertFalse(record.direction_match)
        self.assertEqual(record.match_result, CandleMatch.MISMATCHED)
        self.assertEqual(comparison.direction_agreement, 0.0)

    def test_wick_disagreement(self):
        comparison = self.comparator.compare(
            [_shot(upper_wick=SizeBand.LARGE)],
            {ANCHOR: self.bullish},
            _alignment({0: ANCHOR}),
        )
        record = comparison.alignments[0]
        self.assertFalse(record.wick_match)
        self.assertEqual(record.match_result, CandleMatch.MISMATCHED)

    def test_unaligned_candle_has_no_mt5_interval(self):
        comparison = self.comparator.compare([_shot()], {ANCHOR: self.bullish}, _alignment({}))
        record = comparison.alignments[0]
        self.assertEqual(record.match_result, CandleMatch.UNALIGNED)
        self.assertEqual(comparison.unaligned_count, 1)
        self.assertIsNone(comparison.direction_agreement)

    def test_insufficient_detail_candle(self):
        comparison = self.comparator.compare(
            [
                _shot(
                    classification=CandleClassification.UNKNOWN,
                    body_size=SizeBand.UNKNOWN,
                    upper_wick=SizeBand.UNKNOWN,
                    lower_wick=SizeBand.UNKNOWN,
                    high_px=None,
                    low_px=None,
                )
            ],
            {ANCHOR: self.bullish},
            _alignment({0: ANCHOR}),
        )
        record = comparison.alignments[0]
        self.assertEqual(record.match_result, CandleMatch.INSUFFICIENT)

    def test_doji_classification(self):
        doji = Price(open=1.0000, high=1.0010, low=0.9990, close=1.0001)
        comparison = self.comparator.compare(
            [_shot(classification=CandleClassification.DOJI, body_size=SizeBand.SMALL)],
            {ANCHOR: doji},
            _alignment({0: ANCHOR}),
        )
        self.assertEqual(comparison.alignments[0].mt5_direction, CandleClassification.DOJI)
        self.assertTrue(comparison.alignments[0].direction_match)


class StructureComparatorTests(SimpleTestCase):
    def setUp(self):
        self.comparator = StructureComparator(CONFIG)

    def test_uptrend_agreement(self):
        result = self.comparator.compare(
            {
                "trend": "uptrend",
                "higher_highs": True,
                "higher_lows": True,
                "lower_highs": False,
                "lower_lows": False,
                "consolidation": False,
            },
            uptrend_prices(),
            overlap_candles=len(uptrend_prices()),
        )
        self.assertEqual(result.agreement, StructureAgreement.AGREE)
        self.assertEqual(result.comparable_items, 6)
        self.assertEqual(result.agreeing_items, 6)
        self.assertEqual(result.mt5_trend, "uptrend")

    def test_structure_disagreement(self):
        result = self.comparator.compare(
            {
                "trend": "downtrend",
                "higher_highs": False,
                "higher_lows": False,
                "lower_highs": True,
                "lower_lows": True,
                "consolidation": False,
            },
            uptrend_prices(),
            overlap_candles=len(uptrend_prices()),
        )
        self.assertEqual(result.agreement, StructureAgreement.DISAGREE)

    def test_insufficient_overlap_is_not_an_agreement(self):
        result = self.comparator.compare({"trend": "uptrend"}, uptrend_prices(), overlap_candles=3)
        self.assertEqual(result.agreement, StructureAgreement.INSUFFICIENT)

    def test_ranging_series(self):
        result = self.comparator.compare(
            {"trend": "ranging", "consolidation": True},
            flat_prices(8),
            overlap_candles=8,
        )
        self.assertEqual(result.mt5_trend, "ranging")


class PriceLevelComparatorTests(SimpleTestCase):
    def setUp(self):
        self.comparator = PriceLevelComparator()
        self.candles = uptrend_prices()

    def test_parse_price_labels(self):
        self.assertEqual(parse_price_labels(["1.0850", "$1,0900", "", "x"]), [1.085, 10900.0])

    def test_numeric_axis_match(self):
        result = self.comparator.compare(["0.9990", "1.0075"], self.candles)
        self.assertEqual(result.method, PriceComparisonMethod.NUMERIC_AXIS)
        self.assertTrue(result.matched)
        self.assertIsNotNone(result.offset)

    def test_no_labels_falls_back_to_relative_structure(self):
        result = self.comparator.compare([], self.candles)
        self.assertEqual(result.method, PriceComparisonMethod.RELATIVE_STRUCTURE)
        self.assertIsNone(result.matched)

    def test_offset_is_reported_not_applied(self):
        result = self.comparator.compare(["2.0000", "2.0085"], self.candles)
        self.assertEqual(result.method, PriceComparisonMethod.NUMERIC_AXIS)
        self.assertIsNotNone(result.offset)
        self.assertFalse(result.matched)


class FeedCompatibilityTests(SimpleTestCase):
    def setUp(self):
        self.assessor = FeedCompatibilityAssessor()

    @staticmethod
    def _match(**overrides) -> InstrumentMatch:
        base = {
            "screenshot_instrument": "EURUSD",
            "supported": True,
            "ambiguous": False,
            "canonical_instrument": "EURUSD",
            "broker_symbol": "EURUSD",
            "mapping_source": "broker_symbol_exact",
            "mapping_verified": True,
            "screenshot_is_otc": False,
            "reference_is_otc": False,
        }
        base.update(overrides)
        return InstrumentMatch(**base)

    def test_regular_regular_is_compatible(self):
        result = self.assessor.assess(self._match(), metadata_otc_status="regular")
        self.assertEqual(result.compatibility, FeedCompatibilityStatus.COMPATIBLE)

    def test_otc_screenshot_with_regular_reference_is_incompatible(self):
        result = self.assessor.assess(
            self._match(screenshot_is_otc=True, reference_is_otc=False),
            metadata_otc_status="otc",
        )
        self.assertEqual(result.compatibility, FeedCompatibilityStatus.INCOMPATIBLE_FEED)

    def test_regular_screenshot_with_otc_reference_is_incompatible(self):
        result = self.assessor.assess(self._match(screenshot_is_otc=False, reference_is_otc=True))
        self.assertEqual(result.compatibility, FeedCompatibilityStatus.INCOMPATIBLE_FEED)

    def test_otc_with_verified_otc_reference_is_compatible(self):
        result = self.assessor.assess(
            self._match(screenshot_is_otc=True, reference_is_otc=True, mapping_verified=True)
        )
        self.assertEqual(result.compatibility, FeedCompatibilityStatus.COMPATIBLE)

    def test_otc_reference_not_verified_is_incompatible(self):
        result = self.assessor.assess(
            self._match(screenshot_is_otc=True, reference_is_otc=True, mapping_verified=False)
        )
        self.assertEqual(result.compatibility, FeedCompatibilityStatus.INCOMPATIBLE_FEED)

    def test_unknown_designation_is_flagged(self):
        result = self.assessor.assess(self._match(screenshot_is_otc=None), metadata_otc_status=None)
        self.assertEqual(result.compatibility, FeedCompatibilityStatus.UNKNOWN)

    def test_unsupported_instrument_is_unknown(self):
        result = self.assessor.assess(self._match(supported=False, screenshot_is_otc=None))
        self.assertEqual(result.compatibility, FeedCompatibilityStatus.UNKNOWN)


class FreshnessValidatorTests(SimpleTestCase):
    def setUp(self):
        self.validator = FreshnessValidator(CONFIG)
        self.now = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)

    def test_fresh(self):
        result = self.validator.assess(
            anchor=self.now - timedelta(seconds=10),
            mt5_latest_open=self.now - timedelta(minutes=1),
            timeframe="M1",
            now=self.now,
        )
        self.assertEqual(result.status, FreshnessStatus.FRESH)
        self.assertFalse(result.entry_window_expired)

    def test_stale_screenshot(self):
        result = self.validator.assess(
            anchor=self.now - timedelta(hours=2),
            mt5_latest_open=self.now - timedelta(minutes=1),
            timeframe="M1",
            now=self.now,
        )
        self.assertEqual(result.status, FreshnessStatus.STALE_SCREENSHOT)

    def test_stale_mt5(self):
        result = self.validator.assess(
            anchor=self.now - timedelta(seconds=10),
            mt5_latest_open=self.now - timedelta(hours=3),
            timeframe="M1",
            now=self.now,
        )
        self.assertEqual(result.status, FreshnessStatus.STALE_MT5)

    def test_entry_window_expired(self):
        result = self.validator.assess(
            anchor=self.now - timedelta(minutes=5),
            mt5_latest_open=self.now - timedelta(minutes=1),
            timeframe="M1",
            now=self.now,
        )
        self.assertTrue(result.entry_window_expired)

    def test_unknown_anchor(self):
        result = self.validator.assess(
            anchor=None, mt5_latest_open=None, timeframe="M1", now=self.now
        )
        self.assertEqual(result.status, FreshnessStatus.UNKNOWN)
