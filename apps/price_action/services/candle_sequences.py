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
from apps.price_action.services.candle_math import is_bearish, is_bullish
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


__all__ = [
    "PSYCH_TEMPLATES",
    "Run",
    "analyze_reference_sequences",
    "consecutive_bearish",
    "consecutive_bullish",
    "directional_runs",
    "level_reaction",
    "lonely_candles",
    "psych_sequences",
    "sign",
    "similar_sequences",
]
