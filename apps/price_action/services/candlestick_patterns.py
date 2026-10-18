"""Candlestick pattern engine (Step 7).

Each pattern is defined independently of any trading decision. The ``detect_*``
boolean predicates answer "did this shape occur at index ``i``?"; the
:func:`detect_patterns` aggregator additionally returns the required candle
count, the candle references, the contextual requirement and the invalidation
condition, so downstream phases never have to guess them.

Only *completed* candles may be passed in by the engine; a pattern that needs a
later candle is simply not reported until that candle closes.
"""

from __future__ import annotations

from typing import Any

from apps.price_action.constants import PatternDirection
from apps.price_action.services.candle_math import (
    body_range_ratio,
    is_bearish,
    is_bullish,
    is_doji,
    lower_wick_ratio,
    real_body_bottom,
    real_body_top,
    upper_wick_ratio,
)
from apps.price_action.services.config import PriceActionConfig

Pattern = dict[str, Any]


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


def _mid(candle: dict[str, Any]) -> float:
    return (_f(candle, "open") + _f(candle, "close")) / 2.0


def bullish_engulfing(candles: list[dict[str, Any]], i: int) -> bool:
    if i < 1:
        return False
    prev, cur = candles[i - 1], candles[i]
    return (
        is_bearish(prev)
        and is_bullish(cur)
        and _f(cur, "open") <= _f(prev, "close")
        and _f(cur, "close") >= _f(prev, "open")
    )


def bearish_engulfing(candles: list[dict[str, Any]], i: int) -> bool:
    if i < 1:
        return False
    prev, cur = candles[i - 1], candles[i]
    return (
        is_bullish(prev)
        and is_bearish(cur)
        and _f(cur, "open") >= _f(prev, "close")
        and _f(cur, "close") <= _f(prev, "open")
    )


def hammer(candles: list[dict[str, Any]], i: int, body_ratio_max: float = 0.30) -> bool:
    if i < 0 or i >= len(candles):
        return False
    c = candles[i]
    ratio = body_range_ratio(c)
    if ratio is None:
        return False
    lower = lower_wick_ratio(c) or 0.0
    upper = upper_wick_ratio(c) or 0.0
    return ratio <= body_ratio_max and lower >= 2 * upper and lower > 0


def shooting_star(candles: list[dict[str, Any]], i: int, body_ratio_max: float = 0.30) -> bool:
    if i < 0 or i >= len(candles):
        return False
    c = candles[i]
    ratio = body_range_ratio(c)
    if ratio is None:
        return False
    lower = lower_wick_ratio(c) or 0.0
    upper = upper_wick_ratio(c) or 0.0
    return ratio <= body_ratio_max and upper >= 2 * lower and upper > 0


def doji(candles: list[dict[str, Any]], i: int, doji_body_ratio_max: float = 0.12) -> bool:
    if i < 0 or i >= len(candles):
        return False
    return is_doji(candles[i], doji_body_ratio_max=doji_body_ratio_max)


def _inside_body(prev: dict[str, Any], cur: dict[str, Any]) -> bool:
    return real_body_top(cur) <= real_body_top(prev) and real_body_bottom(cur) >= real_body_bottom(
        prev
    )


def bullish_harami(candles: list[dict[str, Any]], i: int) -> bool:
    if i < 1:
        return False
    prev, cur = candles[i - 1], candles[i]
    return is_bearish(prev) and is_bullish(cur) and _inside_body(prev, cur)


def bearish_harami(candles: list[dict[str, Any]], i: int) -> bool:
    if i < 1:
        return False
    prev, cur = candles[i - 1], candles[i]
    return is_bullish(prev) and is_bearish(cur) and _inside_body(prev, cur)


def inside_bar(candles: list[dict[str, Any]], i: int) -> bool:
    if i < 1:
        return False
    prev, cur = candles[i - 1], candles[i]
    return _f(cur, "high") <= _f(prev, "high") and _f(cur, "low") >= _f(prev, "low")


def outside_bar(candles: list[dict[str, Any]], i: int) -> bool:
    if i < 1:
        return False
    prev, cur = candles[i - 1], candles[i]
    return _f(cur, "high") > _f(prev, "high") and _f(cur, "low") < _f(prev, "low")


