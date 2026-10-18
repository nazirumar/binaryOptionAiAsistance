# apps/strategy_engine/services/confluence_engine.py
"""Evidence dependency and confluence (Step 7)."""

from __future__ import annotations

from typing import Any


class ConfluenceEngine:
    """Track evidence dependencies and compute confluence scores.

    Scores are experimental and must NOT be displayed as probabilities.
    """

    # Correlated evidence groups - to avoid double-counting
    CORRELATED_GROUPS = [
        # Engulfing + body strength
        {
            "keys": ["pa.candle.bullish_engulfing", "pa.candle.bearish_engulfing"],
            "group": "engulfing",
        },
        # Sweep + wick rejection
        {"group": "sweep_rejection"},
        # SBR/RBS + breakout-retest
        {"group": "sbr_rbs_breakout"},
        # Cycle reversal + BSF
        {"group": "cycle_bsf"},
    ]

    def compute_confluence(self, supporting: list[dict[str, Any]]) -> float | None:
        """Compute configurable confluence score (0-1 range conceptually).
        Must not be presented as probability.
        """
        if not supporting:
            return 0.0

        # Deduplicate correlated evidence
        unique_groups = self._deduplicate_correlated(supporting)

        # Simple scoring: more independent evidence = higher confluence
        base_score = min(len(unique_groups) / 5.0, 1.0)  # Cap at 1.0, not a probability
        return round(base_score, 3)

    def _deduplicate_correlated(self, evidence: list[dict[str, Any]]) -> list[str]:
        groups = set()
        for ev in evidence:
            rule_id = ev.get("rule_id", "")
            detector = ev.get("detector", "")

            # Classify into independent groups
            if "structure" in rule_id:
                groups.add("structure")
            elif "sr" in rule_id:
                groups.add("sr")
            elif "bsf" in rule_id or "buyer_seller" in detector:
                groups.add("bsf")
            elif "sweep" in rule_id:
                groups.add("sweep")
            elif "ob" in rule_id:
                groups.add("ob")
            elif "fvg" in rule_id:
                groups.add("fvg")
            elif "gap" in rule_id:
                groups.add("gap")
            elif "volume" in rule_id:
                groups.add("volume")
            elif "sequence" in rule_id:
                groups.add("sequence")
            elif "candle" in rule_id:
                groups.add("pattern")
            elif "cycle" in rule_id:
                groups.add("cycle")
            else:
                groups.add(rule_id)

        return sorted(groups)

    def is_correlated(self, ev1: dict[str, Any], ev2: dict[str, Any]) -> bool:
        """Check if two evidence items are correlated."""
        r1 = ev1.get("rule_id", "")
        r2 = ev2.get("rule_id", "")

        # Engulfing patterns
        if "engulfing" in r1 and "engulfing" in r2:
            return True
        # Sweep + rejection
        if ("sweep" in r1 and "rejection" in r2) or ("rejection" in r1 and "sweep" in r2):
            return True
        # SBR/RBS and breakout/retest related
        if (
            ("sbr_rbs" in r1 or "breakout" in r1)
            and ("sbr_rbs" in r2 or "breakout" in r2)
            and "sr" in r1
            and "sr" in r2
        ):
            return True

        return False


__all__ = ["ConfluenceEngine"]
