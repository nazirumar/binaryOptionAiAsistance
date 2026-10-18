"""Tests for the versioned market-input schema (Step 3)."""

from __future__ import annotations

import pytest

from apps.price_action.constants import PA_MARKET_INPUT_SCHEMA_VERSION, DataQuality
from apps.price_action.exceptions import SchemaValidationError
from apps.price_action.schemas.market_input import (
    MARKET_INPUT_SCHEMA,
    build_market_input,
    validate_payload,
)
from apps.price_action.services.dto import MarketInput
from tests.pa_fakes import CONFIG, candle, uptrend


def test_validate_payload_accepts_good_input():
    assert validate_payload({"candles": uptrend(5)}) == []


def test_validate_payload_flags_missing_and_bad_candles():
    assert validate_payload({}) == ["missing required field: candles"]
    assert validate_payload({"candles": "nope"}) == ["candles must be a list"]
    issues = validate_payload({"candles": [{"open": 1, "high": 0.5, "low": 1.2, "close": 1}]})
    assert any("high < low" in i for i in issues)


def test_build_market_input_records_quality_and_warnings():
    market = build_market_input({"candles": uptrend(6)}, config=CONFIG)
    assert isinstance(market, MarketInput)
    assert market.schema_version == PA_MARKET_INPUT_SCHEMA_VERSION
    assert market.data_quality == DataQuality.HIGH
    assert market.warnings == ()


def test_build_market_input_insufficient_candles_warns():
    market = build_market_input({"candles": [candle(1.0, 1.01, 0.99, 1.0)]}, config=CONFIG)
    assert any("insufficient candles" in w for w in market.warnings)
    assert market.data_quality in (DataQuality.LOW, DataQuality.MEDIUM)
    assert market.candle_count == 1


def test_strict_mode_raises():
    with pytest.raises(SchemaValidationError):
        build_market_input({"candles": "bad"}, config=CONFIG, strict=True)


def test_unknown_market_type_defaults_and_warns():
    market = build_market_input({"candles": uptrend(5), "market_type": "crypto"}, config=CONFIG)
    assert market.market_type == "unknown"
    assert any("unknown market_type" in w for w in market.warnings)


def test_max_candles_truncation():
    market = build_market_input({"candles": uptrend(50)}, config=CONFIG)
    assert market.candle_count == 50
    market_small = build_market_input({"candles": uptrend(50)}, config=CONFIG, strict=False)
    assert market_small.candle_count == 50


def test_schema_document_has_version():
    assert MARKET_INPUT_SCHEMA["schema_version"] == PA_MARKET_INPUT_SCHEMA_VERSION
    assert "candles" in MARKET_INPUT_SCHEMA["properties"]
