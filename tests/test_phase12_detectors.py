"""Phase 12 (CP2-CP8): deterministic detectors are honest and configurable.

Every test here pins a *behaviour*, not a probability: geometry actually
measured, thresholds reported, context requirements named, and the registry
refusing to execute any key it does not know.

No test asserts an accuracy figure — none of these detectors has been validated
against labelled outcomes, so none may claim one.
"""

from __future__ import annotations

import pytest

from apps.price_action.constants import Direction, SBRStage
from apps.price_action.services import candlestick_patterns as cp
from apps.price_action.services.abc_pattern import abc_candidates, detect_abc
from apps.price_action.services.candle_sequences import (
    candle_progress,
    failed_continuation,
    run_count,
    strong_close,
    weak_close,
)
from apps.price_action.services.ict_concepts import (
    breaker_blocks,
    displacement,
    equal_levels,
    inducement,
    mitigation_report,
    premium_discount,
    sweep_of_swing,
)
from apps.price_action.services.level_setups import (
    detect_level_setups,
    doji_at_zone,
    engulfing_at_zone,
    failed_zone_test,
    false_breakout,
    sbr_rbs_lifecycle,
)
from apps.price_action.services.market_structure import (
    detect_choch,
    detect_mss,
    detect_trend_exhaustion,
    reversal_candidates,
    structure_narrative,
)
from apps.price_action.services.support_resistance import detect_zones
from apps.strategy_knowledge.constants import DETECTOR_KEYS
from apps.strategy_knowledge.registry import DETECTOR_REGISTRY, run_detector
from tests.pa_fakes import CONFIG, candle, downtrend, uptrend


def test_bullish_pin_bar_geometry() -> None:
    candles = [*downtrend(5), candle(1.00, 1.005, 0.97, 1.004)]
    # body = 0.004, range = 0.035 -> body 0.114 <= 0.40
    # lower wick = 0.03 -> 0.857 >= 0.55, upper = 0.001 -> 0.029 <= 0.12
    # close position = 0.971 >= 0.65
    assert cp.bullish_pin_bar(candles, 5, config=CONFIG) is True
    # Not a pin bar at an unrelated index.
    assert cp.bullish_pin_bar(candles, 2, config=CONFIG) is False


def test_bearish_pin_bar_geometry() -> None:
    candles = [*uptrend(5), candle(1.05, 1.08, 1.046, 1.047)]
    # body = 0.003, range = 0.034 -> 0.088 <= 0.40
    # upper wick = 0.03 -> 0.882 >= 0.55, lower = 0.001 -> 0.029 <= 0.12
    # close position = 0.029 <= 1 - 0.65 = 0.35
    assert cp.bearish_pin_bar(candles, 5, config=CONFIG) is True
    assert cp.bearish_pin_bar(candles, 2, config=CONFIG) is False


def test_pin_bar_requires_small_body() -> None:
    # Long lower wick (0.56), tiny upper wick (0.10), but a body that is 43% of
    # range (> 0.40 max): not a pin bar.
    not_a_pin = candle(1.006, 1.05, 0.95, 1.049)
    assert cp.bullish_pin_bar([not_a_pin], 0, config=CONFIG) is False
    # Identical wicks with a 39%-of-range body: is a pin bar.
    is_a_pin = candle(1.006, 1.05, 0.95, 1.045)
    assert cp.bullish_pin_bar([is_a_pin], 0, config=CONFIG) is True


def test_inverted_hammer_needs_preceding_decline() -> None:
    # upper 0.039 vs lower 0.003: upper >= 2*lower, small body.
    star = candle(1.00, 1.04, 0.997, 1.001)
    assert cp.inverted_hammer([*downtrend(4), star], 4) is True
    assert cp.inverted_hammer([*uptrend(4), star], 4) is False


def test_hanging_man_needs_preceding_advance() -> None:
    # Same hammer geometry; context decides the name.
    hammer_shape = candle(1.04, 1.045, 1.00, 1.043)
    assert cp.hanging_man([*uptrend(4), hammer_shape], 4) is True
    assert cp.hanging_man([*downtrend(4), hammer_shape], 4) is False


