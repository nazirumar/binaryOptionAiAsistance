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
from apps.strategy_knowledge.services.retrieval import KnowledgeRetrievalService

#: Cap on the retrieved-knowledge string added to a reasoning context, so the
#: provider's total context budget (MAX_CONTEXT_CHARS) is never threatened.
MAX_KNOWLEDGE_CONTEXT_CHARS = 1400

#: Cap on the book-strategy context block (Phase 13) for the same reason.
MAX_BOOK_CONTEXT_CHARS = 1400

#: Message cues that select the book-strategy knowledge block. Matching is
#: substring-based and deliberately narrow; an unmatched message gets nothing.
BOOK_CONTEXT_KEYWORDS = (
    "ss1", "ss2", "ss3", "ss4", "ss5", "ss6", "ss7", "ss8", "ss9",
    "ss10", "ss11", "ss12", "ss13", "ss14", "ss15", "ss16", "ss17",
    "ss18", "ss19", "ss20", "ss21", "ss22", "ss23", "ss24", "ss25",
    "ss26", "ss27", "ss28", "ss29", "ss30",
    "sure shot", "magic v", "the book", "book pattern", "trading bible",
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
        self.knowledge = KnowledgeRetrievalService()

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
        knowledge_context = self._knowledge_context(message, answer)
        if knowledge_context:
            answer = {**answer, "strategy_knowledge": knowledge_context}
        book_context = self._book_context(message)
        if book_context:
            answer = {**answer, "book_strategies": book_context}
        reply = self.provider.complete(
            ReasoningRequest(messages=(({"role": "user", "content": message}),), context=answer)
        )
        saved = self.conversations.add_assistant_message(conversation, reply.content)
        return {"message": saved, "evidence": evidence, "intent": intent}

    def _knowledge_context(self, message: str, answer: dict[str, Any]) -> str:
        """CP11: compact, stored-knowledge block for a strategy question.

        Returns ``""`` when nothing relevant is stored. The block only carries
        reviewed/approved definitions and always names itself as retrieved
        knowledge so the provider cites it instead of restating it as analysis.
        Experimental definitions are never included.
        """
        try:
            retrieved = self.knowledge.retrieve(message, limit=3)
        except Exception:
            return ""
        lines: list[str] = []
        for item in retrieved:
            conditions = "; ".join(item.required_conditions[:4]) or "n/a"
            invalidation = "; ".join(item.invalidation_conditions[:2]) or "n/a"
            lines.append(
                f"{item.name} [{item.strategy_id}] ({item.status_label}): "
                f"required: {conditions} | invalidation: {invalidation}"
            )
        if not lines:
            return ""
        block = (
            "Retrieved from the stored strategy knowledge base "
            "(educational reference, not an analysis result): " + " || ".join(lines)
        )
        return block[:MAX_KNOWLEDGE_CONTEXT_CHARS]

    def _book_context(self, message: str) -> str:
        """Phase 13: compact, catalog-grounded book-strategy block.

        Returns ``""`` when the message does not reference the book catalog.
        The block quotes ONLY the stored catalog fields (requirements,
        invalidation rules, recorded contradictions) and always states the
        deterministic decision: NO TRADE with an uncalibrated probability.
        It contains no accuracy or win-rate numbers, because the catalog
        stores none — the language model cannot receive a fabricated stat
        from here to repeat.
        """
        lowered = (message or "").lower()
        if not any(keyword in lowered for keyword in BOOK_CONTEXT_KEYWORDS):
            return ""
        try:
            from apps.book_strategies.models import BookStrategy

            rows = list(BookStrategy.objects.all())
        except Exception:
            return ""
        lines: list[str] = []
        for row in rows:
            key = row.key.lower()
            if key not in lowered and key.replace("_", " ") not in lowered:
                # also match explicit SS-number mentions like "SS21" (case-insensitive)
                if not any(
                    mention in lowered for mention in (f"ss{row.number}", f"ss {row.number}")
                ):
                    continue
            requirements = "; ".join(row.requirements[:3]) or "n/a"
            contradictions = (
                " | recorded contradictions: " + "; ".join(row.contradictions[:2])
                if row.contradictions
                else ""
            )
            lines.append(
                f"{row.key} ({row.name}) chapter {row.chapter}, PDF pp. {row.pdf_pages}: "
                f"required: {requirements}; invalidation: "
                f"{'; '.join(row.invalidation_rules[:2]) or 'n/a'}"
                f"{contradictions}. Decision: NO TRADE; probability unavailable "
                "(uncalibrated)."
            )
            if len(lines) >= 3:
                break
        if not lines:
            return ""
        block = (
            "Retrieved from the Binary Options Trading Bible catalog "
            "(educational reference, not an analysis result; patterns are "
            "observations, never predictions): " + " || ".join(lines)
        )
        return block[:MAX_BOOK_CONTEXT_CHARS]

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
