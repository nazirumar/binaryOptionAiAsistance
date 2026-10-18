"""Registry of deterministic detectors referenced by ``detector_key``.

This module is the *only* bridge between stored strategy definitions and
executable detection logic. A definition whose key is absent from
:data:`DETECTOR_REGISTRY` is inert: the library displays it, but no detection
can ever be produced from it. Nothing here evaluates expressions from the
database — keys are matched against a fixed dict of callables.

Every entry has the signature ``fn(candles, config) -> dict | None`` and
returns a compact observation (never a trade, never a probability).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apps.price_action.services import candlestick_patterns as cs
from apps.price_action.services import ict_concepts as ict
from apps.price_action.services import level_setups as ls
from apps.price_action.services import market_structure as ms
from apps.price_action.services.abc_pattern import detect_abc
from apps.price_action.services.buyer_seller_failure import detect_buyer_seller_failure
from apps.price_action.services.candle_sequences import (
    candle_progress,
    failed_continuation,
    lonely_candles,
    psych_sequences,
    run_count,
    similar_sequences,
    strong_close,
    weak_close,
)
from apps.price_action.services.config import PriceActionConfig
from apps.price_action.services.fair_value_gaps import detect_fvg
from apps.price_action.services.liquidity_sweeps import detect_sweep
from apps.price_action.services.market_cycle import classify_cycle
from apps.price_action.services.order_blocks import detect_order_blocks
from apps.price_action.services.support_resistance import detect_zones

Detector = Callable[[list[dict[str, Any]], PriceActionConfig], dict[str, Any] | None]


def _last_index(candles: list[dict[str, Any]]) -> int | None:
    return len(candles) - 1 if candles else None


def _cs(name: str) -> Detector:
    """Wrap a candlestick predicate into a detector observation."""

    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        i = _last_index(candles)
        if i is None:
            return None
        fn = getattr(cs, name)
        matched = fn(candles, i, config=config) if name in _CS_WITH_CONFIG else fn(candles, i)
        if not matched:
            return None
        return {"detector": f"cs.{name}", "index": i, "matched": True}

    return run


#: Candlestick detectors that accept a config keyword argument.
_CS_WITH_CONFIG = {
    "bullish_pin_bar",
    "bearish_pin_bar",
    "dragonfly_doji",
    "gravestone_doji",
    "spinning_top",
    "tweezer_top",
    "tweezer_bottom",
    "morning_star",
    "evening_star",
    "three_white_soldiers",
    "three_black_crows",
}


def _sr_rejection(side: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        for zone in detect_zones(candles, config=config):
            if str(zone.kind) != side:
                continue
            from apps.price_action.services.support_resistance import detect_rejection

            rejection = detect_rejection(candles, zone, config=config)
            if rejection:
                return {"detector": f"sr.{side}_rejection", "zone_price": zone.price, **rejection}
        return None

    return run


def _sr_flip(kind: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        for zone in detect_zones(candles, config=config):
            expected = (
                "support_became_resistance"
                if kind == "support_becomes_resistance"
                else "resistance_became_support"
            )
            if str(zone.kind) != ("support" if kind.startswith("support") else "resistance"):
                continue
            lifecycle = ls.sbr_rbs_lifecycle(candles, zone, config=config)
            if lifecycle["type"] == expected and lifecycle["stage_reached"] in (
                "acceptance",
                "completed",
                "invalidated",
            ):
                return {"detector": f"sr.{kind}", **lifecycle}
        return None

    return run


def _zone_last(setup_name: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        for zone in detect_zones(candles, config=config):
            if setup_name == "false_breakout":
                result = ls.false_breakout(candles, zone, config=config)
            elif setup_name == "multi_touch":
                if zone.touches < config.zone_min_touches:
                    continue
                result = {"type": "multi_touch", "touches": zone.touches, "level": zone.price}
            else:
                continue
            if result:
                return {"detector": f"sr.{setup_name}", **result}
        return None

    return run


def _at_level(setup_name: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        for zone in detect_zones(candles, config=config):
            if setup_name == "engulfing_at_support" and str(zone.kind) != "support":
                continue
            if setup_name == "engulfing_at_resistance" and str(zone.kind) != "resistance":
                continue
            if setup_name == "doji_above_support" and str(zone.kind) != "support":
                continue
            if setup_name == "doji_below_resistance" and str(zone.kind) != "resistance":
                continue
            fn = ls.engulfing_at_zone if setup_name.startswith("engulfing") else ls.doji_at_zone
            result = fn(candles, zone, config=config)
            if result:
                return {"detector": f"sr.{setup_name}", **result}
        return None

    return run


def _sr_failed(side: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        for zone in detect_zones(candles, config=config):
            if str(zone.kind) != side:
                continue
            result = ls.failed_zone_test(candles, zone, config=config)
            if result:
                return {"detector": f"sr.failed_{side}_test", **result}
        return None

    return run


def _structure(event: str, kind: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        if event == "bos":
            result = ms.detect_structure_break(candles, config.swing_lookback)
            if result and result["type"] == f"{kind}_bos":
                return {"detector": f"ms.bos_{kind}", **result}
            return None
        if event == "choch":
            result = ms.detect_choch(candles, config=config)
            if result and result["type"] == f"{kind}_choch":
                return {"detector": f"ms.choch_{kind}", **result}
            return None
        result = ms.detect_mss(candles, config=config)
        if result and result["type"] == f"{kind}_mss":
            return {"detector": f"ms.mss_{kind}", **result}
        return None

    return run


def _ms_exhaustion(
    candles: list[dict[str, Any]], config: PriceActionConfig
) -> dict[str, Any] | None:
    result = ms.detect_trend_exhaustion(candles, config=config)
    return {"detector": "ms.trend_exhaustion", **result} if result else None


def _ms_failed_break(
    candles: list[dict[str, Any]], config: PriceActionConfig
) -> dict[str, Any] | None:
    result = ms.detect_failed_breakout(candles, config.swing_lookback)
    return {"detector": "ms.failed_structural_break", **result} if result else None


def _liq_sweep(side: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        want = "high_sweep" if side == "bearish" else "low_sweep"
        for sweep in detect_sweep(candles, config=config):
            if sweep["type"] == want:
                return {"detector": f"liq.{side}_sweep", **sweep}
        return None

    return run


def _liq_equal(side: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        want = "equal_highs" if side == "equal_highs" else "equal_lows"
        for level in ict.equal_levels(candles, config=config):
            if level["type"] == want:
                return {"detector": f"liq.{side}", **level}
        return None

    return run


def _ict(name: str) -> Detector:
    fn_map: dict[str, Callable[..., Any]] = {
        "inducement": ict.inducement,
        "premium_discount": ict.premium_discount,
    }

    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        result = fn_map[name](candles, config=config)
        return {"detector": f"zone.{name}", **result} if result else None

    return run


def _ict_list(name: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        if name == "displacement":
            results = ict.displacement(candles, config=config)
        else:
            results = ict.breaker_blocks(candles, config=config)
        if not results:
            return None
        return {"detector": f"{'liq' if name == 'displacement' else 'ob'}.{name}", **results[-1]}

    return run


def _fvg(direction: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        want = "bullish_fvg" if direction == "bullish" else "bearish_fvg"
        for gap in detect_fvg(candles, config=config):
            if gap["type"] == want:
                return {"detector": f"fvg.{direction}", **gap}
        return None

    return run


def _fvg_retest(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
    for gap in detect_fvg(candles, config=config):
        result = ict.fvg_retest(candles, gap, config=config)
        if result and not result["invalid_gap"]:
            return {"detector": "fvg.retest", **result}
    return None


def _ob(direction: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        want = "bullish_ob" if direction == "bullish" else "bearish_ob"
        for zone in detect_order_blocks(candles, config=config):
            if zone["type"] == want and not zone.get("rejected"):
                return {"detector": f"ob.{direction}", **zone}
        return None

    return run


def _ob_mitigation(
    candles: list[dict[str, Any]], config: PriceActionConfig
) -> dict[str, Any] | None:
    """Fire only when at least one order block has actually been traded back into."""
    report = ict.mitigation_report(candles, config=config)
    mitigated = report["order_blocks"]["mitigated"]
    if not mitigated:
        return None
    return {"detector": "ob.mitigation", "mitigated": mitigated, "note": report["note"]}


def _cycle(phase: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        result = classify_cycle(candles, config=config)
        phase_key = {
            "motive_wave": "original_motive",
            "counter_wave": "counter_wave",
            "weak_last_effort": "last_effort",
            "new_motive_wave": "new_opposing_motive",
        }[phase]
        if result.get("phase") == phase_key:
            return {"detector": f"cycle.{phase}", **result}
        return None

    return run


def _psy_failure(side: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        result = detect_buyer_seller_failure(candles, config=config)
        if not result:
            return None
        events = result.get("events", []) if isinstance(result, dict) else []
        wanted = "buyers_created_support" if side == "buyer" else "sellers_created_resistance"
        for event in events:
            if event.get("type") == wanted:
                return {"detector": f"psy.{side}_failure", **event}
        return None

    return run


def _psy_simple(name: str) -> Detector:
    def run(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
        if name == "candle_progress":
            result = candle_progress(candles)
        elif name == "run_count":
            result = run_count(candles, config=config)
        elif name == "strong_close":
            result = strong_close(candles, config=config)
        elif name == "weak_close":
            result = weak_close(candles, config=config)
        elif name == "failed_continuation":
            result = failed_continuation(candles, config=config)
        else:  # reference_sequence
            from apps.price_action.services.candle_sequences import analyze_reference_sequences

            result = analyze_reference_sequences(candles, config=config)
        if not result:
            return None
        return {"detector": f"psy.{name}", **result}

    return run


def _psy_lonely(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
    result = lonely_candles(candles, config=config)
    if not result:
        return None
    last = result[-1] if isinstance(result, list) and result else None
    return {"detector": "psy.lonely_candle", **last} if last else None


def _psy_similar(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
    result = similar_sequences(candles, config=config)
    if not result.get("available") or not result.get("matches"):
        return None
    return {"detector": "psy.similar_sequence", **result}


def _psy_templates(
    candles: list[dict[str, Any]], config: PriceActionConfig
) -> dict[str, Any] | None:
    matches = psych_sequences(candles, config=config)
    if not matches:
        return None
    return {"detector": "psy.reference_sequence", **matches[-1]}


def _abc(candles: list[dict[str, Any]], config: PriceActionConfig) -> dict[str, Any] | None:
    candidates = detect_abc(candles, config=config)
    if not candidates:
        return None
    return {"detector": "abc.generic", **candidates[-1]}


#: Fixed mapping of detector keys → deterministic callables. Definitions that
#: reference a key outside this dict are inert by design.
DETECTOR_REGISTRY: dict[str, Detector] = {
    # candlestick
    "cs.bullish_engulfing": _cs("bullish_engulfing"),
    "cs.bearish_engulfing": _cs("bearish_engulfing"),
    "cs.bullish_pin_bar": _cs("bullish_pin_bar"),
    "cs.bearish_pin_bar": _cs("bearish_pin_bar"),
    "cs.hammer": _cs("hammer"),
    "cs.inverted_hammer": _cs("inverted_hammer"),
    "cs.shooting_star": _cs("shooting_star"),
    "cs.hanging_man": _cs("hanging_man"),
    "cs.doji": _cs("doji"),
    "cs.dragonfly_doji": _cs("dragonfly_doji"),
    "cs.gravestone_doji": _cs("gravestone_doji"),
    "cs.spinning_top": _cs("spinning_top"),
    "cs.bullish_harami": _cs("bullish_harami"),
    "cs.bearish_harami": _cs("bearish_harami"),
    "cs.inside_bar": _cs("inside_bar"),
    "cs.outside_bar": _cs("outside_bar"),
    "cs.morning_star": _cs("morning_star"),
    "cs.evening_star": _cs("evening_star"),
    "cs.three_white_soldiers": _cs("three_white_soldiers"),
    "cs.three_black_crows": _cs("three_black_crows"),
    "cs.tweezer_top": _cs("tweezer_top"),
    "cs.tweezer_bottom": _cs("tweezer_bottom"),
    "cs.piercing": _cs("piercing"),
    "cs.dark_cloud_cover": _cs("dark_cloud_cover"),
    # support/resistance
    "sr.support_rejection": _sr_rejection("support"),
    "sr.resistance_rejection": _sr_rejection("resistance"),
    "sr.support_becomes_resistance": _sr_flip("support_becomes_resistance"),
    "sr.resistance_becomes_support": _sr_flip("resistance_becomes_support"),
    "sr.breakout_retest": _sr_flip("resistance_became_support"),
    "sr.false_breakout": _zone_last("false_breakout"),
    "sr.multi_touch": _zone_last("multi_touch"),
    "sr.failed_support_test": _sr_failed("support"),
    "sr.failed_resistance_test": _sr_failed("resistance"),
    "sr.engulfing_at_support": _at_level("engulfing_at_support"),
    "sr.engulfing_at_resistance": _at_level("engulfing_at_resistance"),
    "sr.doji_above_support": _at_level("doji_above_support"),
    "sr.doji_below_resistance": _at_level("doji_below_resistance"),
    # market structure
    "ms.bos_bullish": _structure("bos", "bullish"),
    "ms.bos_bearish": _structure("bos", "bearish"),
    "ms.choch_bullish": _structure("choch", "bullish"),
    "ms.choch_bearish": _structure("choch", "bearish"),
    "ms.mss_bullish": _structure("mss", "bullish"),
    "ms.mss_bearish": _structure("mss", "bearish"),
    "ms.trend_exhaustion": _ms_exhaustion,
    "ms.failed_structural_break": _ms_failed_break,
    # liquidity / ICT
    "liq.bearish_sweep": _liq_sweep("bearish"),
    "liq.bullish_sweep": _liq_sweep("bullish"),
    "liq.equal_highs": _liq_equal("equal_highs"),
    "liq.equal_lows": _liq_equal("equal_lows"),
    "liq.inducement": _ict("inducement"),
    "liq.displacement": _ict_list("displacement"),
    "ob.breaker": _ict_list("breaker_blocks"),
    "ob.mitigation": _ob_mitigation,
    "zone.premium_discount": _ict("premium_discount"),
    # FVG / order blocks
    "fvg.bullish": _fvg("bullish"),
    "fvg.bearish": _fvg("bearish"),
    "fvg.retest": _fvg_retest,
    "ob.bullish": _ob("bullish"),
    "ob.bearish": _ob("bearish"),
    # cycle / psychology
    "cycle.motive_wave": _cycle("motive_wave"),
    "cycle.counter_wave": _cycle("counter_wave"),
    "cycle.weak_last_effort": _cycle("weak_last_effort"),
    "cycle.new_motive_wave": _cycle("new_motive_wave"),
    "psy.buyer_failure": _psy_failure("buyer"),
    "psy.seller_failure": _psy_failure("seller"),
    "psy.reference_sequence": _psy_templates,
    "psy.similar_sequence": _psy_similar,
    "psy.lonely_candle": _psy_lonely,
    "psy.candle_progress": _psy_simple("candle_progress"),
    "psy.run_count": _psy_simple("run_count"),
    "psy.strong_close": _psy_simple("strong_close"),
    "psy.weak_close": _psy_simple("weak_close"),
    "psy.failed_continuation": _psy_simple("failed_continuation"),
    # ABC
    "abc.generic": _abc,
}


def run_detector(
    detector_key: str,
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """Run the detector registered under ``detector_key`` (never a DB expression).

    Unknown keys and detector failures return ``None`` — a broken definition
    degrades to "no evidence", never to an error surface or a fabricated hit.
    """
    fn = DETECTOR_REGISTRY.get(detector_key)
    if fn is None or not candles:
        return None
    config = config or PriceActionConfig.from_settings()
    try:
        return fn(candles, config)
    except Exception:
        return None


__all__ = ["DETECTOR_REGISTRY", "run_detector"]
