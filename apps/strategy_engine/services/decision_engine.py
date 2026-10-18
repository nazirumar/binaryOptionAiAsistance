# apps/strategy_engine/services/decision_engine.py
"""Decision engine (Step 11)."""

from __future__ import annotations

import uuid
from typing import Any

from django.utils import timezone

from apps.strategy_engine.constants import (
    EvaluationDirection,
    InvalidationReasonCode,
    ProbabilityStatus,
    StrategyFamily,
)
from apps.strategy_engine.schemas.output import Candidate, EvaluationOutput


class DecisionEngine:
    """Make final decision: UP/DOWN/NO_TRADE."""

    def decide(
        self,
        strategy_input,
        market_context: str,
        candidates: list[Candidate],
        contradictions: list[dict[str, Any]],
        invalidation_should_no_trade: bool,
        reason_codes: list[str],
        timing_validity: str,
        timing_info: dict[str, Any],
        confluence_score: float | None = None,
    ) -> EvaluationOutput:
        """Make the final decision."""
        evaluation_id = str(uuid.uuid4())

        # If forced no-trade by invalidation
        if invalidation_should_no_trade:
            primary = reason_codes[0] if reason_codes else InvalidationReasonCode.NO_CANDIDATES
            return self._build_no_trade(
                evaluation_id,
                strategy_input,
                market_context,
                candidates,
                reason_codes,
                primary,
                timing_validity,
                timing_info,
                confluence_score,
            )

        # If contradictions are strong
        if contradictions:
            return self._build_no_trade(
                evaluation_id,
                strategy_input,
                market_context,
                candidates,
                [InvalidationReasonCode.STRONG_CONTRADICTION, *reason_codes],
                InvalidationReasonCode.STRONG_CONTRADICTION,
                timing_validity,
                timing_info,
                confluence_score,
            )

        # Evaluate candidates
        valid_candidates = [c for c in candidates if c.status == "valid"]
        if not valid_candidates:
            return self._build_no_trade(
                evaluation_id,
                strategy_input,
                market_context,
                candidates,
                [InvalidationReasonCode.NO_CANDIDATES],
                InvalidationReasonCode.NO_CANDIDATES,
                timing_validity,
                timing_info,
                confluence_score,
            )

        # Pick best candidate (simple: first valid)
        best = valid_candidates[0]

        return EvaluationOutput(
            evaluation_id=evaluation_id,
            instrument=strategy_input.instrument,
            timeframe=strategy_input.timeframe,
            market_type=strategy_input.market_type,
            target_candle_interval=strategy_input.timeframe,
            direction=best.direction,
            strategy_family=best.strategy_family,
            market_context=market_context,
            candidates=candidates,
            supporting_evidence=best.supporting_evidence,
            contradictory_evidence=best.contradictory_evidence,
            invalidation_conditions=best.invalidation_conditions,
            primary_reason_code="",
            reason_codes=[],
            sync_status=strategy_input.sync_status,
            feed_compatibility="",
            timing_validity=timing_validity,
            data_quality="",
            data_freshness=strategy_input.data_freshness,
            confluence_score=confluence_score,
            statistical_probability_status=ProbabilityStatus.UNAVAILABLE_UNCALIBRATED,
            explanation="",
            warnings=list(strategy_input.warnings),
            created_at=timezone.now(),
            signal_candle_open_time=timing_info.get("signal_candle_open_time"),
            signal_candle_close_time=timing_info.get("signal_candle_close_time"),
            target_candle_open_time=timing_info.get("target_candle_open_time"),
            target_candle_close_time=timing_info.get("target_candle_close_time"),
        )

    def _build_no_trade(
        self,
        evaluation_id: str,
        strategy_input,
        market_context: str,
        candidates: list[Candidate],
        reason_codes: list[str],
        primary_reason: str,
        timing_validity: str,
        timing_info: dict[str, Any],
        confluence_score: float | None = None,
    ) -> EvaluationOutput:
        return EvaluationOutput(
            evaluation_id=evaluation_id,
            instrument=strategy_input.instrument,
            timeframe=strategy_input.timeframe,
            market_type=strategy_input.market_type,
            target_candle_interval=strategy_input.timeframe,
            direction=EvaluationDirection.NO_TRADE,
            strategy_family=candidates[0].strategy_family if candidates else StrategyFamily.UNKNOWN,
            market_context=market_context,
            candidates=candidates,
            supporting_evidence=[],
            contradictory_evidence=[],
            invalidation_conditions=[],
            primary_reason_code=primary_reason,
            reason_codes=reason_codes,
            sync_status=strategy_input.sync_status,
            feed_compatibility="",
            timing_validity=timing_validity,
            data_quality="",
            data_freshness=strategy_input.data_freshness,
            confluence_score=confluence_score,
            statistical_probability_status=ProbabilityStatus.UNAVAILABLE_UNCALIBRATED,
            explanation="",
            warnings=list(strategy_input.warnings),
            created_at=timezone.now(),
            signal_candle_open_time=timing_info.get("signal_candle_open_time"),
            signal_candle_close_time=timing_info.get("signal_candle_close_time"),
            target_candle_open_time=timing_info.get("target_candle_open_time"),
            target_candle_close_time=timing_info.get("target_candle_close_time"),
        )


__all__ = ["DecisionEngine"]
