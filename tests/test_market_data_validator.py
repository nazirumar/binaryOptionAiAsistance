"""Market data validation tests."""

from __future__ import annotations

from datetime import timedelta

import pytest

from apps.market_data.constants import QualityStatus, Severity
from apps.market_data.services.data_validator import (
    detect_missing_candles,
    summarise_issues,
    validate_candle_series,
    validate_symbol_mapping,
    validate_tick,
)
from apps.market_data.services.timeframe_mapper import duration
from tests.marketdata_fakes import BASE_TIME, make_candle, make_tick


def test_valid_series_has_no_issues():
    series = [make_candle(BASE_TIME + i * duration("M1")) for i in range(5)]
    result = validate_candle_series(series, "M1")
    assert result.issues == []
    assert result.quality_status == QualityStatus.OK


def test_empty_series_warns():
    result = validate_candle_series([], "M1")
    assert result.issues[0].code == "empty_series"
    assert result.quality_status == QualityStatus.SUSPECT


def test_duplicate_timestamps_error():
    series = [make_candle(BASE_TIME), make_candle(BASE_TIME)]
    result = validate_candle_series(series, "M1")
    assert any(i.code == "duplicate_timestamps" for i in result.issues)
    assert result.quality_status == QualityStatus.INVALID


def test_non_monotonic_order_warns():
    series = [make_candle(BASE_TIME + duration("M1")), make_candle(BASE_TIME)]
    result = validate_candle_series(series, "M1")
    assert any(i.code == "non_monotonic_order" for i in result.issues)


def test_invalid_ohlc_error():
    bad = make_candle(BASE_TIME, h="1.0000", low="1.2000")
    result = validate_candle_series([bad], "M1")
    assert any(i.code == "invalid_ohlc" for i in result.issues)
    assert result.quality_status == QualityStatus.INVALID


def test_non_positive_price_error():
    bad = make_candle(BASE_TIME, o="0", h="0", low="0", c="0")
    result = validate_candle_series([bad], "M1")
    assert any(i.code == "non_positive_price" for i in result.issues)


def test_missing_candles_detected():
    series = [
        make_candle(BASE_TIME),
        make_candle(BASE_TIME + 3 * duration("M1")),
    ]
    missing = detect_missing_candles(sorted(series, key=lambda c: c.open_time), "M1")
    assert missing == [BASE_TIME + duration("M1"), BASE_TIME + 2 * duration("M1")]


def test_missing_candle_issue_is_warning_not_error():
    series = [make_candle(BASE_TIME), make_candle(BASE_TIME + 3 * duration("M1"))]
    result = validate_candle_series(series, "M1")
    issue = next(i for i in result.issues if i.code == "missing_candles")
    assert issue.severity == Severity.WARNING
    assert not result.has_errors


def test_validate_tick_stale():
    tick = make_tick(BASE_TIME)
    now = BASE_TIME + timedelta(seconds=600)
    issues = validate_tick(tick, now=now, stale_seconds=120)
    assert any(i.code == "stale_tick" for i in issues)


def test_validate_tick_non_positive_and_crossed():
    tick = make_tick(BASE_TIME, bid="0", ask="1.0")
    issues = validate_tick(tick, now=BASE_TIME, stale_seconds=120)
    assert any(i.code == "tick_non_positive_price" for i in issues)

    crossed = make_tick(BASE_TIME, bid="1.2000", ask="1.1000")
    issues = validate_tick(crossed, now=BASE_TIME, stale_seconds=120)
    assert any(i.code == "tick_crossed_spread" for i in issues)


def test_validate_tick_missing_prices():
    tick = make_tick(BASE_TIME, bid=None, ask=None, last=None)
    issues = validate_tick(tick, now=BASE_TIME, stale_seconds=120)
    assert issues[0].code == "tick_missing_prices"
    assert issues[0].severity == Severity.ERROR


@pytest.mark.django_db
def test_validate_symbol_mapping_otc_mismatch():
    from tests.marketdata_fakes import make_symbol

    symbol = make_symbol(canonical="EURUSD_OTC", broker_symbol="EURUSD", is_otc=False)
    result = validate_symbol_mapping(symbol)
    assert result.has_errors
    assert any(i.code == "otc_mismatch" for i in result.issues)


def test_summarise_issues():
    assert summarise_issues([]) == "ok"
    series = [make_candle(BASE_TIME), make_candle(BASE_TIME)]
    result = validate_candle_series(series, "M1")
    assert "error" in summarise_issues(result.issues)
