# ai_assistant/services/conversation_manager.py
"""Conversation management (Step 3).

New conversation, history, title, attachments, messages, follow-ups,
analysis references, deletion, and secure user ownership. Conversations
retain references to their original market-data and strategy-evaluation
snapshots; historical analysis is never silently updated with current
market data.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model

from apps.ai_assistant.models import AIAttachment, AIConversation, AIMessage
from apps.ai_assistant.services.safety_validator import sanitize_user_text

User = get_user_model()


class ConversationManager:
    def create_conversation(
        self,
        user,
        title: str = "",
        is_educational: bool = False,
    ) -> AIConversation:
        return AIConversation.objects.create(
            owner=user,
            title=sanitize_user_text(title, max_len=200) if title else "New conversation",
            is_educational=is_educational,
        )

    def list_conversations(self, user) -> Any:
        return AIConversation.objects.filter(owner=user)

    def get_conversation(self, user, conversation_id: int) -> AIConversation | None:
        """Secure user ownership: only the owner can access a conversation."""
        return AIConversation.objects.filter(owner=user, pk=conversation_id).first()

    def rename_conversation(self, conversation: AIConversation, title: str) -> AIConversation:
        conversation.title = sanitize_user_text(title, max_len=200)
        conversation.save(update_fields=["title", "updated_at"])
        return conversation

    def delete_conversation(self, conversation: AIConversation) -> None:
        conversation.delete()

    def add_user_message(
        self, conversation: AIConversation, content: str
    ) -> tuple[AIMessage, dict[str, bool]]:
        validation = {"ok": True, "flagged_injection": False}
        cleaned = sanitize_user_text(content)
        if cleaned.startswith("[content filtered"):
            validation = {"ok": False, "flagged_injection": True}
        message = AIMessage.objects.create(conversation=conversation, role="user", content=cleaned)
        return message, validation

    def add_assistant_message(
        self,
        conversation: AIConversation,
        content: str,
        analysis_session=None,
    ) -> AIMessage:
        return AIMessage.objects.create(
            conversation=conversation,
            role="assistant",
            content=content,
            analysis_session=analysis_session,
        )

    def history(self, conversation: AIConversation) -> Any:
        return conversation.messages.order_by("created_at")

    def add_attachment(
        self, conversation: AIConversation, screenshot=None, file_name: str = "", file_size: int = 0
    ) -> AIAttachment:
        return AIAttachment.objects.create(
            conversation=conversation,
            screenshot=screenshot,
            file_name=file_name,
            file_size=file_size,
        )


__all__ = ["ConversationManager"]
