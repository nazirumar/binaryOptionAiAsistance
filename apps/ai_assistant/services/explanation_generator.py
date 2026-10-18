# ai_assistant/services/explanation_generator.py
"""Explanation generation (Steps 6/8).

Builds a structured explanation from deterministic engine outputs. The LLM
may rephrase but never invents observations, probabilities, prices or
outcomes. If the strategy engine returns NO TRADE, it is never converted to
UP or DOWN here.
"""

from __future__ import annotations

from typing import Any

VALID_DIRECTIONS = ("UP", "DOWN", "NO TRADE")


class ExplanationGenerator:
    def generate(self, evaluation: dict[str, Any]) -> dict[str, Any]:
        direction = str(evaluation.get("direction", "NO TRADE")).upper()
        if direction not in VALID_DIRECTIONS:
            direction = "NO TRADE"
        parts: list[str] = []
        parts.append(f"Direction: {direction}.")
        family = evaluation.get("strategy_family")
        if family:
            parts.append(f"Strategy family: {family}.")
        supporting = evaluation.get("supporting_evidence") or []
        contradictory = evaluation.get("contradictory_evidence") or []
        if supporting:
            parts.append(f"Supporting evidence ({len(supporting)} items).")
        if contradictory:
            parts.append(f"Contradictory evidence ({len(contradictory)} items).")
        reason = evaluation.get("primary_reason_code")
        if reason:
            parts.append(f"Primary reason: {reason}.")
        invalidation = evaluation.get("invalidation_conditions") or []
        if invalidation:
            parts.append("Invalidation conditions are listed in the report.")
        if evaluation.get("probability_status"):
            parts.append("Probability unavailable — model not calibrated.")
        return {
            "direction": direction,
            "explanation": " ".join(parts),
            "supporting_evidence": supporting,
            "contradictory_evidence": contradictory,
            "invalidation_conditions": invalidation,
            "warnings": evaluation.get("warnings", []),
        }

    def educational_answer(self, concept: str, observations: list[Any] | None = None) -> str:
        """Distinguish educational examples from actual market observations."""
        base = f"Educational explanation: {concept}."
        if observations:
            return base + " This references actual observations from your analysis."
        return base + " This is a general example, not an observation of your screenshot."


__all__ = ["ExplanationGenerator"]
