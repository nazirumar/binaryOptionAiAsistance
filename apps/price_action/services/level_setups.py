"""Support/resistance *setups* (Phase 12, CP3).

A touch of a level is never a complete setup. This module turns the raw zone
primitives of :mod:`apps.price_action.services.support_resistance` into named
*setups* — each with explicit requirements, missing evidence and an
invalidation — without predicting anything:

* **Flip lifecycle (SBR/RBS):** the full stage machine
  formation → valid break → retest → acceptance/rejection → completed or
  invalidated. A result reports the stage actually reached; stages never skip.
* **False breakout:** price pierced a zone boundary but closed back inside the
  origin side; confirmed only when follow-through agrees.
* **Failed zone test:** the level was attacked repeatedly without a completed
  close beyond it (the level defended itself).
* **Engulfing / doji at a level:** candle patterns whose location (at or beside
  a validated zone) gives them meaning, with the location requirement explicit.
"""

from __future__ import annotations

from typing import Any

from apps.price_action.constants import (
    SBRStage,
    ZoneKind,
)
from apps.price_action.services.candlestick_patterns import (
    bearish_engulfing,
    bullish_engulfing,
    doji,
)
from apps.price_action.services.config import PriceActionConfig
from apps.price_action.services.support_resistance import (
    Zone,
    detect_rejection,
    detect_zones,
)


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


def _zone_dict(zone: Zone) -> dict[str, Any]:
    return {
        "kind": str(zone.kind),
        "low": zone.low,
        "high": zone.high,
        "price": zone.price,
        "touches": zone.touches,
        "first_index": zone.first_index,
        "last_index": zone.last_index,
    }


def _beyond(zone: Zone, close: float, margin: float) -> bool:
    """A *completed close* strictly beyond the zone (either direction)."""
    if zone.kind == ZoneKind.RESISTANCE:
        return close > zone.high * (1 + margin)
    return close < zone.low * (1 - margin)


def _inside_origin(zone: Zone, close: float) -> bool:
    """Close is on the side price came from (support below / resistance above)."""
    if zone.kind == ZoneKind.RESISTANCE:
        return close < zone.high
    return close > zone.low


# ---------------------------------------------------------------------------
# Flip lifecycle (SBR / RBS and plain breakout-retest)
# ---------------------------------------------------------------------------


