"""Tests for sweeps (Step 14), order blocks (Step 15), FVGs (Step 16), gaps (Step 17)."""

from __future__ import annotations

from apps.price_action.constants import FVGState, FVGType, OBType, SweepOutcome, SweepType
from apps.price_action.services.fair_value_gaps import (
    annotate_fvg_states,
    classify_fvg_state,
    detect_fvg,
)
from apps.price_action.services.liquidity_sweeps import (
    detect_sweep,
    prev_high_sweep,
    prev_low_sweep,
)
from apps.price_action.services.opening_gaps import (
    annotate_gap_reactions,
    detect_opening_gaps,
)
from apps.price_action.services.order_blocks import (
    annotate_ob_lifecycle,
    detect_order_blocks,
)
from tests.pa_fakes import (
    CONFIG,
    bearish_fvg_series,
    bullish_fvg_series,
    candle,
    high_sweep_series,
    low_sweep_series,
)


def test_bullish_fvg():
    gaps = detect_fvg(bullish_fvg_series(), config=CONFIG)
    assert any(g["type"] == str(FVGType.BULLISH) for g in gaps)
    gap = next(g for g in gaps if g["type"] == str(FVGType.BULLISH))
    assert gap["bottom"] == 1.000
    assert gap["top"] == 1.005


def test_bearish_fvg():
    gaps = detect_fvg(bearish_fvg_series(), config=CONFIG)
    assert any(g["type"] == str(FVGType.BEARISH) for g in gaps)


def test_fvg_state_mitigated_and_invalidated():
    gap = {"type": str(FVGType.BULLISH), "bottom": 1.000, "top": 1.005, "index": 2}
    mitigated = [*bullish_fvg_series(), candle(1.011, 1.012, 1.003, 1.01)]
    assert classify_fvg_state(mitigated, gap) == FVGState.MITIGATED
    invalidated = [*bullish_fvg_series(), candle(1.01, 1.011, 0.995, 0.997)]
    assert classify_fvg_state(invalidated, gap) == FVGState.INVALIDATED
    assert classify_fvg_state(bullish_fvg_series(), gap) == FVGState.OPEN


def test_annotate_fvg_states():
    gaps = annotate_fvg_states(bullish_fvg_series(), detect_fvg(bullish_fvg_series()))
    assert all("state" in g for g in gaps)


def test_bullish_opening_gap():
    series = [candle(1.000, 1.002, 0.999, 1.001), candle(1.005, 1.008, 1.004, 1.007)]
    gaps = detect_opening_gaps(series, config=CONFIG)
    assert gaps and gaps[0]["type"] == "bullish"
    assert gaps[0]["gap_bottom"] == 1.001
    assert gaps[0]["gap_top"] == 1.005


def test_gap_reaction_filled():
    series = [candle(1.000, 1.002, 0.999, 1.001), candle(1.005, 1.008, 1.004, 1.007)]
    gaps = annotate_gap_reactions(series, detect_opening_gaps(series, config=CONFIG))
    assert gaps[0]["reaction"] in ("continuation", "pending", "filled")


def test_low_sweep_rejection():
    sweeps = detect_sweep(low_sweep_series(), config=CONFIG)
    assert sweeps
    low = next(s for s in sweeps if s["type"] == str(SweepType.LOW_SWEEP))
    assert low["outcome"] == str(SweepOutcome.REJECTION)
    assert low["closed_back_inside"] is True


def test_high_sweep_detected():
    assert prev_high_sweep(high_sweep_series()) is True
    sweeps = detect_sweep(high_sweep_series(), config=CONFIG)
    assert any(s["type"] == str(SweepType.HIGH_SWEEP) for s in sweeps)


def test_prev_low_sweep_negative():
    flat_series = [candle(1.0, 1.001, 0.999, 1.0) for _ in range(4)]
    assert prev_low_sweep(flat_series) is False


def test_order_block_teacher_pattern():
    series = [
        candle(1.000, 1.003, 0.999, 1.002),
        candle(1.002, 1.003, 1.000, 1.001),
        candle(1.001, 1.002, 1.000, 1.0015),
        candle(1.0015, 1.002, 1.000, 1.0005),  # last down candle -> zone
        candle(1.0005, 1.013, 1.000, 1.012),  # strong bullish departure
    ]
    obs = annotate_ob_lifecycle(
        series, detect_order_blocks(series, definition="teacher_pattern", config=CONFIG)
    )
    assert obs
    assert any(o["type"] == str(OBType.BULLISH) for o in obs)
    assert all(o["definition"] == "teacher_pattern" for o in obs)


def test_order_block_definitions_never_merged():
    series = [
        candle(1.000, 1.003, 0.999, 1.002),
        candle(1.002, 1.003, 1.000, 1.001),
        candle(1.001, 1.002, 1.000, 1.0015),
        candle(1.0015, 1.002, 1.000, 1.0005),  # zone
        candle(1.0005, 1.013, 1.000, 1.012),  # strong bullish departure, no FVG
    ]
    teacher = detect_order_blocks(series, definition="teacher_pattern", config=CONFIG)
    ict = detect_order_blocks(series, definition="ict_style", config=CONFIG)
    assert teacher and all(o["definition"] == "teacher_pattern" for o in teacher)
    assert ict and all(o["definition"] == "ict_style" for o in ict)
    # The ICT definition additionally requires an imbalance; the teacher one does not.
    assert any(o.get("rejected") for o in ict)
