# apps/strategy_engine/services/setup_classifier.py
"""Setup classification (Step 5)."""

from __future__ import annotations

from typing import Any

from apps.strategy_engine.constants import StrategyFamily


class SetupClassifier:
    """Classify which strategy families are applicable."""

    def classify_strategies(self, evidence: list[dict[str, Any]]) -> list[str]:
        families = set()

        # Check for S/R related
        for ev in evidence:
            rule_id = ev.get("rule_id", "")
            if "sr" in rule_id:
                families.add(StrategyFamily.SUPPORT_RESISTANCE_REJECTION)
            if "sbr_rbs" in rule_id or "breakout" in rule_id:
                families.add(StrategyFamily.BREAKOUT_RETEST_SBR_RBS)
            if "sweep" in rule_id:
                families.add(StrategyFamily.LIQUIDITY_SWEEP_REJECTION)
            if "ob" in rule_id or "fvg" in rule_id:
                # Contributes to confluence
                pass

        if not families:
            # Default to combined if any evidence exists
            if evidence:
                families.add(StrategyFamily.COMBINED)
            else:
                families.add(StrategyFamily.UNKNOWN)

        return sorted(families)


__all__ = ["SetupClassifier"]
