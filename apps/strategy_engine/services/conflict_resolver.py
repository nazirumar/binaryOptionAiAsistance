# apps/strategy_engine/services/conflict_resolver.py
"""Conflict resolution (Step 8-9)."""

from __future__ import annotations

from typing import Any

from apps.strategy_engine.constants import InvalidationReasonCode


class ConflictResolver:
    """Handle conflicting evidence."""

    def identify_strong_contradictions(
        self, evidence: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Identify strong contradictory evidence."""
        bullish = [e for e in evidence if e.get("direction") == "bullish"]
        bearish = [e for e in evidence if e.get("direction") == "bearish"]
        contradictions = []

        if bullish and bearish:
            contradictions.append(
                {
                    "type": "opposing_evidence",
                    "explanation": "Both bullish and bearish directional evidence present",
                    "bullish_count": len(bullish),
                    "bearish_count": len(bearish),
                }
            )
        return contradictions

    def has_strong_contradiction(self, contradictions: list[dict[str, Any]]) -> bool:
        return len(contradictions) > 0

    def get_no_trade_reason_if_conflicted(self, contradictions: list[dict[str, Any]]) -> str | None:
        if contradictions:
            return InvalidationReasonCode.STRONG_CONTRADICTION
        return None


__all__ = ["ConflictResolver"]
