# ai_assistant/serializers.py
from __future__ import annotations

from rest_framework import serializers

from apps.ai_assistant.models import (
    AIAnalysisSession,
    AIAttachment,
    AIConversation,
    AIMessage,
)


class AIMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIMessage
        fields = ("id", "role", "content", "analysis_session", "created_at")
        read_only_fields = fields


class AIAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIAttachment
        fields = ("id", "file_name", "file_size", "screenshot", "created_at")
        read_only_fields = fields


class AIAnalysisSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIAnalysisSession
        fields = (
            "id",
            "status",
            "prompt_version",
            "model_version",
            "response_schema",
            "warnings",
            "strategy_evaluation",
            "sync_session",
            "created_at",
        )
        read_only_fields = fields


class AIConversationSerializer(serializers.ModelSerializer):
    messages = AIMessageSerializer(many=True, read_only=True)
    attachments = AIAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = AIConversation
        fields = (
            "id",
            "title",
            "is_educational",
            "strategy_evaluation",
            "sync_session",
            "screenshot_analysis",
            "messages",
            "attachments",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ConversationCreateSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True, max_length=200)
    is_educational = serializers.BooleanField(required=False, default=False)


class MessageCreateSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=4000)


class AnalyzeRequestSerializer(serializers.Serializer):
    conversation_id = serializers.IntegerField(required=False, allow_null=True)
    screenshot_id = serializers.IntegerField(required=False, allow_null=True)
    educational = serializers.BooleanField(required=False, default=False)


__all__ = [
    "AIAnalysisSessionSerializer",
    "AIAttachmentSerializer",
    "AIConversationSerializer",
    "AIMessageSerializer",
    "AnalyzeRequestSerializer",
    "ConversationCreateSerializer",
    "MessageCreateSerializer",
]