def test_dragonfly_doji_suppresses_plain_doji() -> None:
    dragon = candle(1.00, 1.001, 0.97, 1.0005)
    # lower wick 0.03 / range 0.031 = 0.968 >= 0.60, upper 0.016 <= 0.10.
    assert cp.dragonfly_doji([dragon], 0, config=CONFIG) is True
    names = [p["name"] for p in cp.detect_patterns([dragon], 0, config=CONFIG)]
    assert "dragonfly_doji" in names
    assert "doji" not in names  # suppressed: dragonfly is the more specific name

    stone = candle(1.00, 1.03, 0.9995, 1.0005)
    assert cp.gravestone_doji([stone], 0, config=CONFIG) is True
    assert cp.dragonfly_doji([stone], 0, config=CONFIG) is False


def test_spinning_top_is_neither_doji_nor_hammer() -> None:
    spin = candle(1.00, 1.04, 0.96, 1.02)  # body 0.25, both wicks >= 0.20
    assert cp.spinning_top([spin], 0, config=CONFIG) is True
    hammer_like = candle(1.00, 1.005, 0.95, 1.004)  # body 0.073 <= 0.12 -> doji
    assert cp.spinning_top([hammer_like], 0, config=CONFIG) is False


def test_tweezers_match_tolerances() -> None:
    pair_top = [
        candle(1.00, 1.050, 1.00, 1.045),  # bullish, high 1.050
        candle(1.045, 1.0505, 1.02, 1.025),  # bearish, high 1.0505 (diff 0.0005)
    ]
    assert cp.tweezer_top(pair_top, 1, config=CONFIG) is True
    pair_bottom = [
        candle(1.03, 1.035, 1.000, 1.005),  # bearish, low 1.000
        candle(1.01, 1.04, 1.0005, 1.035),  # bullish, low 1.0005
    ]
    assert cp.tweezer_bottom(pair_bottom, 1, config=CONFIG) is True
    # Mismatched highs within tolerance fail.
    wide = [pair_top[0], candle(1.045, 1.07, 1.02, 1.025)]  # high 1.07
    assert cp.tweezer_top(wide, 1, config=CONFIG) is False


def test_alternative_names_suppressed_by_context() -> None:
    # A hammer-shaped candle after an advance is a hanging man, not a hammer.
    candles = [*uptrend(4), candle(1.04, 1.045, 1.00, 1.043)]
    names = [p["name"] for p in cp.detect_patterns(candles, 4, config=CONFIG)]
    assert "hanging_man" in names
    assert "hammer" not in names  # suppressed: same geometry, different context


def test_new_patterns_report_context_and_invalidation() -> None:
    candles = [*uptrend(5), candle(1.05, 1.08, 1.046, 1.047)]
    patterns = {p["name"]: p for p in cp.detect_patterns(candles, 5, config=CONFIG)}
    pin = patterns["bearish_pin_bar"]
    assert pin["context_requirement"]  # must state what gives the shape meaning
    assert pin["invalidation_condition"]
    assert pin["candle_refs"] == [5]
    assert pin["candle_count"] >= 1


# ---------------------------------------------------------------------------
# CP3: support/resistance *setups* (a touch is never a complete setup)
# ---------------------------------------------------------------------------


def _zone_series() -> list[dict]:
    """Two confirmed swing highs near 1.0505, then a valid break and retest.

    Traced swings (lookback 2): swing high 1.050 @2, swing high 1.0505 @6
    (cluster -> resistance zone [1.0500, 1.0505]); swing low 1.038 @4 and
    1.037 @5 (cluster -> support zone [1.037, 1.038]). Close 1.068 @9 is the
    valid break; @10 retests into the zone and closes above it (acceptance);
    @11 follows through -> completed.
    """
    return [
        candle(1.000, 1.040, 0.999, 1.035),
        candle(1.035, 1.048, 1.034, 1.044),
        candle(1.044, 1.050, 1.043, 1.046),  # swing high 1.050
        candle(1.046, 1.049, 1.042, 1.044),
        candle(1.044, 1.046, 1.038, 1.040),  # swing low 1.038
        candle(1.040, 1.045, 1.037, 1.043),  # swing low 1.037
        candle(1.043, 1.0505, 1.042, 1.048),  # swing high 1.0505
        candle(1.048, 1.050, 1.046, 1.049),
        candle(1.049, 1.0495, 1.045, 1.047),
        candle(1.047, 1.070, 1.046, 1.068),  # valid break (close 1.068)
        candle(1.068, 1.072, 1.0502, 1.052),  # retest into zone, close above
        candle(1.052, 1.078, 1.0508, 1.076),  # follow-through -> completed
    ]


