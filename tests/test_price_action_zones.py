"""Tests for the support/resistance engine (Step 5)."""

from __future__ import annotations

import pytest

from apps.price_action.constants import RejectionKind, ZoneKind
from apps.price_action.services.support_resistance import (
    Zone,
    detect_breakout_confirmation,
    detect_rejection,
    detect_sbr_rbs,
    detect_zones,
    is_level_invalidated,
)
from tests.pa_fakes import CONFIG, candle

# Repeated rejection at resistance ~1.011, ending with a wick rejection candle.
RESISTANCE = [
    candle(1.000, 1.005, 0.998, 1.004),
    candle(1.004, 1.009, 1.002, 1.007),
    candle(1.007, 1.011, 1.005, 1.006),  # swing high
    candle(1.006, 1.008, 1.002, 1.003),
    candle(1.003, 1.010, 1.001, 1.008),
    candle(1.008, 1.012, 1.006, 1.007),  # swing high
    candle(1.007, 1.009, 1.003, 1.004),
    candle(1.004, 1.011, 1.002, 1.009),
    candle(1.009, 1.010, 1.005, 1.006),
    candle(1.006, 1.012, 1.004, 1.007),  # wick rejection of the zone
]


def test_detect_zones_returns_zones():
    zones = detect_zones(RESISTANCE, config=CONFIG)
    assert zones
    assert all(z.touches >= CONFIG.zone_min_touches for z in zones)
    assert any(z.kind == ZoneKind.RESISTANCE for z in zones)


def test_zone_rejects_and_contains():
    zone = Zone(ZoneKind.RESISTANCE, 1.009, 1.011, 2, 2, 0, 0)
    assert zone.contains(1.010)
    assert not zone.contains(1.02)
    assert zone.price == pytest.approx(1.010)


def test_detect_rejection():
    zone = Zone(ZoneKind.RESISTANCE, 1.009, 1.011, 2, 2, 0, 0)
    rejection = detect_rejection(RESISTANCE, zone, config=CONFIG)
    assert rejection is not None
    assert rejection["kind"] == RejectionKind.WICK_REJECTION


def test_breakout_confirmation_requires_close():
    zone = Zone(ZoneKind.RESISTANCE, 1.009, 1.011, 2, 2, 0, 0)
    wick_only = [candle(1.010, 1.013, 1.008, 1.010)]  # wick above, close inside
    assert detect_breakout_confirmation(wick_only, zone, config=CONFIG) is None
    close_above = [candle(1.010, 1.014, 1.010, 1.013)]
    result = detect_breakout_confirmation(close_above, zone, config=CONFIG)
    assert result is not None and result["type"] == "bullish_breakout"


def test_retest_and_sbr():
    zone = Zone(ZoneKind.SUPPORT, 1.008, 1.012, 2, 2, 0, 0)
    series = [
        candle(1.011, 1.012, 1.006, 1.006),  # closes below support
        candle(1.006, 1.010, 1.005, 1.009),
        candle(1.009, 1.015, 1.011, 1.014),  # breaks back above
        candle(1.014, 1.014, 1.010, 1.012),  # retests the zone from above
    ]
    flip = detect_sbr_rbs(series, zone, config=CONFIG)
    assert flip is not None and flip["type"] == "support_became_resistance"


def test_level_invalidation_requires_two_closes():
    zone = Zone(ZoneKind.SUPPORT, 0.998, 1.002, 2, 2, 0, 0)
    one = [candle(1.000, 1.001, 0.990, 0.995)]
    assert not is_level_invalidated(one, zone, config=CONFIG)
    two = [*one, candle(0.995, 0.996, 0.985, 0.99)]
    assert is_level_invalidated(two, zone, config=CONFIG)
