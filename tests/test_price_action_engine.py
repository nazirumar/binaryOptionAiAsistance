"""Integration tests for the price-action engine orchestrator (Step 20)."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.price_action.constants import PA_ENGINE_SCHEMA_VERSION
from apps.price_action.schemas.market_input import build_market_input
from apps.price_action.services.dto import MarketInput
from apps.price_action.services.engine import PriceActionEngine
from tests.pa_fakes import CONFIG, candle, uptrend


def _engine() -> PriceActionEngine:
    return PriceActionEngine(CONFIG)


def test_engine_run_shape():
    result = _engine().run(uptrend(12))
    assert result["schema_version"] == PA_ENGINE_SCHEMA_VERSION
    assert isinstance(result["evidence"], list)
    assert isinstance(result["conflicts"], list)
    assert result["candles_evaluated"] == 12
    assert "context" in result
    assert "summary" in result


def test_engine_empty_input_is_safe():
    result = _engine().run([])
    assert result["candles_evaluated"] == 0
    assert isinstance(result["evidence"], list)


def test_engine_accepts_none():
    assert _engine().run(None)["candles_evaluated"] == 0


def test_engine_accepts_dict_payload():
    payload = {"candles": uptrend(6), "timeframe": "M5", "canonical_instrument": "EURUSD"}
    result = _engine().run(payload)
    assert result["timeframe"] == "M5"
    assert result["canonical_instrument"] == "EURUSD"


def test_engine_accepts_market_input():
    market = build_market_input({"candles": uptrend(6)}, config=CONFIG)
    assert isinstance(market, MarketInput)
    assert _engine().run(market)["candles_evaluated"] == 6


def test_incomplete_final_candle_is_excluded():
    series = uptrend(6)
    series[-1] = dict(series[-1], complete=False)
    result = _engine().run(series)
    assert result["candles_evaluated"] == 5


def test_evidence_items_have_full_schema():
    result = _engine().run(uptrend(12))
    assert result["evidence"]
    required = {
        "rule_id",
        "rule_version",
        "detector",
        "status",
        "direction",
        "explanation",
        "candle_refs",
        "supporting_levels",
        "timestamps",
        "required_conditions",
        "invalidation_conditions",
        "missing_inputs",
        "data_quality",
        "reasons",
        "metrics",
    }
    for item in result["evidence"]:
        assert required <= set(item)


def test_result_makes_no_prediction_or_recommendation():
    result = _engine().run(uptrend(12))
    assert "prediction" not in result
    assert "recommendation" not in result
    assert "signal" not in result
    # No detector metric may carry a probability-like key.
    for item in result["evidence"]:
        for key in item["metrics"]:
            assert "probab" not in key.lower()
    assert result["summary"]["note"]


def test_engine_is_deterministic():
    a = _engine().run(uptrend(12))
    b = _engine().run(uptrend(12))
    assert a == b


def test_engine_respects_injected_now():
    result = _engine().run(uptrend(12), now=datetime(2026, 1, 5, 9, tzinfo=UTC))
    assert result["context"]["session"] == "london"


def test_engine_never_refers_to_future_candle_index():
    series = uptrend(12)
    result = _engine().run(series)
    for item in result["evidence"]:
        for ref in item["candle_refs"]:
            assert 0 <= ref < len(series)


def test_engine_with_flat_series_has_no_directional_breakout():
    series = [candle(1.0, 1.001, 0.999, 1.0) for _ in range(8)]
    result = _engine().run(series)
    rule_ids = {e["rule_id"] for e in result["evidence"]}
    assert not any("breakout" in rid for rid in rule_ids)