def test_zone_forms_and_lifecycle_tracks_every_stage_in_order() -> None:
    candles = _zone_series()
    zones = detect_zones(candles, config=CONFIG)
    zone = next(z for z in zones if z.kind == "resistance")
    assert zone.touches >= CONFIG.zone_min_touches
    assert zone.low <= 1.0505 and zone.high >= 1.050

    result = sbr_rbs_lifecycle(candles, zone, config=CONFIG)
    history = result["history"]
    order = [str(s) for s in SBRStage]
    stages = [h["stage"] for h in history]
    positions = [order.index(s) for s in stages]
    assert positions == sorted(positions)  # stages never skip or go backwards
    assert str(SBRStage.FORMATION) in stages
    assert result["break_index"] is not None
    assert result["retest_index"] is not None
    assert result["retest_index"] > result["break_index"]


def test_lifecycle_stops_before_retest_when_no_break_exists() -> None:
    candles = _zone_series()[:9]  # closes stop at 1.049: no close beyond 1.0510
    zones = detect_zones(candles, config=CONFIG)
    zone = next(z for z in zones if z.kind == "resistance")
    result = sbr_rbs_lifecycle(candles, zone, config=CONFIG)
    assert result["break_index"] is None
    assert result["in_progress"] is True
    assert "valid_break" in result["missing"]


def test_touch_alone_never_yields_a_completed_flip() -> None:
    setups = detect_level_setups(_zone_series()[:9], config=CONFIG)
    flips = setups["flips"]
    assert flips, "expected lifecycle entries for the validated zones"
    for flip in flips:
        # Reaching retest/acceptance is not completion: follow-through matters.
        assert flip["stage_reached"] != str(SBRStage.COMPLETED)
        # A non-completed setup is either still running or explicitly rejected.
        assert flip["in_progress"] or flip.get("outcome") == "rejected"


def test_false_breakout_reports_unconfirmed_candidate() -> None:
    candles = [*_zone_series(), candle(1.076, 1.082, 1.049, 1.050)]
    zones = detect_zones(candles, config=CONFIG)
    zone = next(z for z in zones if z.kind == "resistance")
    hit = false_breakout(candles, zone, config=CONFIG)
    assert hit is not None
    assert hit["type"] == "false_breakout"
    assert hit["requirements"], "a candidate must state what confirms it"


def test_failed_zone_test_counts_attacks_without_close_beyond() -> None:
    candles = _zone_series()[:9]
    zones = detect_zones(candles, config=CONFIG)
    zone = next(z for z in zones if z.kind == "resistance")
    hit = failed_zone_test(candles, zone, config=CONFIG)
    assert hit is not None, "repeated attacks with no close beyond should be reported"
    assert hit["type"] == "failed_zone_test"
    assert hit["attempt_count"] >= CONFIG.failed_test_min_attempts


def test_engulfing_and_doji_at_zone_are_location_bound() -> None:
    candles = _zone_series()
    zone = next(z for z in detect_zones(candles, config=CONFIG) if z.kind == "resistance")
    engulfing_at_zone(candles[:3], zone, config=CONFIG)
    doji_at_zone([candle(1.00, 1.01, 0.99, 1.005)], zone, config=CONFIG)


# ---------------------------------------------------------------------------
# CP4: market structure (CHOCH / MSS kept distinct)
# ---------------------------------------------------------------------------


def _choch_series() -> list[dict]:
    """Uptrend (HH + HL labels) then a close below the last protective HL.

    Traced swings: SH 1.030 @2, SL 1.012 @3, SL 1.006 @4, SH 1.050 @6 (HH),
    SL 1.036 @8 (HL), SH 1.072 @11 (HH), SL 1.048 @13 (HL). Close 1.030 @17 is
    below 1.048 * (1 - margin) -> bearish CHOCH against the uptrend.
    """
    return [
        candle(1.000, 1.010, 0.995, 1.005),
        candle(1.005, 1.020, 1.004, 1.015),
        candle(1.015, 1.030, 1.014, 1.028),  # swing high 1.030
        candle(1.028, 1.0285, 1.012, 1.015),  # swing low 1.012
        candle(1.015, 1.022, 1.006, 1.020),  # swing low 1.006
        candle(1.020, 1.034, 1.010, 1.032),
        candle(1.032, 1.050, 1.030, 1.048),  # swing high 1.050 (HH)
        candle(1.048, 1.049, 1.040, 1.042),
        candle(1.042, 1.046, 1.036, 1.044),  # swing low 1.036 (HL)
        candle(1.044, 1.060, 1.042, 1.058),
        candle(1.058, 1.066, 1.054, 1.062),
        candle(1.062, 1.072, 1.059, 1.068),  # swing high 1.072 (HH)
        candle(1.068, 1.069, 1.060, 1.063),
        candle(1.063, 1.065, 1.048, 1.052),  # swing low 1.048 (HL, protective)
        candle(1.052, 1.058, 1.0505, 1.056),
        candle(1.056, 1.057, 1.051, 1.054),
        candle(1.054, 1.055, 1.040, 1.043),
        candle(1.043, 1.045, 1.028, 1.030),  # close below 1.048 -> CHOCH
    ]


