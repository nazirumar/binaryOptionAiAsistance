# book_strategies/services/detectors.py
"""Deterministic detectors for the priority Binary Options Trading Bible patterns.

Each detector is a pure function over closed OHLC candle dicts that returns an
explicit lifecycle state:

- ``FORMING``               - the book sequence is not present yet (progress is
                              stated precisely in ``observed_evidence``).
- ``AWAITING_CONFIRMATION`` - the seed sequence and reference level exist but a
                              required condition (breakout, stochastic, trend)
                              is not yet satisfied.
- ``CONFIRMED_PATTERN``     - every deterministic book condition is satisfied.
                              This is NOT a trade prediction: the decision
                              remains NO TRADE and probability stays None.
- ``INVALIDATED``           - one of the book's own invalidation rules fired.
- ``INSUFFICIENT_DATA``     - too few closed candles to evaluate the setup.

Implementation choices that the book leaves undefined (doji thresholds, wick
vs body breaks, trend classification) are explicit here and listed as
ambiguities on the result - never silently absorbed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from apps.price_action.services.indicators import (
    ema,
    parabolic_sar,
    stochastic_supported,
)
from apps.price_action.services.market_structure import infer_trend

#: The seed sequence must have formed within this many candles of the series
#: end; older setups are not re-armed (keeps replay signals fresh).
MAX_SEED_GAP = 10
#: Implementation choice: the book never defines "doji" numerically. A doji's
#: body must be at most this fraction of its range.
DOJI_BODY_RATIO = 0.10
#: Implementation choice: "strong candle" for Chapter 7 Strategy 1 - body at
#: least this multiple of the median absolute body of the previous 10 candles.
STRONG_BODY_MEDIAN_FACTOR = 1.0


@dataclass
class BookPatternResult:
    """Outcome of one detector evaluation."""

    strategy_key: str
    state: str
    direction: str = "neutral"
    candle_refs: list[int] = field(default_factory=list)
    observed_evidence: list[str] = field(default_factory=list)
    missing_conditions: list[str] = field(default_factory=list)
    invalidations: list[str] = field(default_factory=list)
    reference_level: float | None = None
    level_kind: str = ""
    stochastic_supported: bool | None = None
    #: Index at which the pattern fully completed (None unless confirmed).
    completed_at: int | None = None
    ambiguities: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------
def _o(c: dict[str, Any]) -> float:
    return float(c["open"])


def _h(c: dict[str, Any]) -> float:
    return float(c["high"])


def _l(c: dict[str, Any]) -> float:
    return float(c["low"])


def _c(c: dict[str, Any]) -> float:
    return float(c["close"])


def _body(c: dict[str, Any]) -> float:
    return abs(_c(c) - _o(c))


def _range(c: dict[str, Any]) -> float:
    return _h(c) - _l(c)


def _color(c: dict[str, Any]) -> str:
    if _c(c) > _o(c):
        return "green"
    if _c(c) < _o(c):
        return "red"
    return "neutral"


def _is_doji(c: dict[str, Any]) -> bool:
    rng = _range(c)
    return rng > 0 and _body(c) <= DOJI_BODY_RATIO * rng


def _trailing_run(candles: list[dict[str, Any]], end: int) -> tuple[int, str, int]:
    """Longest same-colour run ending at ``end`` -> (start, colour, length).

    Neutral candles AND dojis terminate runs: the book's sequences say
    "back-to-back same colour candles" and a doji is a separate element (its
    own step in SS12/SS13/SS19/SS20), never part of a colour run.
    """
    if _is_doji(candles[end]):
        return end, "neutral", 0
    colour = _color(candles[end])
    if colour == "neutral":
        return end, "neutral", 0
    start = end
    while start - 1 >= 0 and not _is_doji(candles[start - 1]) and (
        _color(candles[start - 1]) == colour
    ):
        start -= 1
    return start, colour, end - start + 1


def _trend_gate(
    candles: list[dict[str, Any]], upto: int, allowed: tuple[str, ...]
) -> tuple[bool | None, str]:
    """Book market-condition precondition. Returns (ok, note)."""
    window = candles[: upto + 1]
    if len(window) < 8:
        return None, "market regime could not be determined (too few candles)"
    trend = infer_trend(window)
    if trend == "unclear":
        return None, "market regime could not be determined from the candles"
    if "trending" in allowed and "ranging" in allowed:
        return True, f"market type acceptable for this pattern (inferred: {trend})"
    if "trending" in allowed:
        if trend in ("uptrend", "downtrend"):
            return True, f"market inferred {trend}"
        return False, f"book requires a trending market but the candles infer {trend}"
    return True, f"market type acceptable (inferred: {trend})"


def _stoch_gate(
    candles: list[dict[str, Any]], index: int, direction: str
) -> tuple[bool | None, str]:
    supported = stochastic_supported(candles, index, direction=direction)
    if supported is None:
        return None, (
            "stochastic confirmation unavailable (needs at least 17 closed "
            "candles of this feed)"
        )
    if supported:
        return True, "stochastic supports the direction (%K vs %D as the book requires)"
    line = "green above red" if direction == "bullish" else "red above green"
    return False, f"stochastic does not support the direction (book requires {line})"


def _first_break_up(
    candles: list[dict[str, Any]], start: int, level: float
) -> int | None:
    """First candle from ``start`` whose CLOSE is above ``level``."""
    for i in range(start, len(candles)):
        if _c(candles[i]) > level:
            return i
    return None


def _first_break_down(
    candles: list[dict[str, Any]], start: int, level: float
) -> int | None:
    for i in range(start, len(candles)):
        if _c(candles[i]) < level:
            return i
    return None


def _finish(
    key: str,
    candles: list[dict[str, Any]],
    confirmed: bool,
    *,
    direction: str,
    refs: list[int],
    evidence: list[str],
    missing: list[str],
    level: float | None,
    level_kind: str,
    trend_ok: bool | None,
    trend_note: str,
    stoch_ok: bool | None,
    stoch_note: str,
    completed_at: int | None,
    invalidations: list[str] | None = None,
    last_forming: bool = False,
    extra_ambiguities: list[str] | None = None,
) -> BookPatternResult:
    """Assemble the final state from the gates, honouring every cap."""
    result = BookPatternResult(
        strategy_key=key,
        state="CONFIRMED_PATTERN" if confirmed else "AWAITING_CONFIRMATION",
        direction=direction if confirmed else "neutral",
        candle_refs=refs,
        observed_evidence=list(evidence),
        missing_conditions=list(missing),
        invalidations=list(invalidations or []),
        reference_level=level,
        level_kind=level_kind,
        stochastic_supported=stoch_ok,
        completed_at=completed_at if confirmed else None,
        ambiguities=list(extra_ambiguities or []),
    )
    if confirmed:
        if trend_ok is not True:
            result.state = "AWAITING_CONFIRMATION"
            result.direction = "neutral"
            result.completed_at = None
            result.missing_conditions.append(trend_note)
        if stoch_ok is not True:
            result.state = "AWAITING_CONFIRMATION"
            result.direction = "neutral"
            result.completed_at = None
            result.missing_conditions.append(stoch_note)
    if last_forming and result.state == "CONFIRMED_PATTERN":
        if completed_at is not None and completed_at == len(candles) - 1:
            # The completion candle IS the still-forming one: its close is
            # provisional, so the setup is not confirmed yet.
            result.state = "AWAITING_CONFIRMATION"
            result.direction = "neutral"
            result.completed_at = None
            result.missing_conditions.append(
                "the completion candle is still forming; its close is "
                "provisional and the pattern cannot be confirmed yet"
            )
        else:
            result.observed_evidence.append(
                "the last candle is still forming on the chart; the completed "
                "state refers to the last CLOSED candle"
            )
    return result


def _forming(key: str, evidence: list[str], refs: list[int] | None = None) -> BookPatternResult:
    return BookPatternResult(
        strategy_key=key,
        state="FORMING",
        observed_evidence=evidence,
        candle_refs=list(refs or []),
    )


def _insufficient(key: str, evidence: list[str]) -> BookPatternResult:
    return BookPatternResult(
        strategy_key=key, state="INSUFFICIENT_DATA", observed_evidence=evidence
    )


def _invalidated(
    key: str, evidence: list[str], invalidations: list[str], refs: list[int]
) -> BookPatternResult:
    return BookPatternResult(
        strategy_key=key,
        state="INVALIDATED",
        observed_evidence=evidence,
        invalidations=invalidations,
        candle_refs=refs,
    )


#: Rank of states for choosing between the up-side and down-side candidate
#: seeds of the Magic-V family (a completed setup beats an uncompleted one).
_STATE_RANK = {
    "CONFIRMED_PATTERN": 3,
    "INVALIDATED": 2,
    "AWAITING_CONFIRMATION": 1,
    "FORMING": 0,
    "INSUFFICIENT_DATA": 0,
}


def _best_side(results: list[tuple[int, BookPatternResult]]) -> BookPatternResult:
    """Pick the most advanced state; tie-break on the most recent seed."""
    return max(results, key=lambda item: (_STATE_RANK.get(item[1].state, 0), item[0]))[1]


# ---------------------------------------------------------------------------
# SS1 - Sequence Breakout Continuation (1 + 2 back-to-back, line "in between")
# ---------------------------------------------------------------------------
def detect_ss1(
    candles: list[dict[str, Any]], *, last_candle_forming: bool = False
) -> BookPatternResult:
    sides = [
        (seed["end"], _ss1_side(candles, side, last_candle_forming=last_candle_forming))
        for side in ("up", "down")
        for seed in [_magic_v_seed(candles, side=side)]
        if seed is not None
    ]
    if not sides:
        if len(candles) < 3:
            return _insufficient("ss1", ["fewer than 3 closed candles"])
        return _forming(
            "ss1",
            ["no completed 1+2 seed (green-red-red or red-green-green) at the series end"],
        )
    return _best_side(sides)


def _ss1_side(
    candles: list[dict[str, Any]], side: str, *, last_candle_forming: bool
) -> BookPatternResult:
    seed = _magic_v_seed(candles, side=side)
    if seed is None:
        raise ValueError("ss1 side requires a seed")
    # The book: "place a horizontal line in between the 2 back-to-back
    # candles" - i.e. across the two PAIR candles, not the first colour change.
    pair_left, pair_right = seed["end"] - 1, seed["end"]
    level = (
        max(_h(candles[pair_left]), _h(candles[pair_right]))
        if side == "up"
        else min(_l(candles[pair_left]), _l(candles[pair_right]))
    )
    evidence = [
        f"1 {seed['first']} candle followed by 2 back-to-back {seed['pair']} "
        f"candles (candles {seed['left']}-{seed['right']})",
        "reference level drawn across the two back-to-back candles "
        f"(level={level:.5f}, book wording: 'in between')",
    ]
    start = seed["end"] + 1
    brk = (
        _first_break_up(candles, start, level)
        if side == "up"
        else _first_break_down(candles, start, level)
    )
    direction = "bullish" if side == "up" else "bearish"
    trend_ok, trend_note = _trend_gate(candles, seed["end"], ("trending", "ranging"))
    if brk is None:
        return BookPatternResult(
            strategy_key="ss1",
            state="AWAITING_CONFIRMATION",
            observed_evidence=evidence,
            missing_conditions=["breakout of the reference level has not closed yet"],
            reference_level=level,
            level_kind="two_candle_span",
        )
    stoch_ok, stoch_note = _stoch_gate(candles, brk, direction)
    evidence.append(
        f"breakout candle {brk} closed {'above' if side == 'up' else 'below'} "
        "the reference level (the book's illustration accepts wick+body break)"
    )
    return _finish(
        "ss1",
        candles,
        True,
        direction=direction,
        refs=seed["refs"] + [brk],
        evidence=evidence,
        missing=[],
        level=level,
        level_kind="two_candle_span",
        trend_ok=trend_ok,
        trend_note=trend_note,
        stoch_ok=stoch_ok,
        stoch_note=stoch_note,
        completed_at=brk,
        last_forming=last_candle_forming,
    )


def _magic_v_seed(
    candles: list[dict[str, Any]], *, side: str
) -> dict[str, Any] | None:
    """1 opposite + 2 back-to-back same-colour candles ending near the end."""
    n = len(candles)
    for end in range(n - 1, max(n - 1 - MAX_SEED_GAP, 2) - 1, -1):
        if end < 2:
            break
        pair_colour = "red" if side == "up" else "green"
        first_colour = "green" if side == "up" else "red"
        if (
            _color(candles[end]) == pair_colour
            and _color(candles[end - 1]) == pair_colour
            and _color(candles[end - 2]) == first_colour
        ):
            return {
                "side": side,
                "first": first_colour,
                "pair": pair_colour,
                "left": end - 2,
                "right": end,
                "end": end,
                "refs": [end - 2, end - 1, end],
            }
    return None


# ---------------------------------------------------------------------------
# SS2 - Magic V (breakout, then ONE candle decides the trade direction)
# ---------------------------------------------------------------------------
def detect_ss2(
    candles: list[dict[str, Any]], *, last_candle_forming: bool = False
) -> BookPatternResult:
    if len(candles) < 4:
        return _insufficient("ss2", ["fewer than 4 closed candles"])
    sides = [
        (seed["end"], _ss2_side(candles, side, last_candle_forming=last_candle_forming))
        for side in ("up", "down")
        for seed in [_magic_v_seed(candles, side=side)]
        if seed is not None
    ]
    if not sides:
        return _forming("ss2", ["no Magic V seed (1 + 2 back-to-back candles) at the series end"])
    return _best_side(sides)


def _ss2_side(
    candles: list[dict[str, Any]], side: str, *, last_candle_forming: bool
) -> BookPatternResult:
    seed = _magic_v_seed(candles, side=side)
    if seed is None:
        raise ValueError("ss2 side requires a seed")
    level = max(_h(candles[i]) for i in seed["refs"])
    level_kind = "seed_top" if side == "up" else "seed_bottom"
    evidence = [
        f"Magic V seed: 1 {seed['first']} + 2 {seed['pair']} candles "
        f"(candles {seed['left']}-{seed['right']})",
        f"reference line on {'top' if side == 'up' else 'bottom'} of the seed "
        f"candles (level={level:.5f})",
    ]
    start = seed["end"] + 1
    brk = (
        _first_break_up(candles, start, level)
        if side == "up"
        else _first_break_down(candles, start, level)
    )
    if brk is None:
        return BookPatternResult(
            strategy_key="ss2",
            state="AWAITING_CONFIRMATION",
            observed_evidence=evidence,
            missing_conditions=["breakout of the seed line has not closed yet"],
            reference_level=level,
            level_kind=level_kind,
        )
    evidence.append(f"breakout candle {brk} closed beyond the seed line")
    if brk + 1 >= len(candles):
        return BookPatternResult(
            strategy_key="ss2",
            state="AWAITING_CONFIRMATION",
            observed_evidence=evidence,
            missing_conditions=[
                "the book requires waiting for ONE candle after the breakout; "
                "that candle has not closed yet"
            ],
            reference_level=level,
            level_kind=level_kind,
        )
    decider = candles[brk + 1]
    decider_colour = _color(decider)
    if decider_colour == "neutral":
        return BookPatternResult(
            strategy_key="ss2",
            state="AWAITING_CONFIRMATION",
            observed_evidence=evidence,
            missing_conditions=[
                "the post-breakout decision candle closed exactly at its open "
                "(no colour to follow)"
            ],
            reference_level=level,
            level_kind=level_kind,
        )
    direction = "bullish" if decider_colour == "green" else "bearish"
    evidence.append(
        f"the book's waited-for candle {brk + 1} is {decider_colour}; the "
        "illustration rule 'green -> next candle green, red -> next candle "
        "red' sets the trade direction"
    )
    trend_ok, trend_note = _trend_gate(candles, seed["end"], ("trending", "ranging"))
    stoch_ok, stoch_note = _stoch_gate(candles, brk + 1, direction)
    return _finish(
        "ss2",
        candles,
        True,
        direction=direction,
        refs=seed["refs"] + [brk, brk + 1],
        evidence=evidence,
        missing=[],
        level=level,
        level_kind=level_kind,
        trend_ok=trend_ok,
        trend_note=trend_note,
        stoch_ok=stoch_ok,
        stoch_note=stoch_note,
        completed_at=brk + 1,
        last_forming=last_candle_forming,
    )


# ---------------------------------------------------------------------------
# SS3 - Magic V Advanced (breakout candle itself is the entry)
# ---------------------------------------------------------------------------
def detect_ss3(
    candles: list[dict[str, Any]], *, last_candle_forming: bool = False
) -> BookPatternResult:
    if len(candles) < 4:
        return _insufficient("ss3", ["fewer than 4 closed candles"])
    sides = [
        (seed["end"], _ss3_side(candles, side, last_candle_forming=last_candle_forming))
        for side in ("up", "down")
        for seed in [_magic_v_seed(candles, side=side)]
        if seed is not None
    ]
    if not sides:
        return _forming(
            "ss3", ["no Magic V seed (1 + 2 back-to-back candles) at the series end"]
        )
    return _best_side(sides)


def _ss3_side(
    candles: list[dict[str, Any]], side: str, *, last_candle_forming: bool
) -> BookPatternResult:
    seed = _magic_v_seed(candles, side=side)
    if seed is None:
        raise ValueError("ss3 side requires a seed")
    level = max(_h(candles[i]) for i in seed["refs"])
    level_kind = "seed_top" if side == "up" else "seed_bottom"
    direction = "bullish" if side == "up" else "bearish"
    evidence = [
        f"Magic V Advanced seed: 1 {seed['first']} + 2 {seed['pair']} candles "
        f"(candles {seed['left']}-{seed['right']})",
        f"reference line on {'top' if side == 'up' else 'bottom'} of the seed "
        f"candles (level={level:.5f})",
    ]
    start = seed["end"] + 1
    brk = (
        _first_break_up(candles, start, level)
        if side == "up"
        else _first_break_down(candles, start, level)
    )
    if brk is None:
        return BookPatternResult(
            strategy_key="ss3",
            state="AWAITING_CONFIRMATION",
            observed_evidence=evidence,
            missing_conditions=["breakout of the seed line has not closed yet"],
            reference_level=level,
            level_kind=level_kind,
        )
    evidence.append(
        f"breakout candle {brk} closed beyond the seed line; unlike SS2 the "
        "book trades this candle directly (timing difference preserved)"
    )
    trend_ok, trend_note = _trend_gate(candles, seed["end"], ("trending",))
    stoch_ok, stoch_note = _stoch_gate(candles, brk, direction)
    return _finish(
        "ss3",
        candles,
        True,
        direction=direction,
        refs=seed["refs"] + [brk],
        evidence=evidence,
        missing=[],
        level=level,
        level_kind=level_kind,
        trend_ok=trend_ok,
        trend_note=trend_note,
        stoch_ok=stoch_ok,
        stoch_note=stoch_note,
        completed_at=brk,
        last_forming=last_candle_forming,
    )


# ---------------------------------------------------------------------------
# Shared four/five-candle run machinery for SS5 / SS6 / SS19 / SS21
# ---------------------------------------------------------------------------
def _run_with_pullback(
    candles: list[dict[str, Any]], *, minimum_run: int
) -> dict[str, Any] | None:
    """Most recent run (>= minimum_run same colour) ending near the end."""
    n = len(candles)
    for end in range(n - 1, max(n - 1 - MAX_SEED_GAP, minimum_run - 1) - 1, -1):
        start, colour, length = _trailing_run(candles, end)
        if length >= minimum_run and colour in ("green", "red"):
            return {"start": start, "end": end, "colour": colour, "length": length}
    return None


def _partial_run_progress(candles: list[dict[str, Any]], minimum_run: int) -> str:
    _, colour, length = _trailing_run(candles, len(candles) - 1)
    if colour == "neutral":
        return "the last closed candle is neutral (doji-like) and breaks any run"
    return f"the current trailing run is {length} {colour} candle(s) of the {minimum_run}+ required"


# ---------------------------------------------------------------------------
# SS5 - Four-Candle Pullback Hold (pullback holds BELOW the line -> trend trade)
# ---------------------------------------------------------------------------
def detect_ss5(
    candles: list[dict[str, Any]], *, last_candle_forming: bool = False
) -> BookPatternResult:
    if len(candles) < 5:
        return _insufficient("ss5", ["fewer than 5 closed candles"])
    run = _run_with_pullback(candles, minimum_run=4)
    if run is None:
        return _forming("ss5", [_partial_run_progress(candles, 4)])
    run_colour = run["colour"]
    opposite = "red" if run_colour == "green" else "green"
    i = run["end"] + 1
    pullbacks: list[int] = []
    while i < len(candles) and _color(candles[i]) == opposite and len(pullbacks) < 3:
        pullbacks.append(i)
        i += 1
    if not pullbacks:
        return BookPatternResult(
            strategy_key="ss5",
            state="FORMING",
            observed_evidence=[
                f"run of {run['length']} {run_colour} candles "
                f"(candles {run['start']}-{run['end']})",
                "awaiting 1 (book illustrations: 1 or 2) opposite-colour "
                "pullback candle(s)",
            ],
            candle_refs=list(range(run["start"], run["end"] + 1)),
        )
    if len(pullbacks) >= 3:
        return _invalidated(
            "ss5",
            [f"run of {run['length']} {run_colour} candles followed by "
             f"{len(pullbacks)} opposite candles"],
            ["three opposite-colour candles: the book states the pattern is "
             "not valid"],
            [run["start"], *pullbacks],
        )
    level = (
        max(_h(candles[idx]) for idx in pullbacks)
        if run_colour == "green"
        else min(_l(candles[idx]) for idx in pullbacks)
    )
    level_kind = "pullback_top" if run_colour == "green" else "pullback_bottom"
    direction = "bullish" if run_colour == "green" else "bearish"
    evidence = [
        f"run of {run['length']} {run_colour} candles "
        f"(candles {run['start']}-{run['end']})",
        f"{len(pullbacks)} opposite-colour pullback candle(s) "
        f"(candles {pullbacks[0]}-{pullbacks[-1]})",
        f"reference line at the {'top' if run_colour == 'green' else 'bottom'} "
        f"of the pullback candle(s) (level={level:.5f})",
    ]
    nxt = pullbacks[-1] + 1
    if nxt >= len(candles):
        return BookPatternResult(
            strategy_key="ss5",
            state="AWAITING_CONFIRMATION",
            observed_evidence=evidence,
            missing_conditions=[
                "the candle after the pullback has not closed yet; it must "
                "FAIL to break the line for the trend trade"
            ],
            reference_level=level,
            level_kind=level_kind,
        )
    broke = (
        _h(candles[nxt]) > level if run_colour == "green" else _l(candles[nxt]) < level
    )
    if broke:
        return _invalidated(
            "ss5",
            [
                *evidence,
                f"candle {nxt} broke the reference line "
                f"({'above' if run_colour == 'green' else 'below'})",
            ],
            [
                "the candle after the pullback broke the reference line: the "
                "book invalidates the setup when the level is taken"
            ],
            [run["start"], *pullbacks, nxt],
        )
    evidence.append(
        f"candle {nxt} failed to break the reference line - the pullback "
        "holds, which is the book's trigger"
    )
    trend_ok, trend_note = _trend_gate(candles, run["end"], ("trending",))
    stoch_ok, stoch_note = _stoch_gate(candles, nxt, direction)
    return _finish(
        "ss5",
        candles,
        True,
        direction=direction,
        refs=[run["start"], *pullbacks, nxt],
        evidence=evidence,
        missing=[],
        level=level,
        level_kind=level_kind,
        trend_ok=trend_ok,
        trend_note=trend_note,
        stoch_ok=stoch_ok,
        stoch_note=stoch_note,
        completed_at=nxt,
        last_forming=last_candle_forming,
    )


# ---------------------------------------------------------------------------
# SS6 - Four-Candle Body Breakout (close must break the level)
# ---------------------------------------------------------------------------
def detect_ss6(
    candles: list[dict[str, Any]], *, last_candle_forming: bool = False
) -> BookPatternResult:
    if len(candles) < 6:
        return _insufficient("ss6", ["fewer than 6 closed candles"])
    run = _run_with_pullback(candles, minimum_run=4)
    if run is None:
        return _forming("ss6", [_partial_run_progress(candles, 4)])
    run_colour = run["colour"]
    opposite = "red" if run_colour == "green" else "green"
    pullback = run["end"] + 1
    if pullback >= len(candles) or _color(candles[pullback]) != opposite:
        return _forming(
            "ss6",
            [
                f"run of {run['length']} {run_colour} candles "
                f"(candles {run['start']}-{run['end']})",
                "awaiting the single opposite-colour candle that carries the "
                "reference line",
            ],
        )
    level = _h(candles[pullback]) if run_colour == "green" else _l(candles[pullback])
    level_kind = "opposite_candle_top" if run_colour == "green" else "opposite_candle_bottom"
    direction = "bullish" if run_colour == "green" else "bearish"
    evidence = [
        f"run of {run['length']} {run_colour} candles "
        f"(candles {run['start']}-{run['end']})",
        f"opposite-colour candle {pullback} with the reference line at its "
        f"{'top' if run_colour == 'green' else 'bottom'} (level={level:.5f})",
    ]
    nxt = pullback + 1
    if nxt >= len(candles):
        return BookPatternResult(
            strategy_key="ss6",
            state="AWAITING_CONFIRMATION",
            observed_evidence=evidence,
            missing_conditions=[
                "the book requires the next candle to break the level WITH ITS "
                "BODY (closing price); that candle has not closed yet"
            ],
            reference_level=level,
            level_kind=level_kind,
        )
    row = candles[nxt]
    body_break = _c(row) > level if run_colour == "green" else _c(row) < level
    wick_touch = _h(row) > level if run_colour == "green" else _l(row) < level
    if not body_break and wick_touch:
        return BookPatternResult(
            strategy_key="ss6",
            state="AWAITING_CONFIRMATION",
            observed_evidence=[*evidence, f"candle {nxt} touched the level with its wick only"],
            missing_conditions=[
                "wick-only touch is NOT a valid breakout (book: 'only through "
                "the body is valid'); a closing break is still required"
            ],
            reference_level=level,
            level_kind=level_kind,
        )
    if not body_break:
        return BookPatternResult(
            strategy_key="ss6",
            state="AWAITING_CONFIRMATION",
            observed_evidence=[*evidence, f"candle {nxt} closed without touching the level"],
            missing_conditions=[
                "no body close beyond the reference level yet "
                "(book: 'only through the body is valid')"
            ],
            reference_level=level,
            level_kind=level_kind,
        )
    evidence.append(
        f"candle {nxt} closed {'above' if run_colour == 'green' else 'below'} "
        "the level with its body - the book's required breakout form"
    )
    trend_ok, trend_note = _trend_gate(candles, run["end"], ("trending",))
    stoch_ok, stoch_note = _stoch_gate(candles, nxt, direction)
    return _finish(
        "ss6",
        candles,
        True,
        direction=direction,
        refs=list(range(run["start"], nxt + 1)),
        evidence=evidence,
        missing=[],
        level=level,
        level_kind=level_kind,
        trend_ok=trend_ok,
        trend_note=trend_note,
        stoch_ok=stoch_ok,
        stoch_note=stoch_note,
        completed_at=nxt,
        last_forming=last_candle_forming,
    )


# ---------------------------------------------------------------------------
# SS19 - Doji-Level Breakout (break direction decides the trade direction)
# ---------------------------------------------------------------------------
def detect_ss19(
    candles: list[dict[str, Any]], *, last_candle_forming: bool = False
) -> BookPatternResult:
    if len(candles) < 6:
        return _insufficient("ss19", ["fewer than 6 closed candles"])
    run = _run_with_pullback(candles, minimum_run=4)
    if run is None:
        return _forming("ss19", [_partial_run_progress(candles, 4)])
    run_colour = run["colour"]
    # Implementation choice (book does not say): the doji may appear within
    # the first three candles after the run.
    doji_at = None
    for i in range(run["end"] + 1, min(run["end"] + 4, len(candles))):
        if _is_doji(candles[i]):
            doji_at = i
            break
    if doji_at is None:
        still_open = run["end"] + 3 >= len(candles)
        if still_open:
            return BookPatternResult(
                strategy_key="ss19",
                state="FORMING",
                observed_evidence=[
                    f"run of {run['length']} {run_colour} candles "
                    f"(candles {run['start']}-{run['end']})",
                    "awaiting a doji within three candles after the run",
                ],
            )
        return _forming(
            "ss19",
            [
                f"run of {run['length']} {run_colour} candles "
                f"(candles {run['start']}-{run['end']})",
                "no doji appeared within three candles after the run",
            ],
        )
    level_low, level_high = _l(candles[doji_at]), _h(candles[doji_at])
    evidence = [
        f"run of {run['length']} {run_colour} candles "
        f"(candles {run['start']}-{run['end']})",
        f"doji at candle {doji_at}; the book's single 'line at the doji' is "
        "under-specified, so the doji range "
        f"[{level_low:.5f}, {level_high:.5f}] is used as the reference zone",
    ]
    for i in range(doji_at + 1, len(candles)):
        if _c(candles[i]) > level_high:
            direction = "bullish"
            break
        if _c(candles[i]) < level_low:
            direction = "bearish"
            break
    else:
        return BookPatternResult(
            strategy_key="ss19",
            state="AWAITING_CONFIRMATION",
            observed_evidence=evidence,
            missing_conditions=[
                "no candle has closed beyond the doji range yet; the break "
                "direction decides the trade direction"
            ],
            reference_level=(level_low + level_high) / 2.0,
            level_kind="doji_range",
        )
    evidence.append(
        f"candle {i} closed {'above the doji high' if direction == 'bullish' else 'below the doji low'}; "
        "the break direction is the trade direction (explicit interpretation, "
        "see recorded ambiguities)"
    )
    trend_ok, trend_note = _trend_gate(candles, run["end"], ("trending",))
    stoch_ok, stoch_note = _stoch_gate(candles, i, direction)
    return _finish(
        "ss19",
        candles,
        True,
        direction=direction,
        refs=[run["start"], doji_at, i],
        evidence=evidence,
        missing=[],
        level=(level_low + level_high) / 2.0,
        level_kind="doji_range",
        trend_ok=trend_ok,
        trend_note=trend_note,
        stoch_ok=stoch_ok,
        stoch_note=stoch_note,
        completed_at=i,
        last_forming=last_candle_forming,
    )


# ---------------------------------------------------------------------------
# SS21 - Five-Candle Reference-Candle Breakout
# ---------------------------------------------------------------------------
def detect_ss21(
    candles: list[dict[str, Any]], *, last_candle_forming: bool = False
) -> BookPatternResult:
    if len(candles) < 7:
        return _insufficient("ss21", ["fewer than 7 closed candles"])
    run = _run_with_pullback(candles, minimum_run=5)
    if run is None:
        return _forming("ss21", [_partial_run_progress(candles, 5)])
    run_colour = run["colour"]
    opposite = "red" if run_colour == "green" else "green"
    reference = run["end"] + 1
    if reference >= len(candles) or _color(candles[reference]) != opposite:
        return _forming(
            "ss21",
            [
                f"run of {run['length']} {run_colour} candles "
                f"(candles {run['start']}-{run['end']})",
                "awaiting the single opposite-colour reference candle",
            ],
        )
    level = _h(candles[reference]) if run_colour == "green" else _l(candles[reference])
    level_kind = "reference_candle_high" if run_colour == "green" else "reference_candle_low"
    direction = "bullish" if run_colour == "green" else "bearish"
    evidence = [
        f"run of {run['length']} {run_colour} candles "
        f"(candles {run['start']}-{run['end']})",
        f"opposite-colour reference candle {reference}; level marked on its "
        f"{'high' if run_colour == 'green' else 'low'} (level={level:.5f})",
    ]
    brk = None
    for i in range(reference + 1, len(candles)):
        closes_beyond = (
            _c(candles[i]) > level if run_colour == "green" else _c(candles[i]) < level
        )
        if closes_beyond:
            brk = i
            break
    if brk is None:
        return BookPatternResult(
            strategy_key="ss21",
            state="AWAITING_CONFIRMATION",
            observed_evidence=evidence,
            missing_conditions=[
                "no candle has closed beyond the reference candle's level yet"
            ],
            reference_level=level,
            level_kind=level_kind,
        )
    evidence.append(
        f"breakout candle {brk} closed beyond the reference level (closing "
        "break used as the conservative reading of 'successful breakout')"
    )
    trend_ok, trend_note = _trend_gate(candles, run["end"], ("trending",))
    stoch_ok, stoch_note = _stoch_gate(candles, brk, direction)
    return _finish(
        "ss21",
        candles,
        True,
        direction=direction,
        refs=[run["start"], reference, brk],
        evidence=evidence,
        missing=[],
        level=level,
        level_kind=level_kind,
        trend_ok=trend_ok,
        trend_note=trend_note,
        stoch_ok=stoch_ok,
        stoch_note=stoch_note,
        completed_at=brk,
        last_forming=last_candle_forming,
    )


# ---------------------------------------------------------------------------
# SS22 / SS23 - Rising / Falling Three Method
# ---------------------------------------------------------------------------
def _three_method(
    candles: list[dict[str, Any]],
    key: str,
    *,
    first_colour: str,
    last_candle_forming: bool,
) -> BookPatternResult:
    second = "red" if first_colour == "green" else "green"
    direction = "bullish" if first_colour == "green" else "bearish"
    if len(candles) < 7:
        return _insufficient(key, ["fewer than 7 closed candles"])
    tail = candles[-7:]
    cols = [_color(c) for c in tail]
    expected = [first_colour] * 3 + [second] * 3 + [first_colour]
    evidence_prefix = (
        f"3 {first_colour} candles, 3 {second} candles, then 1 {first_colour} "
        "candle engulfing all three"
    )
    if cols == expected:
        # The three OPPOSITE-colour candles are tail[3:6]; tail[6] is the
        # final engulfing candle of the first colour.
        opposites = tail[3:6]
        engulf = all(_h(tail[6]) >= _h(s) for s in opposites) and all(
            _l(tail[6]) <= _l(s) for s in opposites
        )
        if not engulf:
            return _forming(
                key,
                [
                    "the colour sequence matches but the final candle does not "
                    "engulf the three opposite candles by full range "
                    "(implementation choice: body-only engulf is not accepted)"
                ],
            )
        # Trend context: everything BEFORE the 7-candle sequence.
        trend_ok, trend_note = _trend_gate(candles, len(candles) - 8, ("trending",))
        stoch_ok, stoch_note = _stoch_gate(candles, len(candles) - 1, direction)
        evidence = [
            evidence_prefix,
            f"the {first_colour} candle closes the series and engulfs the "
            "three opposite candles' full high/low range",
        ]
        return _finish(
            key,
            candles,
            True,
            direction=direction,
            refs=list(range(len(candles) - 7, len(candles))),
            evidence=evidence,
            missing=[],
            level=None,
            level_kind="",
            trend_ok=trend_ok,
            trend_note=trend_note,
            stoch_ok=stoch_ok,
            stoch_note=stoch_note,
            completed_at=len(candles) - 1,
            last_forming=last_candle_forming,
        )
    # Check for a still-building prefix at the series end.
    prefix3 = [first_colour] * 3
    prefix6 = [first_colour] * 3 + [second] * 3
    if cols[-6:] == prefix6:
        return BookPatternResult(
            strategy_key=key,
            state="AWAITING_CONFIRMATION",
            observed_evidence=[
                f"3 {first_colour} candles followed by 3 {second} candles "
                "(candles {}-{})".format(len(candles) - 6, len(candles) - 1)
            ],
            missing_conditions=[
                f"the book requires 1 {first_colour} candle engulfing all "
                "three opposite candles; it has not appeared"
            ],
        )
    if cols[-3:] == prefix3:
        return BookPatternResult(
            strategy_key=key,
            state="FORMING",
            observed_evidence=[
                f"3 back-to-back {first_colour} candles at the series end "
                f"(candles {len(candles) - 3}-{len(candles) - 1})",
                f"awaiting 3 back-to-back {second} candles then the engulfing "
                f"{first_colour} candle",
            ],
        )
    return _forming(
        key,
        [
            "no Rising/Falling Three Method sequence at the series end "
            f"(needed: 3 {first_colour}, 3 {second}, 1 engulfing {first_colour})"
        ],
    )


def detect_ss22(
    candles: list[dict[str, Any]], *, last_candle_forming: bool = False
) -> BookPatternResult:
    return _three_method(
        candles, "ss22", first_colour="green", last_candle_forming=last_candle_forming
    )


def detect_ss23(
    candles: list[dict[str, Any]], *, last_candle_forming: bool = False
) -> BookPatternResult:
    return _three_method(
        candles, "ss23", first_colour="red", last_candle_forming=last_candle_forming
    )


# ---------------------------------------------------------------------------
# CH7 Strategy 1 - EMA5 + Parabolic SAR + Stochastic alignment
# ---------------------------------------------------------------------------
def detect_ch7_s1(
    candles: list[dict[str, Any]], *, last_candle_forming: bool = False
) -> BookPatternResult:
    key = "ch7_s1"
    if len(candles) < 20:
        return _insufficient(
            key,
            [
                "fewer than 20 closed candles; EMA5/SAR/Stochastic alignment "
                "cannot be evaluated"
            ],
        )
    closes = [_c(row) for row in candles]
    ema5 = ema(closes, 5)
    sar = parabolic_sar(candles)
    bodies = sorted(_body(row) for row in candles[-11:-1])
    median_body = bodies[len(bodies) // 2] if bodies else 0.0

    last_cross: tuple[int, str] | None = None
    for i in range(1, len(candles)):
        if ema5[i] is None or ema5[i - 1] is None:
            continue
        up_cross = _c(candles[i - 1]) <= ema5[i - 1] and _c(candles[i]) > ema5[i]
        down_cross = _c(candles[i - 1]) >= ema5[i - 1] and _c(candles[i]) < ema5[i]
        if up_cross:
            last_cross = (i, "bullish")
        elif down_cross:
            last_cross = (i, "bearish")

    if last_cross is None:
        return _forming(
            key,
            ["no candle has closed across the EMA 5 line yet in the provided range"],
        )
    idx, direction = last_cross
    evidence = [
        f"candle {idx} closed {'above' if direction == 'bullish' else 'below'} "
        "the EMA 5 line (the book's 'break of the EMA 5')",
    ]
    if idx == len(candles) - 1:
        state_prefix = "the cross happened on the last closed candle"
    else:
        state_prefix = f"the most recent EMA 5 cross is at candle {idx}"
    strong = _body(candles[idx]) >= STRONG_BODY_MEDIAN_FACTOR * median_body
    if strong:
        evidence.append(
            f"candle {idx} body {_body(candles[idx]):.5f} >= median body "
            f"{median_body:.5f} of the previous 10 candles (our explicit "
            "reading of the book's undefined 'strong candle')"
        )
    else:
        return BookPatternResult(
            strategy_key=key,
            state="AWAITING_CONFIRMATION",
            observed_evidence=[state_prefix, *evidence],
            missing_conditions=[
                "the crossing candle is not 'strong' by our explicit metric "
                "(body below the median of the previous 10 candles)"
            ],
        )
    sar_row = sar[idx]
    sar_supports = (
        sar_row is not None
        and (sar_row < _c(candles[idx]) if direction == "bullish" else sar_row > _c(candles[idx]))
    )
    if sar_supports:
        evidence.append(
            f"Parabolic SAR at candle {idx} sits {'below' if direction == 'bullish' else 'above'} "
            "the close (supporting the direction)"
        )
    else:
        return BookPatternResult(
            strategy_key=key,
            state="AWAITING_CONFIRMATION",
            observed_evidence=[state_prefix, *evidence],
            missing_conditions=[
                "Parabolic SAR does not support the trade direction "
                "(book requirement)"
            ],
        )
    stoch_ok, stoch_note = _stoch_gate(candles, idx, direction)
    evidence.append(state_prefix)
    trend_ok, trend_note = _trend_gate(candles, idx, ("trending",))
    return _finish(
        key,
        candles,
        True,
        direction=direction,
        refs=[idx],
        evidence=evidence,
        missing=[],
        level=float(ema5[idx]) if ema5[idx] is not None else None,
        level_kind="ema5",
        trend_ok=trend_ok,
        trend_note=trend_note,
        stoch_ok=stoch_ok,
        stoch_note=stoch_note,
        completed_at=idx,
        last_forming=last_candle_forming,
        extra_ambiguities=[
            "the book's exit rule ('until an opposite colour candle crosses "
            "EMA 5') is a holding rule, not part of pattern confirmation"
        ],
    )


#: Registry of implemented priority detectors.
BOOK_DETECTORS: dict[str, Callable[..., BookPatternResult]] = {
    "ss1": detect_ss1,
    "ss2": detect_ss2,
    "ss3": detect_ss3,
    "ss5": detect_ss5,
    "ss6": detect_ss6,
    "ss19": detect_ss19,
    "ss21": detect_ss21,
    "ss22": detect_ss22,
    "ss23": detect_ss23,
    "ch7_s1": detect_ch7_s1,
}
