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
from apps.ai_assistant.services.probability_presenter import ProbabilityPresenter
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
        if market_type == "OTC" and sync_status != "VERIFIED_ALIGNMENT":
            warnings.append("otc_feed_incompatible")
            return self._no_trade_response(
                conversation,
                evaluation_input or {},
                warnings=warnings,
                primary_reason="otc_feed_incompatible",
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

        # Step 16: probability only from an approved, validated model.
        probability = self.probability.present(approved_model)
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
            "warnings": warnings + list(explanation.get("warnings", [])),
            "follow_up_suggestions": [
                "Why did you return this direction?",
                "What evidence is missing?",
                "Is the probability calibrated?",
            ],
        }
        validation = self.validator.validate(response, engine_direction=engine_direction)
        response["validation_errors"] = validation["errors"]
        response["analysis_id"] = self._persist_session(
            conversation, screenshot, response, warnings, status="completed"
        )
        return response

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
            "explanation": f"NO TRADE: {primary_reason}.",
            "warnings": warnings,
            "follow_up_suggestions": ["What evidence is missing?"],
            "primary_reason_code": primary_reason,
            "validation_errors": [],
        }
        response["analysis_id"] = self._persist_session(
            conversation, None, response, warnings, status="no_trade"
        )
        return response


__all__ = ["AnalysisOrchestrator"]
