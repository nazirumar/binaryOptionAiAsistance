# ai_assistant/services/context_manager.py
"""Context management (Step 3/9).

Holds references to the original market-data and strategy-evaluation
snapshots for a conversation. Historical analysis is never silently
updated using current market data.
"""

from __future__ import annotations

from typing import Any

from apps.ai_assistant.models import AIAnalysisSession, AIConversation


class ContextManager:
    def attach_analysis(
        self,
        conversation: AIConversation,
        analysis_session: AIAnalysisSession,
    ) -> AIConversation:
        """Link the latest analysis snapshots without mutating history."""
        conversation.screenshot_analysis = getattr(analysis_session, "screenshot", None)
        conversation.sync_session = getattr(analysis_session, "sync_session", None)
        conversation.strategy_evaluation = getattr(analysis_session, "strategy_evaluation", None)
        conversation.save(
            update_fields=[
                "screenshot_analysis",
                "sync_session",
                "strategy_evaluation",
                "updated_at",
            ]
        )
        return conversation

    def latest_analysis(self, conversation: AIConversation) -> AIAnalysisSession | None:
        return conversation.analysis_sessions.order_by("-created_at").first()

    def snapshot_context(self, conversation: AIConversation) -> dict[str, Any]:
        """Immutable view of the conversation's referenced snapshots."""
        evaluation = conversation.strategy_evaluation
        return {
            "conversation_id": conversation.pk,
            "strategy_evaluation_id": evaluation.pk if evaluation else None,
            "screenshot_analysis_id": (conversation.screenshot_analysis_id),
            "sync_session_id": conversation.sync_session_id,
            "note": "Snapshots are referenced, never rewritten with current data.",
        }


__all__ = ["ContextManager"]