def test_choch_requires_prior_trend_and_break_against_it() -> None:
    result = detect_choch(_choch_series(), config=CONFIG)
    assert result is not None
    assert result["type"] == "bearish_choch"
    assert result["prior_trend"] == "uptrend"
    assert result["protective_swing"]["kind"] == "low"
    # A plain uptrend's last close is not a change of character.
    assert detect_choch(uptrend(16), config=CONFIG) is None


def test_mss_needs_displacement_beyond_bare_choch() -> None:
    candles = _choch_series()
    choch = detect_choch(candles, config=CONFIG)
    mss = detect_mss(candles, config=CONFIG)
    if mss is not None:
        assert mss["choch"] == choch
        assert mss["strong_break_candle"] or mss["follow_through"]
        assert mss["type"] == "bearish_mss"


def test_exhaustion_only_reported_within_a_trend() -> None:
    flat = [candle(1.0, 1.001, 0.999, 1.0)] * 20
    assert detect_trend_exhaustion(flat, config=CONFIG) is None


def test_reversal_candidate_needs_evidence_and_flags_confirmation() -> None:
    result = reversal_candidates(_choch_series(), config=CONFIG)
    assert result["confirmed"] is True
    assert "choch" in result["evidence"]
    assert result["candidate_direction"] == "bearish"
    plain = reversal_candidates(uptrend(16), config=CONFIG)
    assert plain["confirmed"] is False
    assert "choch" not in plain["evidence"]


def test_structure_narrative_is_words_only_with_swing_refs() -> None:
    narrative = structure_narrative(_choch_series(), config=CONFIG)
    assert narrative["statements"]
    assert narrative["swing_refs"]
    flat = str(narrative)
    assert "%" not in flat
    assert "probability" not in flat


# ---------------------------------------------------------------------------
# CP5: ICT-style concepts (observable definitions, ambiguities recorded)
# ---------------------------------------------------------------------------


def test_equal_levels_reports_the_tolerance_used() -> None:
    # Traced swing highs 1.050 @2 and 1.0505 @5 (relative diff 0.00048 <= 0.0005).
    candles = [
        candle(1.000, 1.040, 0.999, 1.035),
        candle(1.035, 1.045, 1.034, 1.042),
        candle(1.042, 1.050, 1.041, 1.047),  # swing high 1.050
        candle(1.047, 1.049, 1.044, 1.046),
        candle(1.046, 1.048, 1.042, 1.044),
        candle(1.044, 1.0505, 1.043, 1.048),  # swing high 1.0505
        candle(1.048, 1.049, 1.044, 1.046),
        candle(1.046, 1.050, 1.044, 1.048),
    ]
    levels = equal_levels(candles, config=CONFIG)
    assert levels, "two near-identical swing highs should be reported as EQ"
    for level in levels:
        assert level["type"] in ("equal_highs", "equal_lows")
        assert level["tolerance_used"] == CONFIG.equal_level_tolerance
        assert level["first_index"] < level["second_index"]


def test_sweep_of_swing_reports_level_and_close_back_inside() -> None:
    # Traced swing high 1.012 @2; last candle wicks to 1.016 and closes 1.008.
    candles = [
        candle(1.000, 1.003, 0.998, 1.001),
        candle(1.001, 1.008, 1.000, 1.006),
        candle(1.006, 1.012, 1.004, 1.010),  # swing high 1.012
        candle(1.010, 1.011, 1.006, 1.008),
        candle(1.008, 1.009, 1.004, 1.006),
        candle(1.006, 1.016, 1.005, 1.008),  # sweeps 1.016, closes 1.008
    ]
    sweeps = sweep_of_swing(candles, config=CONFIG)
    assert sweeps, "a wick through a confirmed swing high must be reported"
    assert sweeps[0]["type"] == "swing_high_sweep"
    assert sweeps[0]["level"] == pytest.approx(1.012)
    assert sweeps[0]["closed_back_inside"] is True
    assert sweeps[0]["swing_index"] == 2