def piercing(candles: list[dict[str, Any]], i: int) -> bool:
    if i < 1:
        return False
    prev, cur = candles[i - 1], candles[i]
    return (
        is_bearish(prev)
        and is_bullish(cur)
        and _f(cur, "open") < _f(prev, "close")
        and _mid(prev) < _f(cur, "close") < _f(prev, "open")
    )


def dark_cloud_cover(candles: list[dict[str, Any]], i: int) -> bool:
    if i < 1:
        return False
    prev, cur = candles[i - 1], candles[i]
    return (
        is_bullish(prev)
        and is_bearish(cur)
        and _f(cur, "open") > _f(prev, "close")
        and _f(prev, "open") < _f(cur, "close") < _mid(prev)
    )


def _is_star(candle: dict[str, Any], config: PriceActionConfig) -> bool:
    ratio = body_range_ratio(candle)
    return ratio is not None and ratio <= config.small_body_ratio_max


def morning_star(candles: list[dict[str, Any]], i: int, config: PriceActionConfig) -> bool:
    if i < 2:
        return False
    c1, c2, c3 = candles[i - 2], candles[i - 1], candles[i]
    return is_bearish(c1) and _is_star(c2, config) and is_bullish(c3) and _f(c3, "close") > _mid(c1)


def evening_star(candles: list[dict[str, Any]], i: int, config: PriceActionConfig) -> bool:
    if i < 2:
        return False
    c1, c2, c3 = candles[i - 2], candles[i - 1], candles[i]
    return is_bullish(c1) and _is_star(c2, config) and is_bearish(c3) and _f(c3, "close") < _mid(c1)


def three_white_soldiers(candles: list[dict[str, Any]], i: int, config: PriceActionConfig) -> bool:
    if i < 2:
        return False
    a, b, c = candles[i - 2], candles[i - 1], candles[i]
    bodies = [a, b, c]
    if not all(is_bullish(x) for x in bodies):
        return False
    if not (_f(a, "close") < _f(b, "close") < _f(c, "close")):
        return False
    return all((upper_wick_ratio(x) or 0.0) <= 0.30 for x in bodies)


def three_black_crows(candles: list[dict[str, Any]], i: int, config: PriceActionConfig) -> bool:
    if i < 2:
        return False
    a, b, c = candles[i - 2], candles[i - 1], candles[i]
    bodies = [a, b, c]
    if not all(is_bearish(x) for x in bodies):
        return False
    if not (_f(a, "close") > _f(b, "close") > _f(c, "close")):
        return False
    return all((lower_wick_ratio(x) or 0.0) <= 0.30 for x in bodies)


# ---------------------------------------------------------------------------
# Phase 12 (CP2) additions. Each predicate stays context-free; the aggregator
# attaches the trend/location requirement. Context-dependent twins (hanging
# man / inverted hammer) additionally require the *preceding* move so the same
# geometry is not claimed under two names at once.
# ---------------------------------------------------------------------------


def _close_position(candle: dict[str, Any]) -> float:
    """0.0 = close at the low of the range, 1.0 = close at the high."""
    rng = _f(candle, "high") - _f(candle, "low")
    if rng <= 0.0:
        return 0.5
    return (_f(candle, "close") - _f(candle, "low")) / rng


def _preceded_by_move(candles: list[dict[str, Any]], i: int, lookback: int) -> str:
    """Net direction of the ``lookback`` candles *before* ``i``.

    Returns ``"up"``, ``"down"`` or ``"none"``. Context only — never a signal.
    """
    if i < 1:
        return "none"
    start = max(0, i - lookback)
    net = _f(candles[i - 1], "close") - _f(candles[start], "open")
    if net > 0:
        return "up"
    if net < 0:
        return "down"
    return "none"


def bullish_pin_bar(
    candles: list[dict[str, Any]], i: int, *, config: PriceActionConfig | None = None
) -> bool:
    """Long lower wick, tiny upper wick, small body closing near the high."""
    config = config or PriceActionConfig.from_settings()
    if i < 0 or i >= len(candles):
        return False
    c = candles[i]
    body = body_range_ratio(c)
    if body is None:
        return False
    lower = lower_wick_ratio(c) or 0.0
    upper = upper_wick_ratio(c) or 0.0
    return (
        body <= config.pin_bar_max_body
        and lower >= config.pin_bar_wick_min
        and upper <= config.pin_bar_opposite_wick_max
        and _close_position(c) >= config.pin_bar_close_position
    )


