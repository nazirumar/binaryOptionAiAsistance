# apps/strategy_engine/services/bullish_evaluator.py
"""Bullish strategy evaluation (Strategy A, B, C)."""

from __future__ import annotations

from typing import Any

from apps.strategy_engine.constants import (
    CandidateStatus,
    EvaluationDirection,
    StrategyFamily,
)
from apps.strategy_engine.schemas.output import Candidate


class BullishEvaluator:
    """Evaluate bullish candidates."""

    def evaluate_all(
        self, evidence: list[dict[str, Any]], candles: list[dict[str, Any]]
    ) -> list[Candidate]:
        candidates = []
        candidates.extend(self._evaluate_sr_rejection(evidence))
        candidates.extend(self._evaluate_rbs(evidence))
        candidates.extend(self._evaluate_sweep(evidence))
        return candidates

    def _evaluate_sr_rejection(self, evidence: list[dict[str, Any]]) -> list[Candidate]:
        candidates = []
        # Look for support zone with rejection/bullish recovery
        has_support = any("sr.zone.support" in e.get("rule_id", "") for e in evidence)
        has_bullish_recovery = any(
            e.get("direction") == "bullish" and "rejection" in e.get("rule_id", "")
            for e in evidence
        ) or any(e.get("direction") == "bullish" for e in evidence if "bsf" in e.get("rule_id", ""))

        if has_support and has_bullish_recovery:
            supporting = [e for e in evidence if e.get("direction") == "bullish"]
            candidates.append(
                Candidate(
                    direction=EvaluationDirection.UP,
                    strategy_family=StrategyFamily.SUPPORT_RESISTANCE_REJECTION,
                    status=CandidateStatus.VALID,
                    supporting_evidence=supporting,
                    required_conditions=[
                        "established_support_zone",
                        "seller_failure_or_rejection",
                        "bullish_recovery",
                    ],
                    candle_refs=[],
                )
            )
        return candidates

    def _evaluate_rbs(self, evidence: list[dict[str, Any]]) -> list[Candidate]:
        candidates = []
        # Look for resistance became support (RBS) - bullish
        for ev in evidence:
            if "resistance_became_support" in ev.get("rule_id", ""):
                candidates.append(
                    Candidate(
                        direction=EvaluationDirection.UP,
                        strategy_family=StrategyFamily.BREAKOUT_RETEST_SBR_RBS,
                        status=CandidateStatus.VALID,
                        supporting_evidence=[ev],
                        required_conditions=["breakout_above_resistance", "retest_as_support"],
                        candle_refs=ev.get("candle_refs", []),
                    )
                )
        return candidates

    def _evaluate_sweep(self, evidence: list[dict[str, Any]]) -> list[Candidate]:
        candidates = []
        # Look for low sweep with bullish recovery
        for ev in evidence:
            rule_id = ev.get("rule_id", "")
            if "sweep" in rule_id:
                # Check if it's a low sweep (bearish sweep type but recovery bullish?)
                # Or look for low sweep with rejection outcome
                metrics = ev.get("metrics", {}) or {}
                if metrics.get("outcome") == "rejection" or ev.get("direction") == "bullish":
                    candidates.append(
                        Candidate(
                            direction=EvaluationDirection.UP,
                            strategy_family=StrategyFamily.LIQUIDITY_SWEEP_REJECTION,
                            status=CandidateStatus.VALID,
                            supporting_evidence=[ev],
                            required_conditions=[
                                "sweep_below_prior_low",
                                "recovery_above_swept_level",
                            ],
                            candle_refs=ev.get("candle_refs", []),
                        )
                    )
        return candidates


__all__ = ["BullishEvaluator"]
