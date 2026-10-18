# ai_assistant/services/evidence_retriever.py
"""Evidence retrieval (Step 9).

Retrieves the original analysis evidence before answering follow-up
questions. Never reconstructs historical facts from conversational memory
alone.
"""

from __future__ import annotations

from typing import Any

from apps.strategy_engine.models import StrategyEvaluation


class EvidenceRetriever:
    def retrieve(self, evaluation: StrategyEvaluation | None) -> dict[str, Any]:
        if evaluation is None:
            return {"available": False, "note": "no linked strategy evaluation"}
        return {
            "available": True,
            "evaluation_id": evaluation.evaluation_id,
            "instrument": evaluation.instrument,
            "timeframe": evaluation.timeframe,
            "market_type": evaluation.market_type,
            "direction": evaluation.direction,
            "strategy_family": evaluation.strategy_family,
            "market_context": evaluation.market_context,
            "supporting_evidence": (evaluation.output_snapshot or {}).get(
                "supporting_evidence", []
            ),
            "contradictory_evidence": (evaluation.output_snapshot or {}).get(
                "contradictory_evidence", []
            ),
            "invalidation_conditions": evaluation.invalidation_conditions,
            "reason_codes": evaluation.reason_codes,
            "primary_reason_code": evaluation.primary_reason_code,
            "probability_status": evaluation.probability_status,
        }

    def find_support_zone(self, evaluation: StrategyEvaluation | None) -> Any:
        if evaluation is None:
            return None
        for ev in (evaluation.output_snapshot or {}).get("supporting_evidence", []):
            if "sr.zone.support" in str(ev.get("rule_id", "")):
                return ev
        return None


__all__ = ["EvidenceRetriever"]
