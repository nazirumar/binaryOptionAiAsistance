"""Candle-sequence engines (Steps 9-12).

* **Reference sequences (Step 9):** consecutive directional runs and whether the
  buyer/seller sequence is strengthening or weakening. Run length alone is never
  turned into a probability.
* **Similar sequences (Step 10):** signature matching against *past* windows only,
  with a minimum sample-size gate. Historical outcomes are recorded but never
  promoted to a predictive claim.
* **Lonely candles (Step 11):** isolated candles inside an opposing run, with the
  observation kept separate from the (hypothesis) interpretation.
* **Eight psychological sequences (Step 12):** course templates, not signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.price_action.constants import Direction
from apps.price_action.services.candle_math import (
    body_range_ratio,
    is_bearish,
    is_bullish,
)
from apps.price_action.services.config import PriceActionConfig


def _f(candle: dict[str, Any], key: str) -> float:
    return float(candle.get(key, 0.0) or 0.0)


def sign(candle: dict[str, Any]) -> int:
    """+1 bullish, -1 bearish, 0 flat/doji."""
    if is_bullish(candle):
        return 1
    if is_bearish(candle):
        return -1
    return 0


@dataclass(frozen=True, slots=True)
class Run:
    direction: str
    start: int
    end: int
    length: int
    price_delta: float


def consecutive_bullish(candles: list[dict[str, Any]], start: int = 0) -> int:
    count = 0
    for c in candles[start:]:
        if is_bullish(c):
            count += 1
        else:
            break
    return count


def consecutive_bearish(candles: list[dict[str, Any]], start: int = 0) -> int:
    count = 0
    for c in candles[start:]:
        if is_bearish(c):
            count += 1
        else:
            break
    return count


def directional_runs(candles: list[dict[str, Any]]) -> list[Run]:
    """Merge consecutive same-direction candles into runs."""
    runs: list[Run] = []
    start = 0
    for i in range(1, len(candles) + 1):
        end_of_run = i == len(candles)
        if (
            not end_of_run
            and sign(candles[i]) == sign(candles[start])
            and sign(candles[start]) != 0
        ):
            continue
        direction_sign = sign(candles[start])
        if direction_sign != 0:
            segment = candles[start:i]
            runs.append(
                Run(
                    direction=Direction.BULLISH if direction_sign > 0 else Direction.BEARISH,
                    start=start,
                    end=i - 1,
                    length=len(segment),
                    price_delta=_f(segment[-1], "close") - _f(segment[0], "open"),
                )
            )
        start = i
    return runs


def analyze_reference_sequences(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any]:
    """Describe the current directional run and whether it is strengthening."""
    config = config or PriceActionConfig.from_settings()
    runs = directional_runs(candles)
    if not runs:
        return {"available": False, "runs": [], "reasons": ["no directional runs"]}
    current = runs[-1]
    prior_same = [r for r in runs[:-1] if r.direction == current.direction]
    avg_prior_delta = (
        sum(abs(r.price_delta) for r in prior_same) / len(prior_same) if prior_same else None
    )
    current_delta = abs(current.price_delta)
    strengthening = avg_prior_delta is not None and current_delta > avg_prior_delta
    weakening = avg_prior_delta is not None and current_delta < avg_prior_delta
    increasing_counts = len(runs) >= 2 and current.length > runs[-2].length
    decreasing_counts = len(runs) >= 2 and current.length < runs[-2].length
    return {
        "available": True,
        "runs": [
            {
                "direction": r.direction,
                "start": r.start,
                "end": r.end,
                "length": r.length,
                "price_delta": r.price_delta,
            }
            for r in runs
        ],
        "current_direction": current.direction,
        "current_run_length": current.length,
        "extended": current.length >= config.extended_run_length,
        "increasing_run_counts": increasing_counts,
        "decreasing_run_counts": decreasing_counts,
        "strengthening": strengthening,
        "weakening": weakening,
        "reasons": [
            f"current {current.direction} run length {current.length}",
            "run length is descriptive only and is not a probability",
        ],
    }


def similar_sequences(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any]:
    """Match the trailing signature against earlier windows (past data only)."""
    config = config or PriceActionConfig.from_settings()
    n = len(candles)
    length = config.sequence_signature_length
    if n < length + 1:
        return {"available": False, "matches": [], "reasons": ["not enough candles"]}
    signature = tuple(sign(c) for c in candles[n - length :])
    matches: list[dict[str, Any]] = []
    # Only windows that end strictly before the trailing window are searched, so
    # the trailing window's own future candle is never consulted.
    for p in range(0, n - length - 1):
        window = tuple(sign(c) for c in candles[p : p + length])
        same = sum(1 for a, b in zip(signature, window, strict=True) if a == b)
        similarity = same / length
        if similarity < config.similar_sequence_min_similarity:
            continue
        outcome_index = p + length
        outcome = sign(candles[outcome_index])
        matches.append(
            {
                "start": p,
                "end": outcome_index - 1,
                "similarity": similarity,
                "outcome_direction": (
                    Direction.BULLISH if outcome > 0 else Direction.BEARISH if outcome < 0 else None
                ),
                "outcome_index": outcome_index,
            }
        )
    outcome_counts: dict[str, int] = {}
    for m in matches:
        key = str(m["outcome_direction"])
        outcome_counts[key] = outcome_counts.get(key, 0) + 1
    enough = len(matches) >= config.similar_sequence_min_samples
    return {
        "available": True,
        "signature": list(signature),
        "matches": matches,
        "occurrences": len(matches),
        "outcome_counts": outcome_counts,
        "min_samples_met": enough,
        "predictive_claim": False,
        "reasons": [
            "historical outcomes are descriptive and must not be treated as predictive",
        ],
    }


def lonely_candles(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> list[dict[str, Any]]:
    """Isolated candles inside an opposing run (Step 11)."""
    del config  # currently only used for future extensions
    out: list[dict[str, Any]] = []
    for i in range(1, len(candles) - 1):
        prev_sign = sign(candles[i - 1])
        cur_sign = sign(candles[i])
        next_sign = sign(candles[i + 1])
        if cur_sign == -1 and prev_sign == 1 and next_sign == 1:
            out.append(
                {
                    "index": i,
                    "observation": "isolated bearish candle inside a bullish run",
                    "hypothesis": "candidate seller-stop support",
                    "level": _f(candles[i], "low"),
                    "interpretation_note": "hypothesis only; not inferred intent",
                }
            )
        if cur_sign == 1 and prev_sign == -1 and next_sign == -1:
            out.append(
                {
                    "index": i,
                    "observation": "isolated bullish candle inside a bearish run",
                    "hypothesis": "candidate buyer-stop resistance",
                    "level": _f(candles[i], "high"),
                    "interpretation_note": "hypothesis only; not inferred intent",
                }
            )
    return out


def level_reaction(
    candles: list[dict[str, Any]], level: float, after: int, tolerance: float = 0.0005
) -> bool:
    """Whether later candles reacted to (touched) a lonely candle's level."""
    for c in candles[after + 1 :]:
        if abs(_f(c, "high") - level) / level <= tolerance if level else False:
            return True
        if abs(_f(c, "low") - level) / level <= tolerance if level else False:
            return True
    return False


