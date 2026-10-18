"""ICT-style concepts (Phase 12, CP5) — observable definitions only.

Every function here describes *what price did*, never *why*. "Inducement",
"breaker" and "premium/discount" are names for observable geometric events;
none of them imply institutional intent. Where the course definitions are
ambiguous, the ambiguity is recorded on the result.

Built on the existing sweep / FVG / order-block engines — no detector is
duplicated here.
"""

from __future__ import annotations

from typing import Any

from apps.price_action.constants import (
    FVGState,
    OBType,
    PriceZone,
    SwingKind,
    SwingLabel,
)
from apps.price_action.services.candle_math import average_range, body_range_ratio
from apps.price_action.services.config import PriceActionConfig
from apps.price_action.services.fair_value_gaps import classify_fvg_state, detect_fvg
from apps.price_action.services.market_structure import (
    Swing,
    detect_swings,
    label_swings,
)
from apps.price_action.services.order_blocks import detect_order_blocks

#: Documented ambiguities of the course's ICT vocabulary.
ICT_AMBIGUITIES = (
    "The course does not define a minimum separation between 'equal' highs/lows; "
    "the tolerance used is reported on every result.",
    "'Inducement' is defined here as the first minor liquidity pool price takes "
    "before the real level — other readings exist and are not merged.",
    "'Breaker' follows the invalidated-order-block reading; the teacher-pattern "
    "reading differs and is never silently substituted.",
)


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


# ---------------------------------------------------------------------------
# Equal highs / equal lows
# ---------------------------------------------------------------------------


