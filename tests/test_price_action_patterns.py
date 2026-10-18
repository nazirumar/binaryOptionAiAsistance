"""Tests for the candlestick pattern engine (Step 7): positive + negative."""

from __future__ import annotations

from apps.price_action.constants import PatternDirection
from apps.price_action.services.candlestick_patterns import (
    bearish_engulfing,
    bearish_harami,
    bullish_harami,
    dark_cloud_cover,
    detect_patterns,
    doji,
    evening_star,
    hammer,
    inside_bar,
    morning_star,
    outside_bar,
    piercing,
    shooting_star,
    three_black_crows,
    three_white_soldiers,
)
from tests.pa_fakes import CONFIG, candle


def test_bullish_engulfing():
    candles = [candle(1.0, 1.01, 0.99, 0.995), candle(0.993, 1.02, 0.99, 1.019)]
    assert detect_patterns(candles, 1, config=CONFIG)
    assert any(p["name"] == "bullish_engulfing" for p in detect_patterns(candles, 1, config=CONFIG))


def test_bearish_engulfing():
    candles = [candle(1.0, 1.02, 0.99, 1.015), candle(1.018, 1.02, 0.985, 0.99)]
    assert bearish_engulfing(candles, 1)


def test_hammer_and_shooting_star():
    assert hammer([candle(1.0, 1.005, 0.98, 0.995)], 0)
    assert shooting_star([candle(0.99, 1.02, 0.989, 0.995)], 0)


def test_doji():
    assert doji([candle(1.0, 1.0001, 0.9999, 1.0)], 0)
    assert not doji([candle(1.0, 1.02, 0.99, 1.015)], 0)


def test_harami():
    bullish = [candle(1.0, 1.005, 0.99, 0.99), candle(0.995, 1.0, 0.993, 0.997)]
    assert bullish_harami(bullish, 1)
    bearish = [candle(1.0, 1.01, 0.99, 1.01), candle(1.005, 1.01, 0.995, 1.0)]
    assert bearish_harami(bearish, 1)


def test_inside_and_outside_bar():
    assert inside_bar([candle(1.0, 1.01, 0.99, 1.005), candle(1.002, 1.008, 0.995, 1.004)], 1)
    assert outside_bar([candle(1.0, 1.005, 0.995, 1.002), candle(1.002, 1.008, 0.992, 1.006)], 1)


def test_piercing_and_dark_cloud():
    assert piercing([candle(1.0, 1.005, 0.985, 0.99), candle(0.988, 1.0, 0.987, 0.997)], 1)
    assert dark_cloud_cover(
        [candle(1.0, 1.015, 0.999, 1.01), candle(1.012, 1.013, 0.998, 1.002)], 1
    )


def test_three_candle_stars():
    morning = [
        candle(1.01, 1.012, 0.99, 0.992),
        candle(0.991, 0.993, 0.989, 0.992),
        candle(0.993, 1.006, 0.992, 1.005),
    ]
    assert morning_star(morning, 2, CONFIG)
    evening = [
        candle(1.0, 1.02, 0.999, 1.018),
        candle(1.019, 1.021, 1.017, 1.018),
        candle(1.017, 1.018, 1.002, 1.003),
    ]
    assert evening_star(evening, 2, CONFIG)


def test_three_soldiers_and_crows():
    soldiers = [
        candle(1.0, 1.005, 0.999, 1.004),
        candle(1.004, 1.01, 1.003, 1.009),
        candle(1.009, 1.015, 1.008, 1.014),
    ]
    assert three_white_soldiers(soldiers, 2, CONFIG)
    crows = [
        candle(1.014, 1.015, 1.009, 1.010),
        candle(1.010, 1.011, 1.005, 1.006),
        candle(1.006, 1.007, 1.001, 1.002),
    ]
    assert three_black_crows(crows, 2, CONFIG)


def test_negative_no_directional_pattern_on_flat_candles():
    candles = [candle(1.0, 1.0, 1.0, 1.0) for _ in range(3)]
    patterns = detect_patterns(candles, 2, config=CONFIG)
    directional = [
        p
        for p in patterns
        if p["direction"] in (PatternDirection.BULLISH, PatternDirection.BEARISH)
    ]
    assert directional == []


def test_detect_patterns_reports_context_and_refs():
    candles = [candle(1.0, 1.01, 0.99, 0.995), candle(0.993, 1.02, 0.99, 1.019)]
    pattern = next(
        p for p in detect_patterns(candles, 1, config=CONFIG) if p["name"] == "bullish_engulfing"
    )
    assert pattern["direction"] == str(PatternDirection.BULLISH)
    assert pattern["candle_refs"] == [0, 1]
    assert pattern["context_requirement"]
    assert pattern["invalidation_condition"]