#: The eight course templates (Step 12). Each is a tuple of directional signs
#: evaluated on consecutive candles. ``None`` acts as a wildcard.
PSYCH_TEMPLATES: dict[str, dict[str, Any]] = {
    "bullish_1_green_red_red": {"pattern": (1, -1, -1), "direction": Direction.BULLISH},
    "bullish_2_green_green_red": {"pattern": (1, 1, -1), "direction": Direction.BULLISH},
    "bullish_3_red_green_red": {"pattern": (-1, 1, -1), "direction": Direction.BULLISH},
    "bullish_4_multiple_green_red": {"pattern": (1, 1, 1, -1), "direction": Direction.BULLISH},
    "bearish_1_red_green_green": {"pattern": (-1, 1, 1), "direction": Direction.BEARISH},
    "bearish_2_red_red_green": {"pattern": (-1, -1, 1), "direction": Direction.BEARISH},
    "bearish_3_green_red_green": {"pattern": (1, -1, 1), "direction": Direction.BEARISH},
    "bearish_4_multiple_red_green": {
        "pattern": (-1, -1, -1, 1),
        "direction": Direction.BEARISH,
    },
}


def _matches(template: tuple[int, ...], observed: tuple[int, ...]) -> bool:
    if len(template) > len(observed):
        return False
    tail = observed[-len(template) :]
    return all(t == o for t, o in zip(template, tail, strict=True))


