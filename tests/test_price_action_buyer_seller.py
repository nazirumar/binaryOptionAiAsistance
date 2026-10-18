"""Tests for the buyer/seller failure engine (Step 6)."""

from __future__ import annotations

from apps.price_action.constants import Direction
from apps.price_action.services.buyer_seller_failure import (
    buyers_create_support,
    detect_buyer_seller_failure,
    sellers_create_resistance,
    source_strength,
)
from tests.pa_fakes import CONFIG, candle, swing_high_low_series

# Price repeatedly rejects resistance near 1.011, then wicks above and closes back.
RESISTANCE_FAIL = [
    candle(1.000, 1.005, 0.998, 1.004),
    candle(1.004, 1.010, 1.002, 1.006),
    candle(1.006, 1.010, 1.001, 1.003),
    candle(1.003, 1.009, 1.002, 1.008),
    candle(1.008, 1.011, 1.007, 1.009),
    candle(1.009, 1.010, 1.004, 1.005),
    candle(1.005, 1.010, 1.004, 1.009),
    candle(1.009, 1.012, 1.007, 1.011),
    candle(1.011, 1.011, 1.005, 1.006),
]


def test_buyers_create_support():
    found = buyers_create_support(swing_high_low_series(), config=CONFIG)
    assert found is not None
    assert found["direction"] == Direction.BULLISH
    assert "not an intent claim" in found["note"]


def test_sellers_create_resistance():
    found = sellers_create_resistance(swing_high_low_series(), config=CONFIG)
    assert found is not None
    assert found["direction"] == Direction.BEARISH


def test_detect_failures_flags_buyer_failure():
    result = detect_buyer_seller_failure(RESISTANCE_FAIL, config=CONFIG)
    types = [e["type"] for e in result["events"]]
    assert "buyers_failed_to_break_resistance" in types


def test_events_are_ordered_by_index():
    result = detect_buyer_seller_failure(swing_high_low_series(), config=CONFIG)
    indices = [e["index"] for e in result["events"]]
    assert indices == sorted(indices)


def test_source_strength_reports_strengthening_or_weakening():
    strength = source_strength(swing_high_low_series(), config=CONFIG)
    assert strength["available"]
    assert strength["direction"] in (Direction.BULLISH, Direction.BEARISH)


def test_empty_input_is_safe():
    result = detect_buyer_seller_failure([], config=CONFIG)
    assert result["events"] == []
    assert result["source_strength"]["available"] is False
