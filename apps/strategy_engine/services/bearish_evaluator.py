# apps/strategy_engine/services/bearish_evaluator.py
"""Bearish strategy evaluation (Strategy A, B, C)."""

from __future__ import annotations

from typing import Any

from apps.strategy_engine.constants import (
    CandidateStatus,
    EvaluationDirection,
    StrategyFamily,
)
from apps.strategy_engine.schemas.output import Candidate


class BearishEvaluator:
    """Evaluate bearish candidates."""

    def evaluate_all(
        self, evidence: list[dict[str, Any]], candles: list[dict[str, Any]]
    ) -> list[Candidate]:
        candidates = []
        candidates.extend(self._evaluate_sr_rejection(evidence))
        candidates.extend(self._evaluate_sbr(evidence))
        candidates.extend(self._evaluate_sweep(evidence))
        return candidates

    def _evaluate_sr_rejection(self, evidence: list[dict[str, Any]]) -> list[Candidate]:
        candidates = []
        has_resistance = any("sr.zone.resistance" in e.get("rule_id", "") for e in evidence)
        has_bearish_recovery = any(
            e.get("direction") == "bearish" and "rejection" in e.get("rule_id", "")
            for e in evidence
        ) or any(e.get("direction") == "bearish" for e in evidence if "bsf" in e.get("rule_id", ""))

        if has_resistance and has_bearish_recovery:
            supporting = [e for e in evidence if e.get("direction") == "bearish"]
            candidates.append(
                Candidate(
                    direction=EvaluationDirection.DOWN,
                    strategy_family=StrategyFamily.SUPPORT_RESISTANCE_REJECTION,
                    status=CandidateStatus.VALID,
                    supporting_evidence=supporting,
                    required_conditions=[
                        "established_resistance_zone",
                        "buyer_failure_or_rejection",
                        "bearish_recovery",
                    ],
                    candle_refs=[],
                )
            )
        return candidates

    def _evaluate_sbr(self, evidence: list[dict[str, Any]]) -> list[Candidate]:
        candidates = []
        for ev in evidence:
            if "support_became_resistance" in ev.get("rule_id", ""):
                candidates.append(
                    Candidate(
                        direction=EvaluationDirection.DOWN,
                        strategy_family=StrategyFamily.BREAKOUT_RETEST_SBR_RBS,
                        status=CandidateStatus.VALID,
                        supporting_evidence=[ev],
                        required_conditions=["breakout_below_support", "retest_as_resistance"],
                        candle_refs=ev.get("candle_refs", []),
                    )
                )
        return candidates

    def _evaluate_sweep(self, evidence: list[dict[str, Any]]) -> list[Candidate]:
        candidates = []
        for ev in evidence:
            rule_id = ev.get("rule_id", "")
            if "sweep" in rule_id:
                metrics = ev.get("metrics", {}) or {}
                # High sweep bearish
                if metrics.get("outcome") == "rejection" or ev.get("direction") == "bearish":
                    candidates.append(
                        Candidate(
                            direction=EvaluationDirection.DOWN,
                            strategy_family=StrategyFamily.LIQUIDITY_SWEEP_REJECTION,
                            status=CandidateStatus.VALID,
                            supporting_evidence=[ev],
                            required_conditions=[
                                "sweep_above_prior_high",
                                "rejection_below_swept_level",
                            ],
                            candle_refs=ev.get("candle_refs", []),
                        )
                    )
        return candidates


__all__ = ["BearishEvaluator"]
