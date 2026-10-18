# ai_assistant/services/assistant_service.py
"""Top-level assistant service tying conversation management, analysis
orchestration, follow-up handling and educational mode together."""

from __future__ import annotations

from typing import Any

from apps.ai_assistant.models import AIAnalysisSession
from apps.ai_assistant.services.analysis_orchestrator import AnalysisOrchestrator
from apps.ai_assistant.services.context_manager import ContextManager
from apps.ai_assistant.services.conversation_manager import ConversationManager
from apps.ai_assistant.services.evidence_retriever import EvidenceRetriever
from apps.ai_assistant.services.reasoning_provider import (
    ReasoningProvider,
    ReasoningRequest,
)

FOLLOW_UP_KEYWORDS = {
    "why_up": ("why did you predict up", "why up"),
    "why_down": ("why did you reject down", "why down"),
    "support": ("where is the support", "support"),
    "engulfing": ("is this an engulfing", "engulfing"),
    "no_trade": ("why did you return no trade", "no trade"),
    "probability": ("is the probability calibrated", "probability calibrated"),
    "otc": ("is this an otc", "otc"),
}


class AssistantService:
    def __init__(self) -> None:
        self.conversations = ConversationManager()
        self.context = ContextManager()
        self.orchestrator = AnalysisOrchestrator()
        self.evidence = EvidenceRetriever()
        self.provider = ReasoningProvider()

    def analyze_screenshot(
        self,
        user,
        evaluation_input: dict[str, Any] | None = None,
        approved_model: dict[str, Any] | None = None,
        title: str = "",
        educational: bool = False,
    ) -> dict[str, Any]:
        conversation = self.conversations.create_conversation(
            user, title=title, is_educational=educational
        )
        result = self.orchestrator.run(
            conversation,
            evaluation_input=evaluation_input,
            approved_model=approved_model,
            educational=educational,
        )
        # Link the persisted analysis so follow-ups retrieve stored evidence.
        if result.get("analysis_id"):
            session = AIAnalysisSession.objects.filter(pk=result["analysis_id"]).first()
            if session is not None:
                self.context.attach_analysis(conversation, session)
                conversation.refresh_from_db()
        self.conversations.add_assistant_message(conversation, result["explanation"])
        return {"conversation": conversation, "response": result}

    def handle_follow_up(self, user, conversation_id: int, message: str) -> dict[str, Any]:
        """Answer follow-ups from stored evidence, not conversational memory."""
        conversation = self.conversations.get_conversation(user, conversation_id)
        if conversation is None:
            return {"error": "conversation_not_found"}
        self.conversations.add_user_message(conversation, message)
        session = self.context.latest_analysis(conversation)
        evaluation = (
            session.strategy_evaluation if session is not None else conversation.strategy_evaluation
        )
        evidence = self.evidence.retrieve(evaluation)
        intent = self._classify_follow_up(message)
        answer = self._answer(intent, evidence)
        reply = self.provider.complete(
            ReasoningRequest(messages=(({"role": "user", "content": message}),), context=answer)
        )
        saved = self.conversations.add_assistant_message(conversation, reply.content)
        return {"message": saved, "evidence": evidence, "intent": intent}

    def _classify_follow_up(self, message: str) -> str:
        lowered = (message or "").lower()
        for intent, phrases in FOLLOW_UP_KEYWORDS.items():
            if any(p in lowered for p in phrases):
                return intent
        return "general"

    def _answer(self, intent: str, evidence: dict[str, Any]) -> dict[str, Any]:
        if not evidence.get("available"):
            return {
                "direction": "NO TRADE",
                "explanation": "No stored analysis evidence is available for this conversation.",
            }
        if intent == "probability":
            return {
                "direction": evidence.get("direction", "NO TRADE"),
                "explanation": "Probability unavailable — model not calibrated.",
            }
        if intent == "otc":
            return {
                "direction": evidence.get("direction", "NO TRADE"),
                "explanation": (
                    f"Market type recorded as {evidence.get('market_type')}; "
                    f"feed compatibility: {evidence.get('sync_status')}."
                ),
            }
        return {
            "direction": evidence.get("direction", "NO TRADE"),
            "explanation": (
                f"Stored evaluation reports {evidence.get('direction')} "
                f"({evidence.get('strategy_family')}) with primary reason "
                f"{evidence.get('primary_reason_code')}."
            ),
        }


__all__ = ["AssistantService"]
