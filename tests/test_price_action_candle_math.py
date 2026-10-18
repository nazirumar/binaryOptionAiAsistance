"""Tests for the candle geometry / strength engine (Step 8)."""

from __future__ import annotations

import pytest

from apps.price_action.constants import CandleStrength
from apps.price_action.services.candle_math import (
    aggregate_ohlc,
    body_range_ratio,
    candle_range,
    classify_strength,
    is_bearish,
    is_bullish,
    is_doji,
    is_rejection_candle,
    lower_wick_ratio,
    upper_wick_ratio,
)
from tests.pa_fakes import CONFIG, candle


def test_direction():
    assert is_bullish(candle(1.0, 1.01, 0.99, 1.005))
    assert is_bearish(candle(1.005, 1.01, 0.99, 1.0))
    assert not is_bullish(candle(1.0, 1.0, 1.0, 1.0))


def test_body_and_range_ratios():
    c = candle(1.0, 1.01, 0.99, 1.008)
    assert candle_range(c) == pytest.approx(0.02)
    assert body_range_ratio(c) == pytest.approx(0.4)


def test_wick_ratios():
    c = candle(1.0, 1.005, 0.98, 1.0)
    assert upper_wick_ratio(c) == pytest.approx(0.2)
    assert lower_wick_ratio(c) == pytest.approx(0.8)


def test_zero_range_is_safe():
    c = candle(1.0, 1.0, 1.0, 1.0)
    assert body_range_ratio(c) is None
    assert upper_wick_ratio(c) is None
    assert is_doji(c) is True


def test_classify_strength():
    strong = candle(1.0, 1.011, 0.999, 1.010)
    assert classify_strength(strong, config=CONFIG) == CandleStrength.STRONG_BULLISH
    strong_bear = candle(1.010, 1.011, 0.999, 1.000)
    assert classify_strength(strong_bear, config=CONFIG) == CandleStrength.STRONG_BEARISH
    weak = candle(1.0, 1.01, 0.99, 1.001)
    assert classify_strength(weak, config=CONFIG) == CandleStrength.WEAK


def test_rejection_candle_lower_and_upper():
    lower = candle(1.0, 1.001, 0.99, 0.999)
    assert is_rejection_candle(lower, config=CONFIG)["side"] == "lower"
    upper = candle(1.0, 1.012, 1.0, 1.001)
    assert is_rejection_candle(upper, config=CONFIG)["side"] == "upper"


def test_aggregate_ohlc():
    agg = aggregate_ohlc([candle(1.0, 1.01, 0.99, 1.005), candle(1.005, 1.02, 1.0, 1.015)])
    assert agg == {"open": 1.0, "high": 1.02, "low": 0.99, "close": 1.015}
