# apps/strategy_engine/services/context_evaluator.py
"""Market context evaluation (Step 4)."""

from __future__ import annotations

from typing import Any

from apps.strategy_engine.constants import MarketContextState


class ContextEvaluator:
    """Evaluate market context classification."""

    def evaluate(self, evidence: list[dict[str, Any]], context: dict[str, Any]) -> str:
        """Classify market context.

        Returns one of: bullish_trend, bearish_trend, range, transition, uncertain.
        """
        pa_context = context or {}

        # Check consolidation
        consolidation = pa_context.get("consolidation")
        if consolidation:
            return MarketContextState.RANGE

        # Check market structure from evidence
        structure_trend = self._extract_structure_trend(evidence)
        if structure_trend == "uptrend":
            return MarketContextState.BULLISH_TREND
        if structure_trend == "downtrend":
            return MarketContextState.BEARISH_TREND

        # Check BOS/failed breakouts indicating transition
        if self._has_structure_breaks(evidence):
            return MarketContextState.TRANSITION

        # Check regime
        regime = pa_context.get("regime", "")
        if regime == "trending":
            # Try to infer direction from other evidence
            return MarketContextState.TRANSITION
        if regime == "ranging":
            return MarketContextState.RANGE

        return MarketContextState.UNCERTAIN

    def _extract_structure_trend(self, evidence: list[dict[str, Any]]) -> str:
        for ev in evidence:
            if (
                ev.get("detector") == "market_structure"
                and ev.get("rule_id") == "pa.structure.trend"
            ):
                exp = ev.get("explanation", "").lower()
                if "uptrend" in exp:
                    return "uptrend"
                if "downtrend" in exp:
                    return "downtrend"
                metrics = ev.get("metrics", {}) or {}
                if metrics.get("trend") in ("uptrend", "downtrend"):
                    return str(metrics["trend"])
        return "unclear"

    def _has_structure_breaks(self, evidence: list[dict[str, Any]]) -> bool:
        for ev in evidence:
            rule_id = ev.get("rule_id", "")
            if rule_id.startswith("pa.structure.break") or rule_id.startswith(
                "pa.structure.failed_breakout"
            ):
                return True
        return False

    def is_compatible_bullish(self, context: str) -> bool:
        return context in (MarketContextState.BULLISH_TREND, MarketContextState.TRANSITION)

    def is_compatible_bearish(self, context: str) -> bool:
        return context in (MarketContextState.BEARISH_TREND, MarketContextState.TRANSITION)


__all__ = ["ContextEvaluator"]
