"""Tests for the versioned structured-output schema validator."""

from __future__ import annotations

import pytest

from apps.chart_vision.services.exceptions import SchemaValidationError
from apps.chart_vision.services.schema_validator import (
    parse_json_object,
    validate_payload,
)
from tests.vision_fakes import full_payload

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------
def test_parse_json_object_plain():
    assert parse_json_object('{"a": 1}') == {"a": 1}


def test_parse_json_object_strips_code_fences():
    text = 'Here you go:\n```json\n{"a": 1}\n```\n'
    assert parse_json_object(text) == {"a": 1}


def test_parse_json_object_extracts_embedded_object():
    text = 'prefix {"a": 1} suffix'
    assert parse_json_object(text) == {"a": 1}


@pytest.mark.parametrize("text", ["", "no json here", "[1, 2, 3]"])
def test_parse_json_object_rejects_non_object(text):
    with pytest.raises(SchemaValidationError):
        parse_json_object(text)


# ---------------------------------------------------------------------------
# Valid payload
# ---------------------------------------------------------------------------
def test_valid_payload_passes():
    result = validate_payload(full_payload())
    assert result.valid is True
    assert result.payload["schema_version"] == "1.0"
    assert result.payload["chart_metadata"]["instrument"] == "EURUSD"
    assert len(result.payload["candles"]) == 3
    assert result.payload["patterns"][0]["name"] == "bullish engulfing"


def test_missing_required_key_is_invalid():
    payload = full_payload()
    del payload["market_structure"]
    result = validate_payload(payload)
    assert result.valid is False
    assert any("market_structure" in error for error in result.errors)


def test_schema_version_mismatch_is_invalid():
    result = validate_payload(full_payload(schema_version="2.0"))
    assert result.valid is False
    assert any("Schema version mismatch" in error for error in result.errors)


def test_missing_schema_version_warns_but_valid():
    payload = full_payload()
    del payload["schema_version"]
    result = validate_payload(payload)
    assert result.valid is True
    assert any("schema_version" in warning for warning in result.warnings)


# ---------------------------------------------------------------------------
# No fabricated probabilities / prices
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "key", ["probability", "win_rate", "winRate", "prediction", "up_probability", "success_rate"]
)
def test_forbidden_probability_fields_are_rejected(key):
    payload = full_payload()
    payload["chart_metadata"][key] = 0.9
    result = validate_payload(payload)
    assert result.valid is False
    assert any("probability" in error.lower() for error in result.errors)


def test_forbidden_probability_nested_is_rejected():
    payload = full_payload()
    payload["patterns"][0]["prediction"] = "UP"
    result = validate_payload(payload)
    assert result.valid is False


def test_numeric_candle_prices_are_stripped_with_warning():
    payload = full_payload()
    payload["candles"][0]["close"] = 1.105
    payload["candles"][0]["open"] = 1.100
    result = validate_payload(payload)
    assert result.valid is True
    candle = result.payload["candles"][0]
    assert "close" not in candle
    assert "open" not in candle
    assert candle["high_px"] == 120
    assert any("price fields were removed" in warning for warning in result.warnings)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def test_unknown_enum_values_are_coerced():
    payload = full_payload()
    payload["market_structure"]["trend"] = "sideways-ish"
    payload["chart_metadata"]["otc_status"] = "maybe"
    result = validate_payload(payload)
    assert result.payload["market_structure"]["trend"] == "unclear"
    assert result.payload["chart_metadata"]["otc_status"] == "unknown"
    assert any("not recognised" in warning for warning in result.warnings)


def test_confidence_is_clamped_to_unit_interval():
    payload = full_payload()
    payload["observation_confidence"]["overall"] = 3.5
    payload["candles"][0]["confidence"] = -2
    result = validate_payload(payload)
    assert result.payload["observation_confidence"]["overall"] == 1.0
    assert result.payload["candles"][0]["confidence"] == 0.0


def test_candles_not_a_list_is_invalid():
    result = validate_payload(full_payload(candles={"index": 0}))
    assert result.valid is False
    assert any("candles" in error for error in result.errors)


def test_non_object_payload_is_invalid():
    result = validate_payload(["not", "an", "object"])
    assert result.valid is False
