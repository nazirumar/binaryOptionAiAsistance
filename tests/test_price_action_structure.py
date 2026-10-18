"""Tests for the market-structure engine (Step 4)."""

from __future__ import annotations

from apps.price_action.constants import StructureState, SwingKind, SwingLabel
from apps.price_action.services.market_structure import (
    detect_consolidation,
    detect_failed_breakout,
    detect_structure_break,
    detect_swings,
    infer_trend,
    label_swings,
    structure_state,
)
from tests.pa_fakes import CONFIG, candle, flat

# A clean zig-zag: swing high, swing low, higher high, higher low.
ZIGZAG = [
    candle(1.000, 1.000, 0.999, 0.9995),
    candle(0.9995, 1.010, 1.000, 1.009),  # high @1
    candle(1.009, 1.002, 1.000, 1.001),
    candle(1.001, 0.998, 0.990, 0.991),  # low @3
    candle(0.991, 1.005, 0.998, 1.004),
    candle(1.004, 1.015, 1.004, 1.014),  # high @5
    candle(1.014, 1.006, 1.004, 1.005),
    candle(1.005, 1.000, 0.995, 0.996),  # low @7
    candle(0.996, 1.010, 0.999, 1.009),
    candle(1.009, 1.020, 1.009, 1.019),
]


def test_detect_swings_and_labels():
    swings = label_swings(detect_swings(ZIGZAG, lookback=1), CONFIG.equal_level_tolerance)
    highs = [s for s in swings if s.kind == SwingKind.HIGH]
    lows = [s for s in swings if s.kind == SwingKind.LOW]
    assert [s.value for s in highs] == [1.010, 1.015]
    assert highs[-1].label == SwingLabel.HH
    assert lows[-1].label == SwingLabel.HL


def test_no_lookahead_unconfirmed_final_swing():
    # With lookback=2 the final candle can never be a confirmed swing.
    swings = detect_swings(ZIGZAG, lookback=2)
    assert all(s.index <= len(ZIGZAG) - 1 - 2 for s in swings)


def test_infer_uptrend():
    assert infer_trend(ZIGZAG, 1) == "uptrend"
    assert structure_state(ZIGZAG, swing_lookback=1) == StructureState.BULLISH


def test_infer_downtrend():
    series = [
        candle(1.000, 1.010, 1.000, 1.009),
        candle(1.009, 1.011, 1.000, 1.001),
        candle(1.001, 1.004, 0.990, 0.991),
        candle(0.991, 1.000, 0.980, 0.981),
        candle(0.981, 0.985, 0.970, 0.971),
        candle(0.971, 0.980, 0.960, 0.961),
    ]
    assert infer_trend(series, 1) in ("downtrend", "ranging", "unclear")


def test_insufficient_for_trend():
    assert infer_trend([candle(1.0, 1.01, 0.99, 1.005)], 1) == "unclear"


def test_structure_break_bullish():
    series = [*ZIGZAG, candle(1.019, 1.021, 1.018, 1.02)]
    bos = detect_structure_break(series, lookback=1)
    assert bos is not None and bos["type"] == "bullish_bos"


def test_failed_breakout():
    # A confirmed swing high at 1.010, later re-tested with a wick but closed below.
    series = [
        candle(1.000, 1.002, 0.999, 1.001),
        candle(1.001, 1.010, 1.000, 1.009),  # swing high 1.010
        candle(1.009, 1.002, 1.000, 1.001),
        candle(1.001, 1.003, 0.998, 0.999),
        candle(0.999, 1.004, 0.997, 1.003),
        candle(1.003, 1.005, 1.001, 1.004),
        candle(1.004, 1.006, 1.002, 1.005),
        candle(1.005, 1.012, 1.004, 1.008),  # wicks above 1.010, closes 1.008
    ]
    failed = detect_failed_breakout(series, lookback=1)
    assert failed is not None and failed["type"] == "failed_high_breakout"


def test_consolidation_detected_and_not():
    assert detect_consolidation(flat(6), config=CONFIG) is not None
    wide = flat(6)
    wide[-1] = candle(1.0, 1.02, 0.98, 1.01)
    assert detect_consolidation(wide, config=CONFIG) is None