def track_zone_break(
    candles: list[dict[str, Any]],
    zone: Zone,
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any]:
    """Track the full stage machine of a break/retest/flip on one zone.

    Stages (never skipped): formation → valid break → retest → acceptance or
    rejection → completed or invalidated. ``stage`` is the furthest stage
    actually reached; ``history`` records each transition with its candle
    index. A result that stops before ``retest`` is explicitly *in progress*,
    never presented as a finished pattern.
    """
    config = config or PriceActionConfig.from_settings()
    margin = config.breakout_close_margin
    history: list[dict[str, Any]] = [
        {
            "stage": str(SBRStage.FORMATION),
            "index": zone.last_index,
            "note": f"validated {zone.kind} with {zone.touches} touches",
        }
    ]
    outcome: dict[str, Any] = {
        "type": (
            "support_became_resistance"
            if zone.kind == ZoneKind.SUPPORT
            else "resistance_became_support"
        ),
        "stage": str(SBRStage.FORMATION),
        "stage_reached": str(SBRStage.FORMATION),
        "break_index": None,
        "retest_index": None,
        "outcome_index": None,
        "completed_index": None,
        "invalidated_index": None,
        "in_progress": True,
        "history": history,
        "zone": _zone_dict(zone),
        "requirements": [
            "a completed close beyond the zone",
            "a retest from the opposite side",
            "acceptance or rejection at the retest",
        ],
        "missing": [],
    }

    # Stage 2: valid break — first completed close beyond the zone.
    break_index: int | None = None
    for i, c in enumerate(candles):
        if _beyond(zone, _f(c, "close"), margin):
            break_index = i
            break
    if break_index is None:
        outcome["missing"] = ["valid_break", "retest", "acceptance_or_rejection"]
        return outcome
    outcome["break_index"] = break_index
    outcome["stage"] = outcome["stage_reached"] = str(SBRStage.VALID_BREAK)
    history.append(
        {
            "stage": str(SBRStage.VALID_BREAK),
            "index": break_index,
            "note": "completed close beyond zone",
        }
    )

    # Stage 3: retest — price returns to the zone from the opposite side.
    retest_index: int | None = None
    window_start = break_index + 1
    window_end = min(len(candles), window_start + config.retest_window)
    for i in range(window_start, window_end):
        c = candles[i]
        if zone.contains(_f(c, "high")) or zone.contains(_f(c, "low")):
            retest_index = i
            break
    if retest_index is None:
        outcome["missing"] = ["retest", "acceptance_or_rejection"]
        return outcome
    outcome["retest_index"] = retest_index
    outcome["stage"] = outcome["stage_reached"] = str(SBRStage.RETEST)
    history.append(
        {"stage": str(SBRStage.RETEST), "index": retest_index, "note": "price returned to zone"}
    )

    # Stage 4: acceptance vs rejection at the retest candle.
    retest_candle = candles[retest_index]
    close = _f(retest_candle, "close")
    rejection = detect_rejection(candles[: retest_index + 1], zone, config=config)
    if rejection is not None or _inside_origin(zone, close):
        # The flip failed: price respected the *old* role and closed back on
        # the origin side → the setup is rejected.
        outcome["stage"] = outcome["stage_reached"] = str(SBRStage.REJECTION)
        outcome["outcome_index"] = retest_index
        outcome["outcome"] = "rejected"
        outcome["in_progress"] = False
        outcome["missing"] = []
        history.append(
            {
                "stage": str(SBRStage.REJECTION),
                "index": retest_index,
                "note": "retest rejected; old role still holding",
            }
        )
        return outcome
    if not _beyond(zone, close, 0.0):
        # Closed inside the zone: undecided.
        outcome["missing"] = ["acceptance_or_rejection"]
        history.append(
            {
                "stage": str(SBRStage.RETEST),
                "index": retest_index,
                "note": "retest candle closed inside the zone; outcome undecided",
            }
        )
        return outcome

    # Acceptance: retest candle closed beyond the zone again (new role holding).
    outcome["stage"] = outcome["stage_reached"] = str(SBRStage.ACCEPTANCE)
    outcome["outcome_index"] = retest_index
    outcome["outcome"] = "accepted"
    history.append(
        {
            "stage": str(SBRStage.ACCEPTANCE),
            "index": retest_index,
            "note": "close beyond zone after retest",
        }
    )

    # Stage 5: completed — follow-through close beyond the zone after acceptance.
    completed_index: int | None = None
    for i in range(retest_index + 1, len(candles)):
        if _beyond(zone, _f(candles[i], "close"), margin):
            completed_index = i
            break
    if completed_index is None:
        outcome["missing"] = ["follow_through"]
        return outcome
    outcome["completed_index"] = completed_index
    outcome["stage"] = outcome["stage_reached"] = str(SBRStage.COMPLETED)
    outcome["in_progress"] = False
    history.append(
        {
            "stage": str(SBRStage.COMPLETED),
            "index": completed_index,
            "note": "follow-through close beyond zone",
        }
    )

    # Invalidation can still occur later: two consecutive closes back through.
    streak = 0
    for i in range(completed_index + 1, len(candles)):
        close = _f(candles[i], "close")
        origin_side = (
            close > zone.high * (1 + margin)
            if zone.kind == ZoneKind.SUPPORT
            else close < zone.low * (1 - margin)
        )
        streak = streak + 1 if origin_side else 0
        if streak >= 2:
            outcome["invalidated_index"] = i
            outcome["stage"] = str(SBRStage.INVALIDATED)
            outcome["outcome"] = "invalidated"
            history.append(
                {
                    "stage": str(SBRStage.INVALIDATED),
                    "index": i,
                    "note": "two consecutive closes back through the zone",
                }
            )
            break
    return outcome


