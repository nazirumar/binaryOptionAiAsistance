"""Tests for the end-to-end analysis pipeline (hermetic, fake provider)."""

from __future__ import annotations

import pytest

from apps.chart_vision.constants import AnalysisStatus, EventKind
from apps.chart_vision.services.exceptions import (
    SchemaValidationError,
    VisionProviderUnavailableError,
)
from apps.chart_vision.services.screenshot_analyzer import (
    ScreenshotAnalyzer,
    build_idempotency_key,
    get_or_create_analysis,
)
from tests.factories import UserFactory
from tests.vision_fakes import (
    StaticVisionProvider,
    full_payload,
    make_screenshot,
    unknown_metadata_payload,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return UserFactory(username="vision-analyst")


def run_analysis(screenshot, provider):
    analysis, _ = get_or_create_analysis(screenshot)
    ScreenshotAnalyzer(provider=provider).analyze(screenshot, analysis)
    analysis.refresh_from_db()
    return analysis


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_full_analysis_persists_structured_result(user):
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))

    assert analysis.status == AnalysisStatus.COMPLETED
    assert analysis.candle_count == 3
    assert analysis.provider == "static"
    assert analysis.model_name == "static-vision-1"
    assert analysis.prompt_version == "v1"
    assert analysis.schema_version == "1.0"
    assert analysis.total_tokens == 18
    assert analysis.observation_confidence == pytest.approx(0.62)

    # Derived rows.
    assert analysis.patterns.count() == 2  # candlestick + promoted advanced concept
    categories = set(analysis.patterns.values_list("category", flat=True))
    assert categories == {"candlestick", "advanced"}
    assert analysis.price_zones.count() == 1
    kinds = set(analysis.observations.values_list("kind", flat=True))
    assert {
        "chart_metadata",
        "market_structure",
        "candle_sequence",
        "liquidity",
        "market_cycle",
    } <= kinds

    # Processing events recorded.
    assert analysis.events.filter(kind=EventKind.PROVIDER_REQUEST).exists()
    assert analysis.events.filter(kind=EventKind.PROVIDER_RESPONSE).exists()
    assert analysis.events.filter(kind=EventKind.PERSIST).exists()


def test_metadata_extraction_uses_visible_values(user):
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))
    assert analysis.chart_metadata["instrument"] == "EURUSD"
    assert analysis.chart_metadata["timeframe"] == "M1"
    assert analysis.chart_metadata["platform"] == "IQ Option"


# ---------------------------------------------------------------------------
# Rightmost candle safeguard
# ---------------------------------------------------------------------------
def test_rightmost_candle_is_never_claimed_complete(user):
    payload = full_payload()
    # Provider claims the final candle is complete.
    assert payload["candles"][-1]["appears_complete"] is True
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=payload))

    last = analysis.result["candles"][-1]
    assert last["appears_complete"] is False
    assert last["provider_claimed_complete"] is True
    assert last["ambiguity"]
    assert any("incomplete" in warning.lower() for warning in analysis.warnings)


# ---------------------------------------------------------------------------
# Missing symbol / timeframe / OTC
# ---------------------------------------------------------------------------
def test_missing_symbol_and_timeframe_reported_as_unknown(user):
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=unknown_metadata_payload()))
    assert analysis.status == AnalysisStatus.PARTIAL
    assert analysis.chart_metadata["instrument"] == "UNKNOWN"
    assert analysis.chart_metadata["timeframe"] == "UNKNOWN"
    joined = " ".join(analysis.missing_information).lower()
    assert "instrument" in joined
    assert "timeframe" in joined


def test_otc_status_is_preserved_not_substituted(user):
    payload = full_payload()
    payload["chart_metadata"]["otc_status"] = "otc"
    payload["chart_metadata"]["instrument"] = "EURUSD-OTC"
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=payload))
    assert analysis.chart_metadata["otc_status"] == "otc"

    # Unknown OTC must never be silently turned into a concrete value.
    unknown = run_analysis(
        make_screenshot(user),
        StaticVisionProvider(payload=unknown_metadata_payload()),
    )
    assert unknown.chart_metadata["otc_status"] == "unknown"


# ---------------------------------------------------------------------------
# Quality handling
# ---------------------------------------------------------------------------
def test_low_quality_adds_warning(user):
    payload = full_payload(screenshot_quality={"rating": "low", "issues": ["blurry"], "notes": ""})
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=payload))
    assert any("low-quality" in warning.lower() for warning in analysis.warnings)


def test_unusable_screenshot_is_insufficient_evidence(user):
    payload = full_payload(screenshot_quality={"rating": "unusable", "issues": [], "notes": ""})
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=payload))
    assert analysis.status == AnalysisStatus.INSUFFICIENT


# ---------------------------------------------------------------------------
# No fabricated prices / probabilities
# ---------------------------------------------------------------------------
def test_stored_result_never_contains_numeric_candle_prices(user):
    payload = full_payload()
    payload["candles"][0]["close"] = 1.105
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=payload))
    candle = analysis.result["candles"][0]
    assert "close" not in candle
    assert "open" not in candle


