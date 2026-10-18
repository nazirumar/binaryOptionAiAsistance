# ai_assistant/serializers.py
from __future__ import annotations

from rest_framework import serializers

from apps.ai_assistant.models import (
    AIAnalysisJob,
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


class AnalyzeUploadSerializer(serializers.Serializer):
    """Screenshot analysis request (Phase 11 CP1).

    Accepts either a multipart ``screenshot`` upload *or* a reference to an
    existing owned ``screenshot_id`` — exactly one of the two. Trusted
    verdict fields (``sync_status``, ``market_type``, calibration flags, …)
    are deliberately absent: the pipeline derives every verdict server-side.
    """

    # NB: a plain FileField, not ImageField — image *content* is validated by
    # exactly one authority (``create_screenshot_from_upload``'s Pillow
    # checks), so every rejection surfaces as the same machine-readable
    # ``invalid_image`` error instead of two divergent error shapes.
    screenshot = serializers.FileField(required=False, allow_null=True)
    screenshot_id = serializers.IntegerField(required=False, allow_null=True)
    conversation_id = serializers.IntegerField(required=False, allow_null=True)
    title = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    educational = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        has_upload = attrs.get("screenshot") is not None
        has_reference = bool(attrs.get("screenshot_id"))
        if has_upload == has_reference:
            raise serializers.ValidationError(
                "Provide exactly one of 'screenshot' (upload) or 'screenshot_id' (reference)."
            )
        return attrs


class AIAnalysisJobSerializer(serializers.ModelSerializer):
    """Public view of a durable analysis job (Phase 11 CP8/CP1)."""

    class Meta:
        model = AIAnalysisJob
        fields = (
            "id",
            "status",
            "attempts",
            "error_code",
            "error_message",
            "result_summary",
            "conversation",
            "screenshot",
            "session",
            "created_at",
            "updated_at",
            "started_at",
            "finished_at",
        )
        read_only_fields = fields


__all__ = [
    "AIAnalysisJobSerializer",
    "AIAnalysisSessionSerializer",
    "AIAttachmentSerializer",
    "AIConversationSerializer",
    "AIMessageSerializer",
    "AnalyzeRequestSerializer",
    "AnalyzeUploadSerializer",
    "ConversationCreateSerializer",
    "MessageCreateSerializer",
]