def bearish_pin_bar(
    candles: list[dict[str, Any]], i: int, *, config: PriceActionConfig | None = None
) -> bool:
    """Long upper wick, tiny lower wick, small body closing near the low."""
    config = config or PriceActionConfig.from_settings()
    if i < 0 or i >= len(candles):
        return False
    c = candles[i]
    body = body_range_ratio(c)
    if body is None:
        return False
    lower = lower_wick_ratio(c) or 0.0
    upper = upper_wick_ratio(c) or 0.0
    return (
        body <= config.pin_bar_max_body
        and upper >= config.pin_bar_wick_min
        and lower <= config.pin_bar_opposite_wick_max
        and _close_position(c) <= 1.0 - config.pin_bar_close_position
    )


def _inverted_shape(candle: dict[str, Any], body_ratio_max: float) -> bool:
    ratio = body_range_ratio(candle)
    if ratio is None:
        return False
    lower = lower_wick_ratio(candle) or 0.0
    upper = upper_wick_ratio(candle) or 0.0
    return ratio <= body_ratio_max and upper >= 2 * lower and upper > 0


def inverted_hammer(
    candles: list[dict[str, Any]],
    i: int,
    body_ratio_max: float = 0.30,
    *,
    lookback: int = 3,
) -> bool:
    """Inverted-hammer *geometry* preceded by a decline (bullish candidate).

    Geometrically the same shape as a shooting star; the preceding decline is
    what distinguishes the two names. Without preceding context neither name
    is claimed here (``shooting_star`` remains the context-free predicate).
    """
    if i < 1 or i >= len(candles):
        return False
    return (
        _inverted_shape(candles[i], body_ratio_max)
        and _preceded_by_move(candles, i, lookback) == "down"
    )


def hanging_man(
    candles: list[dict[str, Any]],
    i: int,
    body_ratio_max: float = 0.30,
    *,
    lookback: int = 3,
) -> bool:
    """Hammer *geometry* preceded by an advance (bearish candidate)."""
    if i < 1 or i >= len(candles):
        return False
    c = candles[i]
    ratio = body_range_ratio(c)
    if ratio is None or ratio > body_ratio_max:
        return False
    lower = lower_wick_ratio(c) or 0.0
    upper = upper_wick_ratio(c) or 0.0
    if not (lower >= 2 * upper and lower > 0):
        return False
    return _preceded_by_move(candles, i, lookback) == "up"


def dragonfly_doji(
    candles: list[dict[str, Any]], i: int, *, config: PriceActionConfig | None = None
) -> bool:
    """Doji body with a dominant lower wick and essentially no upper wick."""
    config = config or PriceActionConfig.from_settings()
    if i < 0 or i >= len(candles):
        return False
    c = candles[i]
    if not is_doji(c, doji_body_ratio_max=config.doji_body_ratio_max):
        return False
    lower = lower_wick_ratio(c) or 0.0
    upper = upper_wick_ratio(c) or 0.0
    return lower >= config.doji_extreme_wick_min and upper <= config.doji_opposite_wick_max


def gravestone_doji(
    candles: list[dict[str, Any]], i: int, *, config: PriceActionConfig | None = None
) -> bool:
    """Doji body with a dominant upper wick and essentially no lower wick."""
    config = config or PriceActionConfig.from_settings()
    if i < 0 or i >= len(candles):
        return False
    c = candles[i]
    if not is_doji(c, doji_body_ratio_max=config.doji_body_ratio_max):
        return False
    lower = lower_wick_ratio(c) or 0.0
    upper = upper_wick_ratio(c) or 0.0
    return upper >= config.doji_extreme_wick_min and lower <= config.doji_opposite_wick_max


def spinning_top(
    candles: list[dict[str, Any]], i: int, *, config: PriceActionConfig | None = None
) -> bool:
    """Small (but not doji) body with meaningful wicks on both sides."""
    config = config or PriceActionConfig.from_settings()
    if i < 0 or i >= len(candles):
        return False
    c = candles[i]
    ratio = body_range_ratio(c)
    if ratio is None:
        return False
    if not (config.doji_body_ratio_max < ratio <= config.spinning_top_body_max):
        return False
    lower = lower_wick_ratio(c) or 0.0
    upper = upper_wick_ratio(c) or 0.0
    return lower >= config.spinning_top_wick_min and upper >= config.spinning_top_wick_min