def test_no_probability_keys_in_stored_result(user):
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))
    serialized = repr(analysis.result).lower()
    assert "win_rate" not in serialized
    assert "probability" not in serialized


# ---------------------------------------------------------------------------
# Provider / schema failures never fabricate results
# ---------------------------------------------------------------------------
def test_provider_unavailable_fails_without_result(user):
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    provider = StaticVisionProvider(error=VisionProviderUnavailableError("down"))
    with pytest.raises(VisionProviderUnavailableError):
        ScreenshotAnalyzer(provider=provider).analyze(screenshot, analysis)
    analysis.refresh_from_db()
    assert analysis.status == AnalysisStatus.FAILED
    assert analysis.error_code == "provider_unavailable"
    assert analysis.result == {}


def test_invalid_json_fails(user):
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    provider = StaticVisionProvider(raw_text="this is not json")
    with pytest.raises(SchemaValidationError):
        ScreenshotAnalyzer(provider=provider).analyze(screenshot, analysis)
    analysis.refresh_from_db()
    assert analysis.status == AnalysisStatus.FAILED
    assert analysis.result == {}


def test_schema_violation_fails(user):
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    provider = StaticVisionProvider(
        payload={"schema_version": "1.0", "analysis_status": "completed"}
    )
    with pytest.raises(SchemaValidationError):
        ScreenshotAnalyzer(provider=provider).analyze(screenshot, analysis)
    analysis.refresh_from_db()
    assert analysis.status == AnalysisStatus.FAILED
    assert analysis.error_code == "schema_invalid"


def test_fabricated_probability_fails(user):
    payload = full_payload()
    payload["win_rate"] = 0.85
    screenshot = make_screenshot(user)
    analysis, _ = get_or_create_analysis(screenshot)
    with pytest.raises(SchemaValidationError):
        ScreenshotAnalyzer(provider=StaticVisionProvider(payload=payload)).analyze(
            screenshot, analysis
        )
    analysis.refresh_from_db()
    assert analysis.status == AnalysisStatus.FAILED


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------
def test_idempotency_key_is_stable(user):
    screenshot = make_screenshot(user)
    assert build_idempotency_key(screenshot.pk) == f"analyze:{screenshot.pk}:v1:1.0"


def test_get_or_create_analysis_is_idempotent(user):
    screenshot = make_screenshot(user)
    first, created_first = get_or_create_analysis(screenshot)
    second, created_second = get_or_create_analysis(screenshot)
    assert created_first is True
    assert created_second is False
    assert first.pk == second.pk


def test_rerun_replaces_derived_rows_without_duplicating(user):
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))
    assert analysis.patterns.count() == 2
    observation_count = analysis.observations.count()
    ScreenshotAnalyzer(provider=StaticVisionProvider(payload=full_payload())).analyze(
        screenshot, analysis
    )
    assert analysis.patterns.count() == 2
    assert analysis.observations.count() == observation_count


def test_attempts_increment_on_rerun(user):
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))
    assert analysis.attempts == 1
    ScreenshotAnalyzer(provider=StaticVisionProvider(payload=full_payload())).analyze(
        screenshot, analysis
    )
    analysis.refresh_from_db()
    assert analysis.attempts == 2


# ---------------------------------------------------------------------------
# Confirmed vs uncertain; advanced concepts; insufficient evidence
# ---------------------------------------------------------------------------
def test_confirmed_flag_is_preserved_from_provider(user):
    payload = full_payload()
    payload["patterns"][0]["confirmed"] = False
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=payload))
    pattern = analysis.patterns.get(category="candlestick")
    assert pattern.confirmed is False
    structure = analysis.result["market_structure"]
    assert structure["swing_highs"][0]["confirmed"] is True
    assert structure["swing_lows"][0]["confirmed"] is False


def test_advanced_concepts_are_promoted_without_being_confirmed(user):
    payload = full_payload(
        liquidity=[
            {"kind": "order_block", "candles": [1, 2], "confidence": 0.3, "notes": "OB"},
            {"kind": "liquidity_sweep", "candles": [0], "confidence": 0.2, "notes": "sweep"},
        ],
        sequence_observations=[],
    )
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=payload))
    advanced = set(analysis.patterns.filter(category="advanced").values_list("name", flat=True))
    assert {"order_block", "liquidity_sweep"} <= advanced
    # Advanced concepts are candidate observations, never confirmed.
    assert all(
        confirmed is None
        for confirmed in analysis.patterns.filter(category="advanced").values_list(
            "confirmed", flat=True
        )
    )


def test_insufficient_evidence_status_is_honoured(user):
    payload = full_payload(analysis_status="insufficient_evidence")
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=payload))
    assert analysis.status == AnalysisStatus.INSUFFICIENT


def test_support_resistance_zone_fields_are_stored(user):
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))
    zone = analysis.price_zones.get()
    assert zone.zone_type == "resistance"
    assert zone.price_hint == "1.1100"
    assert zone.repeated_rejection is True
    assert zone.supporting_candles == [0, 2]
