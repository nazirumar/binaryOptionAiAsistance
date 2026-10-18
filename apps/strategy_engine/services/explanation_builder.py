# apps/strategy_engine/services/explanation_builder.py
"""Explanation generator (Step 12)."""

from __future__ import annotations

from typing import Any

from apps.strategy_engine.constants import EvaluationDirection


class ExplanationBuilder:
    """Build readable explanations from structured evidence."""

    def build_explanation(
        self,
        direction: str,
        strategy_family: str,
        supporting: list[dict[str, Any]],
        contradictory: list[dict[str, Any]],
        reason_codes: list[str],
        market_context: str,
    ) -> str:
        """Generate a clear, factual explanation."""
        parts = []

        if direction == EvaluationDirection.NO_TRADE:
            parts.append("No actionable setup qualifies for entry under the evaluation criteria.")
            if reason_codes:
                parts.append(f"Reasons: {', '.join(reason_codes)}.")
            if contradictory:
                parts.append("Strong contradictory evidence was present.")
            if not supporting:
                parts.append(
                    "Insufficient supporting evidence to justify a directional hypothesis."
                )
        else:
            direction_text = "bullish" if direction == EvaluationDirection.UP else "bearish"
            family_text = self._format_family(strategy_family)
            parts.append(f"A {direction_text} hypothesis is supported by {family_text} analysis.")

            if supporting:
                key_evidence = supporting[0].get("explanation", "")
                if key_evidence:
                    parts.append(f"Key evidence: {key_evidence}.")

            if contradictory:
                parts.append(
                    f"{len(contradictory)} contradictory item(s) were identified and considered."
                )

        parts.append(
            "This is a research hypothesis based on structured price-action evidence. "
            "No certainty is claimed and no numerical probability is assigned."
        )

        return " ".join(parts)

    def _format_family(self, family: str) -> str:
        mapping = {
            "sr_rejection": "support/resistance rejection",
            "breakout_retest": "breakout-retest (SBR/RBS)",
            "liquidity_sweep": "liquidity sweep and rejection",
            "combined": "combined strategy factors",
            "unknown": "general confluence",
        }
        return mapping.get(family, family)

    def explain_no_trade(self, reason_codes: list[str]) -> str:
        if reason_codes:
            return f"NO_TRADE: {', '.join(reason_codes)}. Setup does not meet mandatory conditions."
        return "NO_TRADE: Required conditions not satisfied. No fabricated probability assigned."


__all__ = ["ExplanationBuilder"]
