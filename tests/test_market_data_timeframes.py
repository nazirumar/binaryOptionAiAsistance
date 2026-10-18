"""Timeframe mapping tests."""

from __future__ import annotations

from datetime import timedelta

import pytest

from apps.market_data.services.exceptions import UnsupportedTimeframeError
from apps.market_data.services.timeframe_mapper import (
    SUPPORTED_TIMEFRAMES,
    TIMEFRAME_SECONDS,
    duration,
    duration_seconds,
    from_mt5,
    is_supported,
    to_mt5,
)


def test_supported_timeframes_are_the_required_set():
    assert set(SUPPORTED_TIMEFRAMES) == {"M1", "M2", "M3", "M5", "M15", "M30", "H1", "H4", "D1"}


@pytest.mark.parametrize(
    ("timeframe", "seconds"),
    [("M1", 60), ("M3", 180), ("M15", 900), ("H1", 3600), ("H4", 14400), ("D1", 86400)],
)
def test_duration_seconds(timeframe, seconds):
    assert duration_seconds(timeframe) == seconds
    assert duration(timeframe) == timedelta(seconds=seconds)
    assert is_supported(timeframe)


def test_unsupported_timeframe_raises():
    assert not is_supported("M7")
    with pytest.raises(UnsupportedTimeframeError):
        duration_seconds("M7")


def test_to_mt5_maps_to_package_constants():
    mt5 = pytest.importorskip("MetaTrader5")
    assert to_mt5("M1") == mt5.TIMEFRAME_M1
    assert to_mt5("H4") == mt5.TIMEFRAME_H4
    assert to_mt5("D1") == mt5.TIMEFRAME_D1


def test_from_mt5_roundtrip():
    pytest.importorskip("MetaTrader5")
    assert from_mt5(to_mt5("M5")) == "M5"


def test_timeframe_seconds_covers_all_supported():
    assert set(TIMEFRAME_SECONDS) == set(SUPPORTED_TIMEFRAMES)
