# apps/strategy_engine/services/evaluation_service.py
"""Main evaluation service orchestrator (Step 14)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from apps.price_action.services.engine import PriceActionEngine
from apps.strategy_engine.constants import ProbabilityStatus
from apps.strategy_engine.schemas.input import build_strategy_input
from apps.strategy_engine.services.bearish_evaluator import BearishEvaluator
from apps.strategy_engine.services.bullish_evaluator import BullishEvaluator
from apps.strategy_engine.services.conflict_resolver import ConflictResolver
from apps.strategy_engine.services.confluence_engine import ConfluenceEngine
from apps.strategy_engine.services.context_evaluator import ContextEvaluator
from apps.strategy_engine.services.decision_engine import DecisionEngine
from apps.strategy_engine.services.explanation_builder import ExplanationBuilder
from apps.strategy_engine.services.invalidation_engine import InvalidationEngine
from apps.strategy_engine.services.setup_classifier import SetupClassifier
from apps.strategy_engine.services.timing_validator import TimingValidator

logger = logging.getLogger(__name__)


class EvaluationService:
    """Orchestrates the full strategy evaluation."""

    def __init__(self, price_action_engine: PriceActionEngine | None = None) -> None:
        self.pa_engine = price_action_engine or PriceActionEngine()
        self.context_evaluator = ContextEvaluator()
        self.setup_classifier = SetupClassifier()
        self.bullish_evaluator = BullishEvaluator()
        self.bearish_evaluator = BearishEvaluator()
        self.confluence_engine = ConfluenceEngine()
        self.conflict_resolver = ConflictResolver()
        self.invalidation_engine = InvalidationEngine()
        self.timing_validator = TimingValidator()
        self.decision_engine = DecisionEngine()
        self.explanation_builder = ExplanationBuilder()

    def evaluate(
        self, input_data: dict[str, Any], *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Evaluate strategy and return dict output."""
        from django.utils import timezone

        evaluation_ts = now or timezone.now()

        # Build strategy input
        strategy_input = build_strategy_input(input_data, evaluation_timestamp=evaluation_ts)

        # Get price action result if not provided
        pa_result = strategy_input.price_action_result
        if not pa_result:
            # Try to run PA engine if candles provided
            if strategy_input.completed_candles:
                try:
                    pa_result = self.pa_engine.run(
                        {
                            "candles": list(strategy_input.completed_candles),
                            "instrument": strategy_input.instrument,
                            "timeframe": strategy_input.timeframe,
                        },
                        now=evaluation_ts,
                    )
                except Exception:
                    pa_result = {"evidence": [], "conflicts": [], "context": {}}

        # Extract
        evidence = pa_result.get("evidence", []) if pa_result else strategy_input.evidence
        pa_result.get("conflicts", []) if pa_result else strategy_input.conflicts
        pa_context = pa_result.get("context", {}) if pa_result else strategy_input.context

        # Evaluate market context
        market_context = self.context_evaluator.evaluate(evidence, pa_context)

        # Classify strategies
        _ = self.setup_classifier.classify_strategies(evidence)

        # Evaluate candidates
        candles = list(strategy_input.completed_candles)
        has_unfinished = any(self.timing_validator.is_candle_unfinished(c) for c in candles)
        bullish_cands = self.bullish_evaluator.evaluate_all(evidence, candles)
        bearish_cands = self.bearish_evaluator.evaluate_all(evidence, candles)
        all_candidates = bullish_cands + bearish_cands

        # Phase 13: book strategies may contribute an EXTRA candidate, but
        # only for rows with explicit decision_use_approved (see
        # book_strategies.services.decision_integration). In default
        # deployments nothing is approved, so this is inert; a failure here
        # degrades to "no book candidates" and every NO TRADE safeguard below
        # still applies unchanged.
        try:
            from apps.book_strategies.services.decision_integration import (
                book_strategy_candidates,
            )

            all_candidates.extend(
                book_strategy_candidates(
                    candles,
                    last_candle_forming=has_unfinished,
                    instrument=str(strategy_input.instrument or ""),
                    timeframe=str(strategy_input.timeframe or ""),
                    market_type=str(strategy_input.market_type or ""),
                )
            )
        except Exception:
            logger.warning("book strategy candidate evaluation skipped", exc_info=True)

        # Confluence
        supporting_all = []
        for c in all_candidates:
            supporting_all.extend(c.supporting_evidence)
        confluence_score = self.confluence_engine.compute_confluence(supporting_all)

        # Conflicts/contradictions
        contradictions = self.conflict_resolver.identify_strong_contradictions(evidence)

        # Timing
        timing_validity, timing_info = self.timing_validator.validate_timing(
            candles, strategy_input.timeframe, evaluation_ts
        )

        # Invalidation
        should_no_trade_inv, reason_codes_inv, primary_inv = self.invalidation_engine.check_all(
            strategy_input,
            timing_validity,
            has_unfinished_candle=has_unfinished,
            is_stale=False,
        )
        all_reason_codes = list(reason_codes_inv)

        # Decide
        decision = self.decision_engine.decide(
            strategy_input,
            market_context,
            all_candidates,
            contradictions,
            should_no_trade_inv,
            all_reason_codes,
            timing_validity,
            timing_info,
            confluence_score=confluence_score,
        )

        # Build explanation
        explanation = self.explanation_builder.build_explanation(
            decision.direction,
            decision.strategy_family,
            decision.supporting_evidence,
            decision.contradictory_evidence,
            decision.reason_codes or all_reason_codes,
            decision.market_context,
        )
        decision_dict = decision.to_dict()
        decision_dict["explanation"] = explanation
        if not decision_dict["reason_codes"] and all_reason_codes:
            decision_dict["reason_codes"] = all_reason_codes
        if not decision_dict["primary_reason_code"] and primary_inv:
            decision_dict["primary_reason_code"] = primary_inv
        decision_dict["statistical_probability_status"] = ProbabilityStatus.UNAVAILABLE_UNCALIBRATED

        return decision_dict

    def evaluate_and_persist(
        self,
        input_data: dict[str, Any],
        owner=None,
        now: datetime | None = None,
    ):
        """Evaluate and persist to database."""
        result = self.evaluate(input_data, now=now)
        # For now, return result without persisting complex relations (can be enhanced)
        from apps.strategy_engine.models import StrategyEvaluation

        evaluation = StrategyEvaluation(
            owner=owner,
            evaluation_id=result.get("evaluation_id", ""),
            instrument=result.get("instrument", ""),
            timeframe=result.get("timeframe", ""),
            market_type=result.get("market_type", ""),
            direction=result.get("direction", ""),
            strategy_family=result.get("strategy_family", ""),
            market_context=result.get("market_context", ""),
            status="valid" if result.get("direction") in ("up", "down") else "rejected",
            explanation=result.get("explanation", ""),
            warnings=result.get("warnings", []),
            invalidation_conditions=result.get("invalidation_conditions", []),
            reason_codes=result.get("reason_codes", []),
            primary_reason_code=result.get("primary_reason_code", ""),
            timing_validity=result.get("timing_validity", ""),
            probability_status=result.get("statistical_probability_status", ""),
            sync_status=result.get("sync_status", ""),
            feed_compatibility=result.get("feed_compatibility", ""),
            data_quality=result.get("data_quality", ""),
            data_freshness=result.get("data_freshness", ""),
            confluence_score=result.get("confluence_score"),
            schema_version=result.get("schema_version", ""),
            engine_config_version=result.get("engine_config_version", ""),
            rule_version=result.get("rule_version", ""),
            input_snapshot=input_data,
            output_snapshot=result,
            signal_candle_open_time=self._parse_dt(result.get("signal_candle_open_time")),
            signal_candle_close_time=self._parse_dt(result.get("signal_candle_close_time")),
            target_candle_open_time=self._parse_dt(result.get("target_candle_open_time")),
            target_candle_close_time=self._parse_dt(result.get("target_candle_close_time")),
            analysis_completion_time=__import__("django.utils.timezone").utils.timezone.now(),
        )
        evaluation.save()
        return evaluation, result

    def _parse_dt(self, val):
        """Parse a stored engine timestamp, keeping it UTC-aware.

        Phase 11 CP5: naive/ambiguous values are rejected (``None``) instead
        of being stripped of their offset and persisted as naive datetimes.
        """
        from apps.core.timeutils import parse_iso_datetime

        if not val:
            return None
        if isinstance(val, datetime):
            from apps.core.timeutils import ensure_utc

            return ensure_utc(val)
        return parse_iso_datetime(val)


__all__ = ["EvaluationService"]
