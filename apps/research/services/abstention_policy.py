# apps/research/services/abstention_policy.py
"""Abstention policy (Step 13)."""

from __future__ import annotations

from typing import Any


class AbstentionPolicy:
    """Configurable abstention rules.

    Distinguish: strategy rejection, data-quality rejection,
    statistical uncertainty, expired opportunity.
    """

    def evaluate(
        self,
        strategy_result: dict[str, Any],
        data_quality_ok: bool = True,
        timing_valid: bool = True,
        model_trusted: bool = False,
        conflicts: bool = False,
    ) -> dict[str, Any]:
        reasons = []

        if not data_quality_ok:
            reasons.append("data_quality_rejection")
        if not timing_valid:
            reasons.append("expired_opportunity")
        if conflicts:
            reasons.append("strategy_rejection_conflict")
        if not model_trusted:
            reasons.append("statistical_uncertainty_uncalibrated")

        if strategy_result.get("direction") == "no_trade":
            reasons.append("strategy_rejection")

        should_abstain = len(reasons) > 0
        return {
            "should_abstain": should_abstain,
            "reasons": reasons,
            "recorded": True,
        }


__all__ = ["AbstentionPolicy"]
