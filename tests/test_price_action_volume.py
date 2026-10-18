"""Tests for the volume intelligence engine (Step 18)."""

from __future__ import annotations

from apps.price_action.constants import VolumeSource
from apps.price_action.services.volume_analysis import (
    average_volume,
    detect_volume_patterns,
    reversal_pattern_volume_context,
    volume_effort_result,
    volume_of,
)
from tests.pa_fakes import CONFIG, candle, volume_anomaly_series


def test_volume_source_prefers_real_and_never_merges():
    assert volume_of({"real_volume": 5, "tick_volume": 9}) == (5.0, str(VolumeSource.REAL))
    assert volume_of({"tick_volume": 9}) == (9.0, str(VolumeSource.TICK))
    assert volume_of({}) == (None, str(VolumeSource.NONE))


def test_generic_volume_key_is_treated_as_tick():
    value, source = volume_of({"volume": 7})
    assert value == 7.0
    assert source == str(VolumeSource.TICK)


def test_average_volume():
    series = [candle(1.0, 1.001, 0.999, 1.0, v=100) for _ in range(5)]
    avg, source = average_volume(series)
    assert avg == 100.0
    assert source == str(VolumeSource.TICK)


def test_volume_effort_result():
    result = volume_effort_result(candle(1.0, 1.01, 0.99, 1.005, v=250))
    assert result["interpretable"] is True
    assert result["volume"] == 250.0


def test_high_volume_narrow_range():
    patterns = detect_volume_patterns(volume_anomaly_series(), config=CONFIG)
    assert any(p["type"] == "high_volume_narrow_range" for p in patterns)


def test_low_volume_wide_range():
    series = [candle(1.0, 1.002, 0.999, 1.001, v=100) for _ in range(6)]
    series.append(candle(1.001, 1.02, 1.0, 1.019, v=20))
    patterns = detect_volume_patterns(series, config=CONFIG)
    assert any(p["type"] == "low_volume_wide_range" for p in patterns)


def test_rising_volume_sequence():
    series = [
        candle(1.0, 1.002, 0.999, 1.001, v=100),
        candle(1.001, 1.003, 1.0, 1.002, v=150),
        candle(1.002, 1.004, 1.001, 1.003, v=250),
    ]
    patterns = detect_volume_patterns(series, config=CONFIG)
    assert any(p["type"] == "rising_volume_sequence" for p in patterns)


def test_reversal_volume_context():
    series = [candle(1.0, 1.001, 0.999, 1.0, v=100) for _ in range(5)]
    series.append(candle(1.0, 1.02, 0.99, 1.015, v=300))
    ctx = reversal_pattern_volume_context(series, len(series) - 1, config=CONFIG)
    assert ctx["available"] is True
    assert ctx["context"] == "elevated"