def equal_levels(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> list[dict[str, Any]]:
    """Consecutive labelled EQ swings (equal highs / equal lows).

    Uses the engine's swing labeller, so "equal" means: within
    ``config.equal_level_tolerance`` relative distance of the previous swing of
    the same kind. The tolerance is always reported.
    """
    config = config or PriceActionConfig.from_settings()
    swings = label_swings(
        detect_swings(candles, config.swing_lookback), config.equal_level_tolerance
    )
    out: list[dict[str, Any]] = []
    previous: Swing | None = None
    for s in swings:
        if previous is not None and previous.kind == s.kind and s.label == SwingLabel.EQ:
            out.append(
                {
                    "type": "equal_highs" if s.kind == SwingKind.HIGH else "equal_lows",
                    "first_index": previous.index,
                    "second_index": s.index,
                    "level": (previous.value + s.value) / 2.0,
                    "tolerance_used": config.equal_level_tolerance,
                    "note": "an observable liquidity pool; a sweep of it is a separate event",
                }
            )
        previous = s
    return out


# ---------------------------------------------------------------------------
# Swing sweeps (prev-extreme sweeps live in liquidity_sweeps)
# ---------------------------------------------------------------------------


def sweep_of_swing(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> list[dict[str, Any]]:
    """The last candle swept a *confirmed swing* high/low and closed back inside.

    Distinct from the previous-candle sweep in :mod:`liquidity_sweeps`: the
    level here is a confirmed swing point, so the liquidity reference is
    structural rather than recent-range.
    """
    config = config or PriceActionConfig.from_settings()
    if not candles:
        return []
    swings = detect_swings(candles, config.swing_lookback)
    if not swings:
        return []
    idx = len(candles) - 1
    last = candles[idx]
    close = _f(last, "close")
    out: list[dict[str, Any]] = []
    for s in swings:
        if s.index >= idx:
            continue
        if s.kind == SwingKind.HIGH and _f(last, "high") > s.value and close <= s.value:
            out.append(
                {
                    "type": "swing_high_sweep",
                    "index": idx,
                    "swing_index": s.index,
                    "level": s.value,
                    "closed_back_inside": True,
                }
            )
        if s.kind == SwingKind.LOW and _f(last, "low") < s.value and close >= s.value:
            out.append(
                {
                    "type": "swing_low_sweep",
                    "index": idx,
                    "swing_index": s.index,
                    "level": s.value,
                    "closed_back_inside": True,
                }
            )
    return out


# ---------------------------------------------------------------------------
# Inducement
# ---------------------------------------------------------------------------


def inducement(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """The most recent *swept minor swing* before the current extreme.

    Observable reading: in an up-move, the last swept swing low before the
    highest recent high is the candidate inducement (the liquidity that was
    taken before the leg continued). Reported only when such a sweep actually
    exists — never assumed. Ambiguity is copied onto the result.
    """
    config = config or PriceActionConfig.from_settings()
    sweeps = sweep_of_swing(candles, config=config)
    if not sweeps:
        return None
    last = sweeps[-1]
    high_index = max(range(len(candles)), key=lambda i: _f(candles[i], "high"))
    low_index = min(range(len(candles)), key=lambda i: _f(candles[i], "low"))
    if last["type"] == "swing_low_sweep" and last["index"] <= high_index:
        side = "bullish"
    elif last["type"] == "swing_high_sweep" and last["index"] <= low_index:
        side = "bearish"
    else:
        return None
    return {
        "type": "inducement",
        "side": side,
        "level": last["level"],
        "sweep_index": last["index"],
        "swing_index": last["swing_index"],
        "ambiguities": list(ICT_AMBIGUITIES[1:2]),
        "note": "candidate inducement: the minor liquidity taken before the leg",
    }


# ---------------------------------------------------------------------------
# Displacement
# ---------------------------------------------------------------------------


def displacement(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> list[dict[str, Any]]:
    """Strong impulsive candles (wide range + strong body) that left an FVG.

    Displacement is the observable: a departure candle whose range exceeds
    ``strong_range_multiple`` of the recent average *and* whose body ratio
    reaches ``strong_body_ratio_min``, with a matching three-candle gap.
    """
    config = config or PriceActionConfig.from_settings()
    avg = average_range(candles, config.volume_lookback)
    if not avg:
        return []
    gaps = detect_fvg(candles, config=config)
    gap_departures = {g["middle_index"] for g in gaps}
    out: list[dict[str, Any]] = []
    for i, c in enumerate(candles):
        rng = _f(c, "high") - _f(c, "low")
        body = body_range_ratio(c)
        if body is None or body < config.strong_body_ratio_min:
            continue
        if rng < config.strong_range_multiple * avg:
            continue
        if (i - 1) not in gap_departures and i not in gap_departures:
            continue
        out.append(
            {
                "type": "displacement",
                "index": i,
                "direction": "bullish" if _f(c, "close") > _f(c, "open") else "bearish",
                "range_multiple": rng / avg if avg else None,
                "body_ratio": body,
                "note": "wide strong-bodied candle coinciding with an imbalance",
            }
        )
    return out


# ---------------------------------------------------------------------------
# FVG retest
# ---------------------------------------------------------------------------


def fvg_retest(
    candles: list[dict[str, Any]],
    gap: dict[str, Any],
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """First retest of an FVG inside ``retest_window`` candles after formation.

    Only *open* or *mitigated-once* gaps make sense here; a retest of an
    invalidated gap is reported as an invalidated-gap touch, not a retest.
    """
    config = config or PriceActionConfig.from_settings()
    bottom = gap["bottom"]
    top = gap["top"]
    start = gap["index"] + 1
    end = min(len(candles), start + config.retest_window)
    for i in range(start, end):
        c = candles[i]
        if _f(c, "low") <= top and _f(c, "high") >= bottom:
            state = str(classify_fvg_state(candles[: i + 1], gap))
            return {
                "type": "fvg_retest",
                "fvg_type": gap["type"],
                "formation_index": gap["index"],
                "retest_index": i,
                "top": top,
                "bottom": bottom,
                "state_at_retest": state,
                "invalid_gap": state == str(FVGState.INVALIDATED),
                "note": "price returned to the imbalance; state at retest is reported",
            }
    return None


# ---------------------------------------------------------------------------
# Breaker block & mitigation
# ---------------------------------------------------------------------------


def breaker_blocks(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> list[dict[str, Any]]:
    """Order blocks that price *closed through* and then retested from afar.

    Reading used: an invalidated order block that price trades back into is a
    candidate "breaker" (role reversal of the block). The block boundaries and
    the invalidation are reported — the role-reversal interpretation is labelled
    as the ICT-style reading, matching ``OBDefinition.ICT_STYLE``.
    """
    config = config or PriceActionConfig.from_settings()
    zones = detect_order_blocks(candles, config=config)
    out: list[dict[str, Any]] = []
    for zone in zones:
        if zone.get("rejected"):
            continue
        top = zone["top"]
        bottom = zone["bottom"]
        start = zone.get("departure_index", zone["index"]) + 1
        invalidated_at: int | None = None
        retest_after: int | None = None
        for i in range(start, len(candles)):
            c = candles[i]
            if invalidated_at is None:
                if zone["type"] == str(OBType.BULLISH) and _f(c, "close") < bottom:
                    invalidated_at = i
                elif zone["type"] == str(OBType.BEARISH) and _f(c, "close") > top:
                    invalidated_at = i
                continue
            if _f(c, "low") <= top and _f(c, "high") >= bottom:
                retest_after = i
                break
        if invalidated_at is None or retest_after is None:
            continue
        out.append(
            {
                "type": "breaker_block",
                "block_type": str(zone["type"]),
                "index": zone["index"],
                "top": top,
                "bottom": bottom,
                "invalidated_index": invalidated_at,
                "retest_index": retest_after,
                "note": (
                    "invalidated order block traded back into (ICT-style breaker "
                    "reading; the teacher-pattern reading differs)"
                ),
                "ambiguities": [ICT_AMBIGUITIES[2]],
            }
        )
    return out


def mitigation_report(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any]:
    """Mitigation status of every FVG and order block in one pass."""
    config = config or PriceActionConfig.from_settings()
    gaps = detect_fvg(candles, config=config)
    annotated = [{**g, "state": str(classify_fvg_state(candles, g))} for g in gaps]
    zones = detect_order_blocks(candles, config=config)
    open_blocks: list[dict[str, Any]] = []
    mitigated: list[dict[str, Any]] = []
    for zone in zones:
        if zone.get("rejected"):
            continue
        top = zone["top"]
        bottom = zone["bottom"]
        start = zone.get("departure_index", zone["index"]) + 1
        touched = any(_f(c, "low") <= top and _f(c, "high") >= bottom for c in candles[start:])
        (mitigated if touched else open_blocks).append(
            {"index": zone["index"], "type": zone["type"], "top": top, "bottom": bottom}
        )
    return {
        "fvgs": annotated,
        "order_blocks": {"mitigated": mitigated, "open": open_blocks},
        "note": "mitigation = traded back into; nothing here implies intent",
    }


# ---------------------------------------------------------------------------
# Premium / discount
# ---------------------------------------------------------------------------


def premium_discount(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """Classify the latest close inside the recent dealing range.

    Range = highest high / lowest low over ``volume_lookback`` candles. The
    midpoint is equilibrium. Classification is geometric — "premium" is not a
    claim that price will fall.
    """
    config = config or PriceActionConfig.from_settings()
    window = candles[-config.volume_lookback :]
    if len(window) < 2:
        return None
    top = max(_f(c, "high") for c in window)
    bottom = min(_f(c, "low") for c in window)
    if top <= bottom:
        return None
    close = _f(candles[-1], "close")
    midpoint = (top + bottom) / 2.0
    rel_tolerance = config.equal_level_tolerance
    if abs(close - midpoint) / midpoint <= rel_tolerance:
        zone = PriceZone.EQUILIBRIUM
    elif close > midpoint:
        zone = PriceZone.PREMIUM
    else:
        zone = PriceZone.DISCOUNT
    return {
        "type": "premium_discount",
        "zone": str(zone),
        "range_top": top,
        "range_bottom": bottom,
        "midpoint": midpoint,
        "close": close,
        "window": len(window),
        "note": "geometric classification of price inside the dealing range",
    }


__all__ = [
    "ICT_AMBIGUITIES",
    "breaker_blocks",
    "displacement",
    "equal_levels",
    "fvg_retest",
    "inducement",
    "mitigation_report",
    "premium_discount",
    "sweep_of_swing",
]
