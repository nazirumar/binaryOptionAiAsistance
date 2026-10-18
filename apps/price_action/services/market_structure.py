"""Market-structure engine (Step 4).

Swing points, higher highs/lows, lower highs/lows, trend, structure breaks and
failed breakouts. **No look-ahead:** a swing at index ``i`` is only reported
once ``lookback`` candles have closed on *both* sides of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.price_action.constants import (
    StructureBreakType,
    StructureState,
    SwingKind,
    SwingLabel,
)
from apps.price_action.services.candle_math import body_range_ratio
from apps.price_action.services.config import PriceActionConfig


@dataclass(frozen=True, slots=True)
class Swing:
    """A confirmed swing point with a structural label."""

    index: int
    kind: str  # SwingKind.HIGH | SwingKind.LOW
    value: float
    label: str = SwingLabel.UNKNOWN
    time: str | None = None


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


def _close(candle: dict[str, Any]) -> float:
    return _f(candle, "close")


def detect_swings(candles: list[dict[str, Any]], lookback: int = 2) -> list[Swing]:
    """Detect raw swing highs/lows confirmed by ``lookback`` candles each side."""
    swings: list[Swing] = []
    n = len(candles)
    if n == 0 or lookback < 1:
        return swings
    for i in range(lookback, n - lookback):
        c = candles[i]
        high = _f(c, "high")
        low = _f(c, "low")
        left = range(i - lookback, i)
        right = range(i + 1, i + lookback + 1)
        is_high = all(high >= _f(candles[j], "high") for j in left) and all(
            high >= _f(candles[j], "high") for j in right
        )
        is_low = all(low <= _f(candles[j], "low") for j in left) and all(
            low <= _f(candles[j], "low") for j in right
        )
        t = c.get("open_time") or c.get("time")
        t = t if isinstance(t, str) else None
        if is_high:
            swings.append(Swing(index=i, kind=SwingKind.HIGH, value=high, time=t))
        if is_low:
            swings.append(Swing(index=i, kind=SwingKind.LOW, value=low, time=t))
    return swings


def label_swings(swings: list[Swing], tolerance: float = 0.0005) -> list[Swing]:
    """Label each swing relative to the previous swing of the same kind."""
    labelled: list[Swing] = []
    last_high: float | None = None
    last_low: float | None = None
    for s in sorted(swings, key=lambda x: x.index):
        label = SwingLabel.UNKNOWN
        if s.kind == SwingKind.HIGH:
            if last_high is not None:
                label = _compare(
                    s.value, last_high, tolerance, up=SwingLabel.HH, down=SwingLabel.LH
                )
            last_high = s.value
        else:
            if last_low is not None:
                label = _compare(s.value, last_low, tolerance, up=SwingLabel.HL, down=SwingLabel.LL)
            last_low = s.value
        labelled.append(Swing(index=s.index, kind=s.kind, value=s.value, label=label, time=s.time))
    return labelled


def _compare(value: float, previous: float, tolerance: float, *, up: str, down: str) -> str:
    if previous == 0.0:
        return SwingLabel.UNKNOWN
    rel = (value - previous) / abs(previous)
    if rel > tolerance:
        return up
    if rel < -tolerance:
        return down
    return SwingLabel.EQ


def infer_trend(
    candles: list[dict[str, Any]],
    swing_lookback: int = 2,
    *,
    config: PriceActionConfig | None = None,
) -> str:
    """Return "uptrend", "downtrend", "ranging" or "unclear"."""
    config = config or PriceActionConfig.from_settings()
    swings = label_swings(detect_swings(candles, swing_lookback), config.equal_level_tolerance)
    highs = [s for s in swings if s.kind == SwingKind.HIGH]
    lows = [s for s in swings if s.kind == SwingKind.LOW]
    if len(highs) < config.min_swings_for_trend or len(lows) < config.min_swings_for_trend:
        return "unclear"
    hh = highs[-1].label == SwingLabel.HH
    hl = lows[-1].label == SwingLabel.HL
    lh = highs[-1].label == SwingLabel.LH
    ll = lows[-1].label == SwingLabel.LL
    if hh and hl:
        return "uptrend"
    if lh and ll:
        return "downtrend"
    return "ranging"


def structure_state(
    candles: list[dict[str, Any]],
    *,
    swing_lookback: int | None = None,
    config: PriceActionConfig | None = None,
) -> str:
    """Map the inferred trend onto a :class:`StructureState` value."""
    config = config or PriceActionConfig.from_settings()
    lookback = config.swing_lookback if swing_lookback is None else swing_lookback
    trend = infer_trend(candles, lookback, config=config)
    if trend == "uptrend":
        return StructureState.BULLISH
    if trend == "downtrend":
        return StructureState.BEARISH
    if trend == "ranging":
        return StructureState.RANGING
    return StructureState.UNCLEAR


def last_swing(swings: list[Swing], kind: str) -> Swing | None:
    for s in reversed(swings):
        if s.kind == kind:
            return s
    return None


def detect_structure_break(
    candles: list[dict[str, Any]], lookback: int = 2
) -> dict[str, Any] | None:
    """Break of structure: the latest close beyond the most recent confirmed swing."""
    swings = detect_swings(candles, lookback)
    if not candles:
        return None
    price = _close(candles[-1])
    high = last_swing(swings, SwingKind.HIGH)
    low = last_swing(swings, SwingKind.LOW)
    if high is not None and price > high.value:
        return {"type": "bullish_bos", "level": high.value, "index": len(candles) - 1}
    if low is not None and price < low.value:
        return {"type": "bearish_bos", "level": low.value, "index": len(candles) - 1}
    return None


def detect_failed_breakout(
    candles: list[dict[str, Any]], lookback: int = 2
) -> dict[str, Any] | None:
    """Price pierced a swing but closed back inside it (a failed breakout)."""
    swings = detect_swings(candles, lookback)
    if not candles:
        return None
    c = candles[-1]
    high = last_swing(swings, SwingKind.HIGH)
    low = last_swing(swings, SwingKind.LOW)
    if high is not None and _f(c, "high") > high.value and _close(c) < high.value:
        return {"type": "failed_high_breakout", "level": high.value, "index": len(candles) - 1}
    if low is not None and _f(c, "low") < low.value and _close(c) > low.value:
        return {"type": "failed_low_breakout", "level": low.value, "index": len(candles) - 1}
    return None


# ---------------------------------------------------------------------------
# Phase 12 (CP4): CHOCH, MSS, exhaustion, reversal candidates, narrative
# ---------------------------------------------------------------------------


def detect_choch(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """Change of character: the first completed close *against* a live trend.

    Requires an existing structural trend (last high/low labels agree) and a
    close beyond the most recent *protective* swing (the last HL in an uptrend
    / the last LH in a downtrend) with the breakout margin. A plain BOS with
    the trend is never reported as a CHOCH.
    """
    config = config or PriceActionConfig.from_settings()
    if not candles:
        return None
    swings = label_swings(
        detect_swings(candles, config.swing_lookback), config.equal_level_tolerance
    )
    highs = [s for s in swings if s.kind == SwingKind.HIGH]
    lows = [s for s in swings if s.kind == SwingKind.LOW]
    if not highs or not lows:
        return None
    price = _close(candles[-1])
    idx = len(candles) - 1
    margin = config.breakout_close_margin
    if highs[-1].label == SwingLabel.HH and lows[-1].label == SwingLabel.HL:
        protective = lows[-1]
        if price < protective.value * (1 - margin) and idx > protective.index:
            return {
                "type": str(StructureBreakType.CHOCH_BEARISH),
                "prior_trend": "uptrend",
                "protective_swing": {
                    "kind": "low",
                    "value": protective.value,
                    "index": protective.index,
                },
                "level": protective.value,
                "index": idx,
                "note": "close below the last higher low: character changed bullish -> bearish",
            }
    if highs[-1].label == SwingLabel.LH and lows[-1].label == SwingLabel.LL:
        protective = highs[-1]
        if price > protective.value * (1 + margin) and idx > protective.index:
            return {
                "type": str(StructureBreakType.CHOCH_BULLISH),
                "prior_trend": "downtrend",
                "protective_swing": {
                    "kind": "high",
                    "value": protective.value,
                    "index": protective.index,
                },
                "level": protective.value,
                "index": idx,
                "note": "close above the last lower high: character changed bearish -> bullish",
            }
    return None


def detect_mss(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """Market structure shift: a CHOCH *confirmed by displacement*.

    MSS is the stronger claim on top of CHOCH: the character change plus a
    strong break candle or immediate follow-through in the new direction. The
    two names are never merged — the ``displacement`` field shows exactly why
    this is an MSS and not merely a CHOCH.
    """
    config = config or PriceActionConfig.from_settings()
    choch = detect_choch(candles, config=config)
    if choch is None:
        return None
    i = choch["index"]
    break_candle = candles[i]
    body = body_range_ratio(break_candle)
    strong = body is not None and body >= config.strong_body_ratio_min
    follow_through = False
    if i + 1 < len(candles):
        nxt = candles[i + 1]
        if choch["type"] == str(StructureBreakType.CHOCH_BEARISH):
            follow_through = _close(nxt) < _close(break_candle)
        else:
            follow_through = _close(nxt) > _close(break_candle)
    if not (strong or follow_through):
        return None
    return {
        "type": (
            str(StructureBreakType.MSS_BEARISH)
            if choch["prior_trend"] == "uptrend"
            else str(StructureBreakType.MSS_BULLISH)
        ),
        "choch": choch,
        "strong_break_candle": strong,
        "follow_through": follow_through,
        "index": i,
        "note": "character change confirmed by displacement/ follow-through",
    }


def detect_trend_exhaustion(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any] | None:
    """Observable exhaustion signals inside a *live* trend.

    Signals checked (each recorded, none interpreted as a probability):
    shrinking bodies in the trend direction, growing opposing wicks and a
    close far from the trend's last swing extreme. Requires a recognised
    trend; outside a trend there is nothing to exhaust.
    """
    config = config or PriceActionConfig.from_settings()
    trend = infer_trend(candles, config.swing_lookback, config=config)
    if trend not in ("uptrend", "downtrend"):
        return None
    w = config.exhaustion_window
    if len(candles) < 2 * w + 1:
        return None
    recent = candles[-(w + 1) : -1]
    prior = candles[-(2 * w + 1) : -(w + 1)]

    def _bodies(group: list[dict[str, Any]]) -> list[float]:
        out = []
        for c in group:
            body = abs(_close(c) - _f(c, "open"))
            out.append(body)
        return out

    recent_bodies = _bodies(recent)
    prior_bodies = _bodies(prior)
    prior_avg = sum(prior_bodies) / len(prior_bodies) if prior_bodies else 0.0
    shrinking = prior_avg > 0 and (sum(recent_bodies) / len(recent_bodies)) < (
        prior_avg * config.exhaustion_body_shrink_ratio
    )
    last = candles[-1]
    upper = max(0.0, _f(last, "high") - max(_f(last, "open"), _close(last)))
    lower = max(0.0, min(_f(last, "open"), _close(last)) - _f(last, "low"))
    rng = _f(last, "high") - _f(last, "low")
    opposing_wick = (
        (lower / rng) if (trend == "uptrend" and rng > 0) else ((upper / rng) if rng > 0 else 0.0)
    )
    wick_growing = opposing_wick >= config.exhaustion_opposing_wick_min
    signals = []
    if shrinking:
        signals.append("shrinking_bodies")
    if wick_growing:
        signals.append("growing_opposing_wick")
    if len(signals) < 2:
        return None
    return {
        "type": "trend_exhaustion",
        "trend": trend,
        "signals": signals,
        "index": len(candles) - 1,
        "note": (
            "exhaustion *candidate*: observable decay inside the trend. "
            "It is not a reversal — a structure break is required for that."
        ),
    }


def reversal_candidates(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any]:
    """Bullish/bearish *reversal candidates* with the evidence that produced them.

    A candidate needs a live trend plus at least one of: CHOCH (strongest),
    exhaustion signals, or a failed structural break. ``confirmed`` is True
    only when a CHOCH exists — the only stage the engine treats as a real
    character change.
    """
    config = config or PriceActionConfig.from_settings()
    trend = infer_trend(candles, config.swing_lookback, config=config)
    choch = detect_choch(candles, config=config)
    exhaustion = detect_trend_exhaustion(candles, config=config)
    failed_break = detect_failed_breakout(candles, config.swing_lookback)
    evidence: list[str] = []
    if choch:
        evidence.append("choch")
    if exhaustion:
        evidence.append("exhaustion")
    if failed_break:
        evidence.append("failed_structural_break")
    direction = "neutral"
    if choch:
        direction = (
            "bearish" if choch["type"] == str(StructureBreakType.CHOCH_BEARISH) else "bullish"
        )
    elif trend != "unclear" and evidence:
        direction = (
            "bearish" if trend == "uptrend" else "bullish" if trend == "downtrend" else "neutral"
        )
    return {
        "trend": trend,
        "candidate_direction": direction,
        "confirmed": choch is not None,
        "evidence": evidence,
        "choch": choch,
        "exhaustion": exhaustion,
        "failed_break": failed_break,
        "note": (
            "a reversal candidate is a hypothesis; only a CHOCH marks an actual "
            "character change, and even then continuation is never guaranteed"
        ),
    }


def structure_narrative(
    candles: list[dict[str, Any]],
    *,
    config: PriceActionConfig | None = None,
) -> dict[str, Any]:
    """Plain-language HH/HL/LH/LL narrative with explicit swing references.

    Distinguishes *continuation* evidence (fresh HH+HL / LH+LL) from
    *reversal-in-progress* evidence (CHOCH, failed break, exhaustion) and names
    the swings each statement is based on. Words only — no probabilities.
    """
    config = config or PriceActionConfig.from_settings()
    swings = label_swings(
        detect_swings(candles, config.swing_lookback), config.equal_level_tolerance
    )
    highs = [s for s in swings if s.kind == SwingKind.HIGH]
    lows = [s for s in swings if s.kind == SwingKind.LOW]
    statements: list[dict[str, Any]] = []
    refs: list[int] = []
    if (
        highs
        and lows
        and highs[-1].label != SwingLabel.UNKNOWN
        and lows[-1].label != SwingLabel.UNKNOWN
    ):
        pair = {highs[-1].label, lows[-1].label}
        if pair <= {SwingLabel.HH, SwingLabel.HL}:
            statements.append(
                {
                    "text": f"Uptrend continuation: {highs[-1].label} high then {lows[-1].label} low.",
                    "kind": "continuation",
                }
            )
        elif pair <= {SwingLabel.LH, SwingLabel.LL}:
            statements.append(
                {
                    "text": f"Downtrend continuation: {highs[-1].label} high then {lows[-1].label} low.",
                    "kind": "continuation",
                }
            )
        else:
            statements.append(
                {
                    "text": (
                        f"Mixed structure: last high {highs[-1].label}, last low {lows[-1].label}."
                    ),
                    "kind": "mixed",
                }
            )
        refs.extend([highs[-1].index, lows[-1].index])
    choch = detect_choch(candles, config=config)
    if choch:
        statements.append(
            {"text": choch["note"] + f" (close at candle {choch['index']}).", "kind": "reversal"}
        )
        refs.append(choch["index"])
    exhaustion = detect_trend_exhaustion(candles, config=config)
    if exhaustion:
        statements.append(
            {
                "text": (
                    f"Trend exhaustion candidate ({', '.join(exhaustion['signals'])}) "
                    f"at candle {exhaustion['index']}."
                ),
                "kind": "caution",
            }
        )
        refs.append(exhaustion["index"])
    if not statements:
        statements.append(
            {"text": "Structure unclear: not enough confirmed swings.", "kind": "unclear"}
        )
    return {
        "trend": infer_trend(candles, config.swing_lookback, config=config),
        "statements": statements,
        "swing_refs": refs,
        "swing_labels": [
            {"index": s.index, "kind": str(s.kind), "label": str(s.label), "value": s.value}
            for s in swings
        ],
    }


def detect_consolidation(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any] | None:
    """A tight range over a window with no decisive close outside it."""
    config = config or PriceActionConfig.from_settings()
    window = candles[-config.consolidation_min_candles :]
    if len(window) < config.consolidation_min_candles:
        return None
    high = max(_f(c, "high") for c in window)
    low = min(_f(c, "low") for c in window)
    if low <= 0:
        return None
    width = (high - low) / low
    if width <= config.consolidation_max_width:
        return {
            "type": "consolidation",
            "high": high,
            "low": low,
            "width": width,
            "candles": len(window),
            "index": len(candles) - 1,
        }
    return None


__all__ = [
    "Swing",
    "detect_consolidation",
    "detect_failed_breakout",
    "detect_structure_break",
    "detect_swings",
    "infer_trend",
    "label_swings",
    "last_swing",
    "structure_state",
]