def _tweezers_match(a: dict[str, Any], b: dict[str, Any], key: str, tolerance: float) -> bool:
    va, vb = _f(a, key), _f(b, key)
    if va <= 0:
        return False
    return abs(va - vb) / va <= tolerance


def tweezer_top(
    candles: list[dict[str, Any]], i: int, *, config: PriceActionConfig | None = None
) -> bool:
    """Bullish candle then bearish candle with matching highs (within tolerance)."""
    config = config or PriceActionConfig.from_settings()
    if i < 1:
        return False
    prev, cur = candles[i - 1], candles[i]
    return (
        is_bullish(prev)
        and is_bearish(cur)
        and _tweezers_match(prev, cur, "high", config.tweezer_tolerance)
    )


def tweezer_bottom(
    candles: list[dict[str, Any]], i: int, *, config: PriceActionConfig | None = None
) -> bool:
    """Bearish candle then bullish candle with matching lows (within tolerance)."""
    config = config or PriceActionConfig.from_settings()
    if i < 1:
        return False
    prev, cur = candles[i - 1], candles[i]
    return (
        is_bearish(prev)
        and is_bullish(cur)
        and _tweezers_match(prev, cur, "low", config.tweezer_tolerance)
    )


def detect_patterns(
    candles: list[dict[str, Any]],
    i: int,
    *,
    config: PriceActionConfig | None = None,
) -> list[Pattern]:
    """Return every pattern whose final candle is at index ``i``."""
    config = config or PriceActionConfig.from_settings()
    out: list[Pattern] = []
    checks: list[tuple[str, bool, str, int, str, str]] = [
        (
            "bullish_engulfing",
            bullish_engulfing(candles, i),
            PatternDirection.BULLISH,
            2,
            "needs a prior down-move or support context",
            "voided if price closes back below the engulfing candle open",
        ),
        (
            "bearish_engulfing",
            bearish_engulfing(candles, i),
            PatternDirection.BEARISH,
            2,
            "needs a prior up-move or resistance context",
            "voided if price closes back above the engulfing candle open",
        ),
        (
            "hammer",
            hammer(candles, i),
            PatternDirection.BULLISH,
            1,
            "meaningful at support or after a decline",
            "voided if the low is broken",
        ),
        (
            "shooting_star",
            shooting_star(candles, i),
            PatternDirection.BEARISH,
            1,
            "meaningful at resistance or after an advance",
            "voided if the high is broken",
        ),
        (
            "doji",
            doji(candles, i),
            PatternDirection.NEUTRAL,
            1,
            "indecision; needs trend/support context to interpret",
            "no directional invalidation",
        ),
        (
            "bullish_harami",
            bullish_harami(candles, i),
            PatternDirection.BULLISH,
            2,
            "needs a prior down-move",
            "voided if the harami low is broken",
        ),
        (
            "bearish_harami",
            bearish_harami(candles, i),
            PatternDirection.BEARISH,
            2,
            "needs a prior up-move",
            "voided if the harami high is broken",
        ),
        (
            "inside_bar",
            inside_bar(candles, i),
            PatternDirection.NEUTRAL,
            2,
            "a contraction; direction set by the breakout side",
            "voided when price exits the mother bar",
        ),
        (
            "outside_bar",
            outside_bar(candles, i),
            PatternDirection.NEUTRAL,
            2,
            "an expansion; direction set by the close",
            "voided when price re-enters the mother bar",
        ),
        (
            "piercing",
            piercing(candles, i),
            PatternDirection.BULLISH,
            2,
            "needs a prior down-move or support",
            "voided below the pattern low",
        ),
        (
            "dark_cloud_cover",
            dark_cloud_cover(candles, i),
            PatternDirection.BEARISH,
            2,
            "needs a prior up-move or resistance",
            "voided above the pattern high",
        ),
        (
            "morning_star",
            morning_star(candles, i, config),
            PatternDirection.BULLISH,
            3,
            "needs a prior down-move",
            "voided below the star low",
        ),
        (
            "evening_star",
            evening_star(candles, i, config),
            PatternDirection.BEARISH,
            3,
            "needs a prior up-move",
            "voided above the star high",
        ),
        (
            "three_white_soldiers",
            three_white_soldiers(candles, i, config),
            PatternDirection.BULLISH,
            3,
            "strongest after a base or support",
            "voided below the first soldier open",
        ),
        (
            "three_black_crows",
            three_black_crows(candles, i, config),
            PatternDirection.BEARISH,
            3,
            "strongest after a top or resistance",
            "voided above the first crow open",
        ),
        (
            "bullish_pin_bar",
            bullish_pin_bar(candles, i, config=config),
            PatternDirection.BULLISH,
            1,
            "meaningful at support or after a decline",
            "voided if the pin low is broken",
        ),
        (
            "bearish_pin_bar",
            bearish_pin_bar(candles, i, config=config),
            PatternDirection.BEARISH,
            1,
            "meaningful at resistance or after an advance",
            "voided if the pin high is broken",
        ),
        (
            "inverted_hammer",
            inverted_hammer(candles, i, lookback=config.swing_lookback + 1),
            PatternDirection.BULLISH,
            1,
            "requires a preceding decline; reversal candidate at support",
            "voided if the inverted-hammer high is broken downward",
        ),
        (
            "hanging_man",
            hanging_man(candles, i, lookback=config.swing_lookback + 1),
            PatternDirection.BEARISH,
            1,
            "requires a preceding advance; caution at resistance",
            "voided if the hanging-man high is broken",
        ),
        (
            "dragonfly_doji",
            dragonfly_doji(candles, i, config=config),
            PatternDirection.NEUTRAL,
            1,
            "indecision with lower-wick rejection; needs level context",
            "no directional invalidation",
        ),
        (
            "gravestone_doji",
            gravestone_doji(candles, i, config=config),
            PatternDirection.NEUTRAL,
            1,
            "indecision with upper-wick rejection; needs level context",
            "no directional invalidation",
        ),
        (
            "spinning_top",
            spinning_top(candles, i, config=config),
            PatternDirection.NEUTRAL,
            1,
            "indecision; needs trend context to interpret",
            "no directional invalidation",
        ),
        (
            "tweezer_top",
            tweezer_top(candles, i, config=config),
            PatternDirection.BEARISH,
            2,
            "needs a prior up-move or resistance",
            "voided above the tweezer high",
        ),
        (
            "tweezer_bottom",
            tweezer_bottom(candles, i, config=config),
            PatternDirection.BULLISH,
            2,
            "needs a prior down-move or support",
            "voided below the tweezer low",
        ),
    ]
    for name, matched, direction, count, context, invalidation in checks:
        if not matched:
            continue
        start = i - count + 1
        out.append(
            {
                "name": name,
                "direction": str(direction),
                "candle_count": count,
                "candle_refs": list(range(start, i + 1)),
                "context_requirement": context,
                "invalidation_condition": invalidation,
                "reasons": [f"{name} shape matched at index {i}"],
            }
        )
    return _suppress_alternative_names(out)