def sbr_rbs_lifecycle(
    candles: list[dict[str, Any]],
    zone: Zone,
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any]:
    """SBR/RBS: the flip lifecycle with all six stages tracked explicitly."""
    return track_zone_break(candles, zone, config=config)


# ---------------------------------------------------------------------------
# False breakout
# ---------------------------------------------------------------------------


def false_breakout(
    candles: list[dict[str, Any]],
    zone: Zone,
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """A candle pierced the zone boundary but closed back inside the origin side.

    ``confirmed`` is True only when a follow-through candle closed further
    against the break; without it the event stays a candidate.
    """
    config = config or PriceActionConfig.from_settings()
    if not candles:
        return None
    i = len(candles) - 1
    c = candles[i]
    close = _f(c, "close")
    if zone.kind == ZoneKind.RESISTANCE:
        pierced = _f(c, "high") > zone.high and close < zone.high
        direction = "bull_trap"
        follow_level = zone.low
    else:
        pierced = _f(c, "low") < zone.low and close > zone.low
        direction = "bear_trap"
        follow_level = zone.high
    if not pierced:
        return None
    # Follow-through: prior candle closed further against the break direction.
    confirmed = False
    if i >= 1:
        prev = candles[i - 1]
        confirmed = (
            _f(prev, "close") < follow_level
            if zone.kind == ZoneKind.RESISTANCE
            else _f(prev, "close") > follow_level
        )
    return {
        "type": "false_breakout",
        "subtype": direction,
        "index": i,
        "level": zone.price,
        "close": close,
        "confirmed": confirmed,
        "note": "pierced the zone but closed back inside; not a breakout",
        "requirements": ["follow-through candle against the break for confirmation"],
        "missing": [] if confirmed else ["follow_through"],
        "zone": _zone_dict(zone),
    }


# ---------------------------------------------------------------------------
# Failed zone test (the level defended itself)
# ---------------------------------------------------------------------------


def failed_zone_test(
    candles: list[dict[str, Any]],
    zone: Zone,
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """The zone was attacked at least ``failed_test_min_attempts`` times
    (wick penetration) without a single completed close beyond it."""
    config = config or PriceActionConfig.from_settings()
    attempts: list[int] = []
    for i, c in enumerate(candles):
        close = _f(c, "close")
        if _beyond(zone, close, config.breakout_close_margin):
            return None  # a valid break exists → not a "failed" test
        penetrated = zone.contains(_f(c, "high")) or zone.contains(_f(c, "low"))
        if penetrated:
            attempts.append(i)
    if len(attempts) < config.failed_test_min_attempts:
        return None
    return {
        "type": "failed_zone_test",
        "side": str(zone.kind),
        "attempt_indices": attempts,
        "attempt_count": len(attempts),
        "last_attempt_index": attempts[-1],
        "note": (
            f"{len(attempts)} attacks into the zone without a close beyond it; "
            "the level defended itself (an observation, not a guarantee)"
        ),
        "requirements": [],
        "missing": [],
        "zone": _zone_dict(zone),
    }


# ---------------------------------------------------------------------------
# Patterns at a level
# ---------------------------------------------------------------------------


def _at_or_near(zone: Zone, candle: dict[str, Any], config: PriceActionConfig) -> bool:
    """The candle's range reached within one zone-width of the zone edge."""
    width = max(zone.high - zone.low, zone.high * config.zone_tolerance)
    near = width * (1.0 + config.level_proximity)
    if zone.kind == ZoneKind.SUPPORT:
        return _f(candle, "low") <= zone.high + near
    return _f(candle, "high") >= zone.low - near


def engulfing_at_zone(
    candles: list[dict[str, Any]],
    zone: Zone,
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """An engulfing pattern on the *last* candle that also touched the zone.

    Direction must agree with the level: bullish engulfing at support, bearish
    engulfing at resistance. The location requirement is recorded explicitly —
    an engulfing away from any level is a different (weaker) observation.
    """
    config = config or PriceActionConfig.from_settings()
    if len(candles) < 2:
        return None
    i = len(candles) - 1
    last = candles[i]
    if not _at_or_near(zone, last, config):
        return None
    if zone.kind == ZoneKind.SUPPORT and bullish_engulfing(candles, i):
        return {
            "type": "engulfing_at_support",
            "direction": "bullish",
            "index": i,
            "candle_refs": [i - 1, i],
            "note": "bullish engulfing at a validated support zone",
            "requirements": ["prior down-move or fresh support context"],
            "invalidation": "voided if price closes back below the engulfing candle open",
            "zone": _zone_dict(zone),
        }
    if zone.kind == ZoneKind.RESISTANCE and bearish_engulfing(candles, i):
        return {
            "type": "engulfing_at_resistance",
            "direction": "bearish",
            "index": i,
            "candle_refs": [i - 1, i],
            "note": "bearish engulfing at a validated resistance zone",
            "requirements": ["prior up-move or fresh resistance context"],
            "invalidation": "voided if price closes back above the engulfing candle open",
            "zone": _zone_dict(zone),
        }
    return None


def doji_at_zone(
    candles: list[dict[str, Any]],
    zone: Zone,
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """A doji *above* a support or *below* a resistance zone.

    Indecision beside a validated level. Direction is always neutral: the
    doji names hesitation, not a turn.
    """
    config = config or PriceActionConfig.from_settings()
    if not candles:
        return None
    i = len(candles) - 1
    last = candles[i]
    if not doji(candles, i, config.doji_body_ratio_max):
        return None
    if zone.kind == ZoneKind.SUPPORT and _f(last, "low") >= zone.high:
        return {
            "type": "doji_above_support",
            "direction": "neutral",
            "index": i,
            "note": "doji hovering above support; indecision, needs a confirmed response",
            "requirements": ["confirmed rejection or break candle after the doji"],
            "zone": _zone_dict(zone),
        }
    if zone.kind == ZoneKind.RESISTANCE and _f(last, "high") <= zone.low:
        return {
            "type": "doji_below_resistance",
            "direction": "neutral",
            "index": i,
            "note": "doji under resistance; indecision, needs a confirmed response",
            "requirements": ["confirmed rejection or break candle after the doji"],
            "zone": _zone_dict(zone),
        }
    return None


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def detect_level_setups(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any]:
    """Run every level setup over the detected zones.

    Returns flip lifecycles, false-break candidates, defended-level reports and
    pattern-at-level observations. A zone *touch* alone never produces a setup
    beyond the plain zone record.
    """
    config = config or PriceActionConfig.from_settings()
    zones = detect_zones(candles, config=config)
    flips: list[dict[str, Any]] = []
    false_breaks: list[dict[str, Any]] = []
    defended: list[dict[str, Any]] = []
    at_level: list[dict[str, Any]] = []
    for zone in zones:
        flips.append(sbr_rbs_lifecycle(candles, zone, config=config))
        fb = false_breakout(candles, zone, config=config)
        if fb:
            false_breaks.append(fb)
        ft = failed_zone_test(candles, zone, config=config)
        if ft:
            defended.append(ft)
        for setup in (
            engulfing_at_zone(candles, zone, config=config),
            doji_at_zone(candles, zone, config=config),
        ):
            if setup:
                at_level.append(setup)
    return {
        "zones": [_zone_dict(z) for z in zones],
        "flips": flips,
        "false_breakouts": false_breaks,
        "failed_tests": defended,
        "patterns_at_level": at_level,
    }


__all__ = [
    "detect_level_setups",
    "doji_at_zone",
    "engulfing_at_zone",
    "failed_zone_test",
    "false_breakout",
    "sbr_rbs_lifecycle",
    "track_zone_break",
]