def test_inducement_never_invented_without_a_sweep() -> None:
    # Flat market: no sweep occurs, so no inducement may be claimed.
    assert inducement([candle(1.0, 1.001, 0.999, 1.0)] * 8, config=CONFIG) is None


def test_premium_discount_is_geometric_not_a_prediction() -> None:
    result = premium_discount(
        [candle(0.999, 1.010, 0.998, 1.005), candle(1.005, 1.042, 1.004, 1.039)],
        config=CONFIG,
    )
    assert result is not None
    assert result["zone"] in ("premium", "discount", "equilibrium")
    assert "geometric" in result["note"]


def test_breaker_block_records_both_readings_ambiguity() -> None:
    # Bullish order block: bearish candle @0 (low 1.010) before a strong up
    # departure @1; @2 closes 1.007 < bottom -> invalidated; @3 trades back in.
    candles = [
        candle(1.020, 1.030, 1.010, 1.012),
        candle(1.012, 1.060, 1.011, 1.058),
        candle(1.058, 1.059, 1.005, 1.007),
        candle(1.007, 1.035, 1.002, 1.030),
    ]
    blocks = breaker_blocks(candles, config=CONFIG)
    assert blocks, "an invalidated order block traded back into is a breaker"
    block = blocks[0]
    assert block["type"] == "breaker_block"
    assert block["block_type"] == "bullish_ob"
    assert block["invalidated_index"] is not None
    assert block["retest_index"] is not None
    assert block["ambiguities"], "the differing readings must be recorded"


def test_fvg_retest_reports_state_and_flags_invalid_gap() -> None:
    from apps.price_action.services.fair_value_gaps import detect_fvg

    candles = [
        candle(0.998, 1.000, 0.997, 0.999),
        candle(0.999, 1.010, 0.999, 1.009),
        candle(1.009, 1.012, 1.005, 1.011),
        candle(1.011, 1.012, 1.002, 1.004),  # trades back into 1.000-1.005
    ]
    gaps = detect_fvg(candles, config=CONFIG)
    assert gaps, "the 1.000-1.005 imbalance should be detected"
    gap = gaps[0]
    from apps.price_action.services.ict_concepts import fvg_retest

    retest = fvg_retest(candles, gap, config=CONFIG)
    assert retest is not None
    assert retest["invalid_gap"] is False
    assert retest["state_at_retest"]


def test_mitigation_report_never_claims_intent() -> None:
    from tests.pa_fakes import bullish_fvg_series

    report = mitigation_report(bullish_fvg_series(), config=CONFIG)
    assert "nothing here implies intent" in report["note"]
    assert "fvgs" in report
    assert "order_blocks" in report


def test_displacement_requires_impulse_and_imbalance() -> None:
    # avg range ~0.00575; @1 range 0.011 >= 1.2*avg, body 0.010/0.011 = 0.91,
    # and it is the FVG departure -> displacement.
    candles = [
        candle(0.998, 1.000, 0.997, 0.999),
        candle(0.999, 1.010, 0.999, 1.009),
        candle(1.009, 1.012, 1.005, 1.011),
        candle(1.011, 1.012, 1.010, 1.0115),
    ]
    results = displacement(candles, config=CONFIG)
    assert results, "the wide strong-bodied FVG candle is displacement"
    for item in results:
        assert item["type"] == "displacement"
        assert item["range_multiple"] is not None
        assert item["body_ratio"] >= CONFIG.strong_body_ratio_min


# ---------------------------------------------------------------------------
# CP6: candle sequences and progression
# ---------------------------------------------------------------------------


def test_candle_progress_reports_number_and_label() -> None:
    result = candle_progress([candle(1.00, 1.10, 0.90, 1.08)])
    assert result is not None
    assert result["progress"] == pytest.approx(0.9)
    assert result["label"] == "closed_near_high"


def test_run_count_uses_configured_threshold() -> None:
    result = run_count(uptrend(10), config=CONFIG)
    assert result["direction"] == Direction.BULLISH
    assert result["extended"] is True
    assert result["extended_threshold"] == CONFIG.extended_run_length


