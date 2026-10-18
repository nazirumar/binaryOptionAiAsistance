# ai_assistant/services/analysis_orchestrator.py
"""Screenshot analysis workflow orchestration (Step 4).

Pipeline: validate image -> vision -> instrument/timeframe -> MT5 data ->
feed compatibility -> price-action engine -> strategy evaluation ->
mandatory NO TRADE conditions -> probability retrieval -> explanation ->
persist. Expensive work is delegated to background tasks (tasks.py).
"""

from __future__ import annotations

import logging
from typing import Any

from apps.ai_assistant.models import AIAnalysisSession
from apps.ai_assistant.services.evidence_retriever import EvidenceRetriever
from apps.ai_assistant.services.explanation_generator import ExplanationGenerator
from apps.ai_assistant.services.probability_presenter import (
    PROBABILITY_UNAVAILABLE_MESSAGE,
    ProbabilityPresenter,
)
from apps.ai_assistant.services.response_validator import ResponseValidator
from apps.ai_assistant.services.safety_validator import SafetyValidator
from apps.strategy_engine.services.evaluation_service import EvaluationService

logger = logging.getLogger("apps.ai_assistant")

ALLOWED_IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


class AnalysisOrchestrator:
    def __init__(self) -> None:
        self.safety = SafetyValidator()
        self.evidence = EvidenceRetriever()
        self.explainer = ExplanationGenerator()
        self.probability = ProbabilityPresenter()
        self.validator = ResponseValidator()
        self.evaluation_service = EvaluationService()

    def validate_upload(self, content_type: str, size: int) -> dict[str, Any]:
        if content_type not in ALLOWED_IMAGE_TYPES:
            return {"ok": False, "error": "unsupported_image_type"}
        if size <= 0 or size > MAX_UPLOAD_BYTES:
            return {"ok": False, "error": "invalid_image_size"}
        return {"ok": True}

    def run(
        self,
        conversation,
        screenshot=None,
        evaluation_input: dict[str, Any] | None = None,
        approved_model: dict[str, Any] | None = None,
        educational: bool = False,
    ) -> dict[str, Any]:
        """Run the deterministic pipeline and produce a structured response."""
        warnings: list[str] = []

        # Step 6/15: OTC / feed compatibility guard.
        market_type = str((evaluation_input or {}).get("market_type", "")).upper()
        sync_status = str((evaluation_input or {}).get("sync_status", ""))
        # Case-insensitive on purpose: the builder persists the server token
        # ``verified_alignment`` while legacy inputs used the display casing.
        # Only a genuine VERIFIED_ALIGNMENT (whatever the casing) opens this
        # gate; the engine re-checks it independently below (double gate).
        if market_type == "OTC" and sync_status.strip().upper() != "VERIFIED_ALIGNMENT":
            warnings.append("otc_feed_incompatible")
            return self._no_trade_response(
                conversation,
                evaluation_input or {},
                warnings=warnings,
                primary_reason="otc_feed_incompatible",
                educational=educational,
            )

        # Step 14: timing validation / expired opportunity.
        timing_validity = str((evaluation_input or {}).get("timing_validity", "")).lower()
        if timing_validity == "expired":
            warnings.append("opportunity_expired")
            return self._no_trade_response(
                conversation,
                evaluation_input or {},
                warnings=warnings,
                primary_reason="opportunity_expired",
                educational=educational,
            )

        # Steps 7-10: deterministic engines.
        evaluation: dict[str, Any] = {}
        if evaluation_input:
            try:
                if conversation is not None:
                    strategy_evaluation, evaluation = self.evaluation_service.evaluate_and_persist(
                        evaluation_input, owner=conversation.owner
                    )
                    conversation.strategy_evaluation = strategy_evaluation
                    conversation.save(update_fields=["strategy_evaluation", "updated_at"])
                else:
                    evaluation = self.evaluation_service.evaluate(evaluation_input)
            except Exception:  # pragma: no cover - defensive
                logger.exception("strategy evaluation failed")
                warnings.append("strategy_evaluation_failed")
                evaluation = {}

        engine_direction = str(evaluation.get("direction", "NO TRADE"))
        explanation = self.explainer.generate(evaluation)

        # Step 16: probability only from an approved, validated model that is
        # compatible with this instrument/timeframe (CP6 strictness).
        probability = self.probability.present(
            approved_model,
            context={
                "instrument": str(
                    evaluation.get("instrument") or (evaluation_input or {}).get("instrument", "")
                ),
                "timeframe": str(
                    evaluation.get("timeframe") or (evaluation_input or {}).get("timeframe", "")
                ),
            },
        )
        if educational:
            warnings.append("educational_mode_no_actionable_prediction")

        response: dict[str, Any] = {
            "conversation_id": conversation.pk if conversation else None,
            "analysis_id": None,
            "instrument": evaluation.get("instrument", ""),
            "timeframe": evaluation.get("timeframe", ""),
            "market_type": evaluation.get("market_type", market_type.lower()),
            "screenshot_timestamp": None,
            "mt5_verification_status": evaluation.get("sync_status", "unavailable"),
            "market_context": evaluation.get("market_context", ""),
            "strategy_family": evaluation.get("strategy_family", ""),
            "direction": engine_direction.upper()
            if engine_direction.upper() in ("UP", "DOWN")
            else "NO TRADE",
            "supporting_evidence": explanation["supporting_evidence"],
            "contradictory_evidence": explanation["contradictory_evidence"],
            "invalidation_conditions": explanation["invalidation_conditions"],
            "target_candle_interval": evaluation.get("target_candle_interval", {}),
            "timing_validity": evaluation.get("timing_validity", ""),
            "probability_value": probability.get("value"),
            "probability_type": (
                "next_candle_directional" if probability.get("available") else None
            ),
            "calibration_status": (
                "calibrated" if probability.get("available") else "uncalibrated"
            ),
            "explanation": explanation["explanation"],
            "primary_reason_code": evaluation.get("primary_reason_code", ""),
            "reason_codes": list(evaluation.get("reason_codes", [])),
            "warnings": warnings + list(explanation.get("warnings", [])),
            "follow_up_suggestions": [
                "Why did you return this direction?",
                "What evidence is missing?",
                "Is the probability calibrated?",
            ],
        }
        # CP9-J: when no approved compatible model exists, the reader always
        # sees the exact calibration notice (never a number, never silence).
        if not probability.get("available") and PROBABILITY_UNAVAILABLE_MESSAGE not in str(
            response.get("explanation", "")
        ):
            response["explanation"] = (
                f"{str(response.get('explanation', '')).rstrip()} {PROBABILITY_UNAVAILABLE_MESSAGE}"
            ).strip()

        validation = self.validator.validate(response, engine_direction=engine_direction)
        response["validation_errors"] = validation["errors"]

        # CP7: educational mode never presents a trade assessment. Overrides
        # are applied AFTER validation so the validator still checks the raw
        # engine output, and the persisted schema records the educational
        # form of the response.
        if educational:
            response["direction"] = "EDUCATIONAL"
            response["explanation"] = self._educational_explanation(evaluation, explanation)
            response["probability_value"] = None
            response["probability_type"] = None
            response["calibration_status"] = "not_applicable_educational"
            response["follow_up_suggestions"] = [
                "Explain the detected patterns in more detail.",
                "What is support/resistance in this chart?",
                "Explain buyer/seller failure here.",
            ]

        response["analysis_id"] = self._persist_session(
            conversation, screenshot, response, warnings, status="completed"
        )
        return response

    @staticmethod
    def _educational_explanation(evaluation: dict[str, Any], explanation: dict[str, Any]) -> str:
        """Observations and course concepts — no prediction, ever.

        The text is built only from engine observations (market structure,
        detected evidence, contradictory evidence, invalidation conditions).
        It never states a next-candle direction and never carries a
        probability.
        """

        def _ev_text(item: Any) -> str:
            if isinstance(item, dict):
                return str(
                    item.get("description") or item.get("summary") or item.get("rule_id") or item
                )[:160]
            return str(item)[:160]

        parts = [
            "Educational analysis: observations and course concepts only — "
            "this is not a trade assessment and contains no prediction."
        ]
        context = str(evaluation.get("market_context") or "")
        if context:
            parts.append(f"Market structure observed: {context}.")
        supporting = list(explanation.get("supporting_evidence") or [])
        if supporting:
            listed = "; ".join(_ev_text(item) for item in supporting[:5])
            parts.append(f"Detected observations ({len(supporting)}): {listed}.")
        contradictory = list(explanation.get("contradictory_evidence") or [])
        if contradictory:
            listed = "; ".join(_ev_text(item) for item in contradictory[:5])
            parts.append(f"Contradictory evidence to weigh ({len(contradictory)}): {listed}.")
        invalidation = list(explanation.get("invalidation_conditions") or [])
        if invalidation:
            parts.append(
                "Concept: setups are invalidated by unfinished candles, stale "
                "data or an expired entry window — watch for those conditions."
            )
        parts.append(
            "Course concept: support turns to resistance after a decisive break "
            "(RBS), and resistance turns to support (SBR); liquidity sweeps "
            "often precede reversals. Hypothetical example only — not a "
            "forecast of this market."
        )
        return " ".join(parts)

    def _persist_session(
        self,
        conversation,
        screenshot,
        response: dict[str, Any],
        warnings: list[str],
        status: str = "completed",
        error: str = "",
    ) -> int | None:
        """Persist an AIAnalysisSession so follow-ups can retrieve evidence."""
        if conversation is None:
            return None
        session = AIAnalysisSession.objects.create(
            conversation=conversation,
            screenshot=screenshot,
            strategy_evaluation=(getattr(conversation, "strategy_evaluation", None)),
            sync_session=getattr(conversation, "sync_session", None),
            status=status,
            prompt_version="v1",
            model_version="mock-1.0",
            response_schema=response,
            warnings=warnings + ([error] if error else []),
        )
        return session.pk

    def _no_trade_response(
        self,
        conversation,
        evaluation_input: dict[str, Any],
        warnings: list[str],
        primary_reason: str,
        educational: bool = False,
    ) -> dict[str, Any]:
        self.probability.present(None)
        response = {
            "conversation_id": conversation.pk if conversation else None,
            "analysis_id": None,
            "instrument": evaluation_input.get("instrument", ""),
            "timeframe": evaluation_input.get("timeframe", ""),
            "market_type": evaluation_input.get("market_type", ""),
            "screenshot_timestamp": None,
            "mt5_verification_status": "unavailable",
            "market_context": "",
            "strategy_family": "",
            "direction": "NO TRADE",
            "supporting_evidence": [],
            "contradictory_evidence": [],
            "invalidation_conditions": [],
            "target_candle_interval": {},
            "timing_validity": evaluation_input.get("timing_validity", ""),
            "probability_value": None,
            "probability_type": None,
            "calibration_status": "uncalibrated",
            "explanation": (f"NO TRADE: {primary_reason}. {PROBABILITY_UNAVAILABLE_MESSAGE}"),
            "warnings": warnings,
            "follow_up_suggestions": ["What evidence is missing?"],
            "primary_reason_code": primary_reason,
            "validation_errors": [],
        }
        if educational:
            # CP7: educational mode never presents a trade assessment, even on
            # an early-exit path (OTC guard, expired window).
            warnings.append("educational_mode_no_actionable_prediction")
            response["direction"] = "EDUCATIONAL"
            response["calibration_status"] = "not_applicable_educational"
            response["explanation"] = (
                "Educational analysis: observations and course concepts only — "
                "this is not a trade assessment and contains no prediction. "
                f"No verifiable setup was available ({primary_reason}); in a "
                "course setting this is where learners identify what evidence "
                "would be required before any assessment could be made."
            )
            response["follow_up_suggestions"] = [
                "Explain why verification failed here.",
                "What is a dual-source verification policy?",
                "What evidence would a real assessment require?",
            ]
        response["analysis_id"] = self._persist_session(
            conversation, None, response, warnings, status="no_trade"
        )
        return response


__all__ = ["AnalysisOrchestrator"]
