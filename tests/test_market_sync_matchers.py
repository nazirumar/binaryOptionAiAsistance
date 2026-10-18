"""Unit tests for the instrument, timeframe and timestamp matchers (Steps 3-6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.test import TestCase

from apps.market_data.constants import MappingStatus
from apps.market_sync.constants import AlignmentSource, MappingSource
from apps.market_sync.services.instrument_matcher import (
    has_otc_token,
    resolve_instrument,
)
from apps.market_sync.services.timeframe_matcher import match_timeframe, parse_timeframe
from apps.market_sync.services.timestamp_aligner import (
    TimestampAligner,
    floor_to_grid,
    last_completed_open,
    parse_timestamp,
)
from tests.sync_fakes import make_symbol


class InstrumentMatcherTests(TestCase):
    def test_exact_canonical_mapping_is_resolved(self):
        make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
        match = resolve_instrument("EURUSD")
        self.assertTrue(match.supported)
        self.assertFalse(match.ambiguous)
        self.assertEqual(match.canonical_instrument, "EURUSD")
        self.assertEqual(match.broker_symbol, "EURUSD")
        self.assertEqual(match.mapping_source, MappingSource.BROKER_SYMBOL_EXACT)
        self.assertTrue(match.mapping_verified)

    def test_broker_suffix_mapping_is_resolved_explicitly(self):
        make_symbol(canonical="EURUSD", broker_symbol="EURUSDm")
        match = resolve_instrument("EURUSDm")
        self.assertTrue(match.supported)
        self.assertEqual(match.canonical_instrument, "EURUSD")
        self.assertEqual(match.broker_symbol, "EURUSDm")
        self.assertEqual(match.mapping_source, MappingSource.BROKER_SYMBOL_EXACT)

    def test_broker_prefix_dot_mapping_is_resolved(self):
        make_symbol(canonical="GBPUSD", broker_symbol="GBPUSD.pro")
        match = resolve_instrument("GBPUSD.pro")
        self.assertTrue(match.supported)
        self.assertEqual(match.canonical_instrument, "GBPUSD")
        self.assertEqual(match.broker_symbol, "GBPUSD.pro")

    def test_similar_name_is_not_inferred_as_equivalent(self):
        # A mapping exists for EURUSD only; a near-miss symbol must not match it.
        make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
        match = resolve_instrument("EURUSDT")
        self.assertFalse(match.supported)
        self.assertFalse(match.ambiguous)

    def test_missing_instrument_is_rejected(self):
        match = resolve_instrument("UNKNOWN")
        self.assertFalse(match.supported)
        self.assertTrue(match.reasons)

    def test_known_instrument_without_mapping_is_unsupported(self):
        match = resolve_instrument("EURUSD")
        self.assertFalse(match.supported)
        self.assertEqual(match.canonical_instrument, "EURUSD")

    def test_ambiguous_mappings_are_rejected(self):
        make_symbol(canonical="EURUSD", broker_symbol="EURUSD.a")
        make_symbol(canonical="EURUSD", broker_symbol="EURUSD.b")
        match = resolve_instrument("EURUSD")
        self.assertFalse(match.supported)
        self.assertTrue(match.ambiguous)

    def test_unverified_mapping_is_flagged(self):
        make_symbol(
            canonical="EURUSD",
            broker_symbol="EURUSD",
            mapping_status=MappingStatus.UNKNOWN,
        )
        match = resolve_instrument("EURUSD")
        self.assertTrue(match.supported)
        self.assertFalse(match.mapping_verified)

    def test_invalid_mapping_is_rejected(self):
        make_symbol(
            canonical="EURUSD",
            broker_symbol="EURUSD",
            mapping_status=MappingStatus.INVALID,
        )
        match = resolve_instrument("EURUSD")
        self.assertFalse(match.supported)

    def test_otc_token_detection(self):
        self.assertTrue(has_otc_token("EURUSD-OTC"))
        self.assertTrue(has_otc_token("EURUSD_OTC"))
        self.assertTrue(has_otc_token("EURUSDOTC"))
        self.assertFalse(has_otc_token("EURUSD"))
        make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
        match = resolve_instrument("EURUSD-OTC")
        self.assertTrue(match.supported)
        self.assertTrue(match.screenshot_is_otc)
        self.assertFalse(match.reference_is_otc)


class TimeframeMatcherTests(TestCase):
    def test_parse_common_forms(self):
        cases = {
            "M15": "M15",
            "15m": "M15",
            "1 min": "M1",
            "1m": "M1",
            "H1": "H1",
            "4h": "H4",
            "1 day": "D1",
            "D1": "D1",
            "M3": "M3",
        }
        for raw, expected in cases.items():
            self.assertEqual(parse_timeframe(raw), expected, msg=raw)

    def test_unsupported_and_missing_timeframes_return_none(self):
        for raw in ("W1", "UNKNOWN", "", "yearly", "5x"):
            self.assertIsNone(parse_timeframe(raw), msg=raw)

    def test_timeframe_mismatch_detected(self):
        result = match_timeframe("M5", "M1")
        self.assertTrue(result.mismatch)
        self.assertEqual(result.screenshot_timeframe, "M5")

    def test_timeframe_match(self):
        result = match_timeframe("M1", "M1")
        self.assertFalse(result.mismatch)

    def test_missing_screenshot_timeframe_is_not_assumed(self):
        result = match_timeframe("UNKNOWN", "M1")
        self.assertIsNone(result.screenshot_timeframe)
        self.assertFalse(result.supported)


class TimestampAlignerTests(TestCase):
    def test_parse_timestamp_naive_applies_offset(self):
        parsed = parse_timestamp("2026-01-05 12:00", tz_offset_minutes=120)
        self.assertEqual(parsed, datetime(2026, 1, 5, 10, 0, tzinfo=UTC))

    def test_parse_timestamp_z_is_utc(self):
        parsed = parse_timestamp("2026-01-05T12:00:00Z")
        self.assertEqual(parsed, datetime(2026, 1, 5, 12, 0, tzinfo=UTC))

    def test_floor_to_grid(self):
        moment = datetime(2026, 1, 5, 12, 3, 12, tzinfo=UTC)
        self.assertEqual(floor_to_grid(moment, 300), datetime(2026, 1, 5, 12, 0, tzinfo=UTC))

    def test_last_completed_open(self):
        anchor = datetime(2026, 1, 5, 12, 3, 0, tzinfo=UTC)
        self.assertEqual(last_completed_open(anchor, 60), datetime(2026, 1, 5, 12, 2, tzinfo=UTC))

    def test_resolve_anchor_priority(self):
        aligner = TimestampAligner()
        anchor, source, _confidence, _reasons = aligner.resolve_anchor(
            captured_at="2026-01-05T10:00:00Z",
            visible_timestamp="2026-01-05T09:00:00Z",
        )
        self.assertEqual(source, AlignmentSource.USER_PROVIDED)
        self.assertEqual(anchor, datetime(2026, 1, 5, 10, 0, tzinfo=UTC))

    def test_resolve_anchor_visible_timestamp(self):
        aligner = TimestampAligner()
        anchor, source, _confidence, _reasons = aligner.resolve_anchor(
            visible_timestamp="2026-01-05T09:00:00Z",
        )
        self.assertEqual(source, AlignmentSource.VISIBLE_TIMESTAMP)
        self.assertEqual(anchor, datetime(2026, 1, 5, 9, 0, tzinfo=UTC))

    def test_resolve_anchor_none_records_reason(self):
        aligner = TimestampAligner()
        anchor, source, _confidence, reasons = aligner.resolve_anchor()
        self.assertIsNone(anchor)
        self.assertEqual(source, AlignmentSource.NONE)
        self.assertTrue(reasons)

    def test_build_alignment_maps_indices_backwards(self):
        aligner = TimestampAligner()
        last_open = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
        result = aligner.build_alignment(
            completed_indices=[0, 1, 2],
            timeframe="M1",
            last_open=last_open,
            source=AlignmentSource.VISIBLE_TIMESTAMP,
            confidence=0.9,
            uncertain=False,
        )
        self.assertEqual(result.mt5_open_times[2], last_open)
        self.assertEqual(result.mt5_open_times[0], last_open - timedelta(minutes=2))