def psych_sequences(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> list[dict[str, Any]]:
    """Return the course templates that match the trailing candle signs."""
    del config
    observed = tuple(sign(c) for c in candles)
    out: list[dict[str, Any]] = []
    for name, spec in PSYCH_TEMPLATES.items():
        if _matches(spec["pattern"], observed):
            count = len(spec["pattern"])
            out.append(
                {
                    "name": name,
                    "direction": str(spec["direction"]),
                    "candle_count": count,
                    "candle_refs": list(range(len(candles) - count, len(candles))),
                    "context_requirements": [
                        "support/resistance location",
                        "buyer/seller failure context",
                        "SBR/RBS context",
                        "trend direction",
                        "candle location",
                    ],
                    "template_not_signal": True,
                }
            )
    return out


# ---------------------------------------------------------------------------
# Phase 12 (CP6): candle psychology observables
# ---------------------------------------------------------------------------


def candle_progress(candles: list[dict[str, Any]], i: int = -1) -> dict[str, Any] | None:
    """Where the *latest completed* candle closed inside its own range.

    ``progress`` = (close - low) / range: 1.0 = closed on the high, 0.0 = on
    the low. The raw number is reported alongside a coarse label; the label is
    an interpretation, the number is the measurement.
    """
    if not candles:
        return None
    c = candles[i]
    rng = _f(c, "high") - _f(c, "low")
    if rng <= 0:
        return {
            "index": len(candles) - 1 if i == -1 else i,
            "progress": None,
            "label": "flat",
            "note": "zero-range candle; close position is undefined",
        }
    progress = (_f(c, "close") - _f(c, "low")) / rng
    if progress >= 0.8:
        label = "closed_near_high"
    elif progress >= 0.6:
        label = "closed_upper"
    elif progress <= 0.2:
        label = "closed_near_low"
    elif progress <= 0.4:
        label = "closed_lower"
    else:
        label = "closed_mid"
    return {
        "index": len(candles) - 1 if i == -1 else i,
        "progress": progress,
        "label": label,
        "note": "close position within the candle's range; not a prediction",
    }


def run_count(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any]:
    """Length, price travel and extension status of the current directional run."""
    config = config or PriceActionConfig.from_settings()
    runs = directional_runs(candles)
    if not runs:
        return {
            "length": 0,
            "direction": "flat",
            "price_delta": 0.0,
            "extended": False,
            "extended_threshold": config.extended_run_length,
        }
    current = runs[-1]
    return {
        "length": current.length,
        "direction": current.direction,
        "price_delta": current.price_delta,
        "extended": current.length >= config.extended_run_length,
        "extended_threshold": config.extended_run_length,
    }


def strong_close(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any] | None:
    """The latest candle is a *strong close* (large body, close at the extreme).

    Requires both a high body/range ratio and a close in the top/bottom fifth
    of the range. Reports the thresholds used.
    """
    config = config or PriceActionConfig.from_settings()
    if not candles:
        return None
    c = candles[-1]
    rng = _f(c, "high") - _f(c, "low")
    body_ratio = body_range_ratio(c)
    if rng <= 0 or body_ratio is None or body_ratio < config.strong_body_ratio_min:
        return None
    progress = (_f(c, "close") - _f(c, "low")) / rng
    close_at_extreme = progress >= 0.8 or progress <= 0.2
    if not close_at_extreme:
        return None
    direction = "bullish" if _f(c, "close") > _f(c, "open") else "bearish"
    return {
        "type": "strong_close",
        "direction": direction,
        "index": len(candles) - 1,
        "body_ratio": body_ratio,
        "close_progress": progress,
        "thresholds": {
            "strong_body_ratio_min": config.strong_body_ratio_min,
            "close_progress_extreme": 0.8,
        },
        "note": "observable candle quality; not a directional signal on its own",
    }


def weak_close(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any] | None:
    """The latest candle closed *off* its extreme against its own direction.

    A bullish candle that failed to hold its high (or a bearish candle that
    failed to hold its low) is a weak close — progress and body ratio are both
    reported so the caller can apply its own thresholds.
    """
    config = config or PriceActionConfig.from_settings()
    del config
    if not candles:
        return None
    c = candles[-1]
    rng = _f(c, "high") - _f(c, "low")
    if rng <= 0:
        return None
    progress = (_f(c, "close") - _f(c, "low")) / rng
    if is_bullish(c) and progress <= 0.5:
        weak_of = "bullish"
    elif is_bearish(c) and progress >= 0.5:
        weak_of = "bearish"
    else:
        return None
    return {
        "type": "weak_close",
        "direction": weak_of,
        "index": len(candles) - 1,
        "close_progress": progress,
        "note": "closed against the candle's own direction; observation only",
    }


def failed_continuation(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> dict[str, Any] | None:
    """A directional run ended because the *next* candle closed against it.

    Reported when a run of at least two candles is followed by a candle whose
    close is beyond the run's last close in the *opposite* direction. The run
    direction and reversal index are both reported; this is not a reversal
    claim, only a failed-continuation observation.
    """
    config = config or PriceActionConfig.from_settings()
    del config
    if len(candles) < 3:
        return None
    runs = directional_runs(candles[:-1])
    if not runs:
        return None
    run = runs[-1]
    if run.length < 2 or run.end != len(candles) - 2:
        return None
    last_run_close = _f(candles[run.end], "close")
    final = candles[-1]
    final_close = _f(final, "close")
    against = (run.direction == Direction.BULLISH and final_close < last_run_close) or (
        run.direction == Direction.BEARISH and final_close > last_run_close
    )
    if not against or sign(final) == 0:
        return None
    return {
        "type": "failed_continuation",
        "run_direction": run.direction,
        "run_length": run.length,
        "run_end_index": run.end,
        "reversal_index": len(candles) - 1,
        "note": "the run's continuation candle closed against the run; not a reversal claim",
    }


__all__ = [
    "PSYCH_TEMPLATES",
    "Run",
    "analyze_reference_sequences",
    "candle_progress",
    "consecutive_bearish",
    "consecutive_bullish",
    "directional_runs",
    "failed_continuation",
    "level_reaction",
    "lonely_candles",
    "psych_sequences",
    "run_count",
    "sign",
    "similar_sequences",
    "strong_close",
    "weak_close",
]