#: Alternative names for identical geometry: when the context-specific name
#: matches, the generic name for the same shape is dropped so one candle is
#: never reported under two contradictory names.
_ALT_NAME_PRIORITY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hanging_man", ("hammer",)),
    ("inverted_hammer", ("shooting_star",)),
    ("dragonfly_doji", ("doji",)),
    ("gravestone_doji", ("doji",)),
    ("spinning_top", ("doji",)),
)


def _suppress_alternative_names(found: list[Pattern]) -> list[Pattern]:
    present = {p["name"] for p in found}
    drop: set[str] = set()
    for winner, losers in _ALT_NAME_PRIORITY:
        if winner in present:
            drop.update(losers)
    return [p for p in found if p["name"] not in drop]


__all__ = [
    "bearish_engulfing",
    "bearish_harami",
    "bearish_pin_bar",
    "bullish_engulfing",
    "bullish_harami",
    "bullish_pin_bar",
    "dark_cloud_cover",
    "detect_patterns",
    "doji",
    "dragonfly_doji",
    "evening_star",
    "gravestone_doji",
    "hammer",
    "hanging_man",
    "inside_bar",
    "inverted_hammer",
    "morning_star",
    "outside_bar",
    "piercing",
    "shooting_star",
    "spinning_top",
    "three_black_crows",
    "three_white_soldiers",
    "tweezer_bottom",
    "tweezer_top",
]
