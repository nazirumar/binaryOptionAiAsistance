"""Tests for the candle-sequence engines (Steps 9-12)."""

from __future__ import annotations

from apps.price_action.constants import Direction
from apps.price_action.services.candle_sequences import (
    analyze_reference_sequences,
    consecutive_bearish,
    consecutive_bullish,
    directional_runs,
    lonely_candles,
    psych_sequences,
    sign,
    similar_sequences,
)
from tests.pa_fakes import CONFIG, candle, downtrend, uptrend


def test_consecutive_helpers():
    assert consecutive_bullish(uptrend(5)) == 5
    assert consecutive_bearish(downtrend(4)) == 4


def test_directional_runs_merge():
    series = uptrend(3) + downtrend(2)
    runs = directional_runs(series)
    assert [r.length for r in runs] == [3, 2]


def test_reference_sequences_extended_run():
    ref = analyze_reference_sequences(uptrend(5), config=CONFIG)
    assert ref["available"]
    assert ref["current_direction"] == Direction.BULLISH
    assert ref["current_run_length"] == 5
    assert ref["extended"] is True


def test_reference_sequences_insufficient():
    assert analyze_reference_sequences([], config=CONFIG)["available"] is False


def test_similar_sequences_has_no_predictive_claim():
    series = uptrend(3) + downtrend(3) + uptrend(3)
    result = similar_sequences(series, config=CONFIG)
    assert result["available"]
    assert result["predictive_claim"] is False
    assert len(result["signature"]) == CONFIG.sequence_signature_length


def test_lonely_bearish_inside_bullish_run():
    series = [
        candle(1.0, 1.01, 0.999, 1.008),
        candle(1.008, 1.009, 0.995, 0.997),  # isolated bearish
        candle(0.997, 1.01, 0.996, 1.009),
    ]
    found = lonely_candles(series, config=CONFIG)
    assert len(found) == 1
    assert found[0]["index"] == 1
    assert found[0]["hypothesis"] == "candidate seller-stop support"


def test_psych_template_match():
    series = [
        candle(1.0, 1.01, 0.999, 1.008),
        candle(1.008, 1.02, 1.006, 1.018),
        candle(1.018, 1.019, 1.0, 1.002),
    ]
    assert [sign(c) for c in series] == [1, 1, -1]
    matches = psych_sequences(series, config=CONFIG)
    names = {m["name"] for m in matches}
    assert "bullish_2_green_green_red" in names
    assert all(m["template_not_signal"] for m in matches)