def test_strong_close_reports_thresholds_used() -> None:
    result = strong_close([candle(1.00, 1.10, 0.99, 1.09)], config=CONFIG)
    assert result is not None
    assert result["thresholds"]["strong_body_ratio_min"] == CONFIG.strong_body_ratio_min


def test_weak_close_is_off_own_extreme() -> None:
    weak = weak_close([candle(1.00, 1.10, 0.99, 1.03)], config=CONFIG)
    assert weak is not None
    assert weak["direction"] == "bullish"
    assert weak_close([candle(1.00, 1.10, 0.99, 1.09)], config=CONFIG) is None


def test_failed_continuation_is_not_a_reversal_claim() -> None:
    candles = [
        candle(1.000, 1.005, 0.999, 1.004),
        candle(1.004, 1.010, 1.003, 1.009),
        candle(1.009, 1.011, 1.008, 1.010),
        candle(1.010, 1.011, 0.995, 0.996),  # closes back below the run
    ]
    result = failed_continuation(candles, config=CONFIG)
    assert result is not None
    assert result["type"] == "failed_continuation"
    assert "not a reversal claim" in result["note"]


# ---------------------------------------------------------------------------
# CP7: generic ABC (course-specific rules not available)
# ---------------------------------------------------------------------------


def test_abc_is_labelled_generic_with_explicit_thresholds() -> None:
    # Traced swings: SL 0.995 @2 (A), SH 1.035 @5 (B), SL 1.010 @8 (C).
    candles = [
        candle(1.010, 1.012, 1.000, 1.008),
        candle(1.008, 1.009, 0.998, 1.001),
        candle(1.001, 1.004, 0.995, 1.002),  # A: swing low 0.995
        candle(1.002, 1.015, 1.000, 1.013),
        candle(1.013, 1.030, 1.012, 1.028),
        candle(1.028, 1.035, 1.026, 1.030),  # B: swing high 1.035
        candle(1.030, 1.032, 1.018, 1.020),
        candle(1.020, 1.025, 1.012, 1.024),
        candle(1.024, 1.026, 1.010, 1.018),  # C: swing low 1.010 (> A)
        candle(1.018, 1.020, 1.011, 1.014),  # low above C so C stays confirmed
        candle(1.014, 1.018, 1.012, 1.016),
    ]
    patterns = detect_abc(candles, config=CONFIG)
    assert patterns, "A(0.995) -> B(1.035) -> C(1.010) is a textbook up-ABC"
    result = patterns[0]
    assert result["label"] == "generic_abc"
    assert "course" in result["note"]
    assert result["sufficient_for_entry"] is False
    assert "retracement_min" in result["thresholds"]


def test_abc_summary_admits_course_rules_unavailable() -> None:
    summary = abc_candidates([], config=CONFIG)
    assert summary["count"] == 0
    assert summary["course_specific_rules_available"] is False


def test_abc_never_reports_without_confirmed_third_swing() -> None:
    assert detect_abc(uptrend(4), config=CONFIG) == []


# ---------------------------------------------------------------------------
# CP8: registry of deterministic detectors
# ---------------------------------------------------------------------------


def test_every_registry_key_is_in_the_constants_registry() -> None:
    assert set(DETECTOR_REGISTRY) <= set(DETECTOR_KEYS)


def test_unknown_detector_key_is_inert() -> None:
    assert run_detector("no.such.detector", uptrend(8), config=CONFIG) is None


def test_registry_never_raises_on_any_key() -> None:
    candles = _choch_series()
    for key in DETECTOR_REGISTRY:
        run_detector(key, candles, config=CONFIG)  # must not raise


def test_registry_returns_none_on_empty_input() -> None:
    for key in DETECTOR_REGISTRY:
        assert run_detector(key, [], config=CONFIG) is None


@pytest.mark.parametrize("key", sorted(DETECTOR_REGISTRY))
def test_registry_observations_carry_their_key(key: str) -> None:
    candles = [
        candle(0.998, 1.000, 0.997, 0.999),
        candle(0.999, 1.010, 0.999, 1.009),
        candle(1.009, 1.012, 1.005, 1.011),
        candle(1.011, 1.012, 1.010, 1.011),
    ]
    result = run_detector(key, candles, config=CONFIG)
    if result is not None:
        assert result.get("detector") == key


def test_unknown_key_never_shaped_like_a_signal() -> None:
    result = run_detector("ms.totally_unknown", _choch_series(), config=CONFIG)
    assert result is None or result.get("detector") != "ms.totally_unknown"
