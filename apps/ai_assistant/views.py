# ai_assistant/views.py
"""Authenticated assistant API endpoints (Step 18).

Enforce user ownership, request limits and safe attachment handling.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.ai_assistant.models import AIAnalysisSession, AIConversation
from apps.ai_assistant.serializers import (
    AIAnalysisSessionSerializer,
    AIConversationSerializer,
    AIMessageSerializer,
    AnalyzeRequestSerializer,
    ConversationCreateSerializer,
    MessageCreateSerializer,
)
from apps.ai_assistant.services.assistant_service import AssistantService
from apps.ai_assistant.services.conversation_manager import ConversationManager


class AssistantBaseView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant_read"


class ConversationListView(AssistantBaseView):
    def get(self, request):
        qs = AIConversation.objects.filter(owner=request.user)
        return Response({"results": AIConversationSerializer(qs, many=True).data})

    def post(self, request):
        serializer = ConversationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = ConversationManager().create_conversation(
            request.user,
            title=serializer.validated_data.get("title", ""),
            is_educational=serializer.validated_data.get("is_educational", False),
        )
        return Response(AIConversationSerializer(conversation).data, status=status.HTTP_201_CREATED)


class ConversationDetailView(AssistantBaseView):
    def get(self, request, pk: int):
        conversation = get_object_or_404(AIConversation, pk=pk, owner=request.user)
        return Response(AIConversationSerializer(conversation).data)

    def delete(self, request, pk: int):
        conversation = get_object_or_404(AIConversation, pk=pk, owner=request.user)
        ConversationManager().delete_conversation(conversation)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConversationMessageView(AssistantBaseView):
    throttle_scope = "assistant_upload"

    def post(self, request, pk: int):
        conversation = get_object_or_404(AIConversation, pk=pk, owner=request.user)
        serializer = MessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        manager = ConversationManager()
        message, validation = manager.add_user_message(
            conversation, serializer.validated_data["content"]
        )
        if not validation["ok"]:
            return Response(
                {"detail": "content filtered", "flagged_injection": True},
                status=status.HTTP_400_BAD_REQUEST,
            )
        assistant = AssistantService()
        reply = assistant.handle_follow_up(
            request.user, conversation.pk, serializer.validated_data["content"]
        )
        if "error" in reply:
            return Response({"detail": reply["error"]}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "user_message": AIMessageSerializer(message).data,
                "assistant_message": AIMessageSerializer(reply["message"]).data,
            },
            status=status.HTTP_201_CREATED,
        )


class AnalyzeView(AssistantBaseView):
    throttle_scope = "assistant_upload"

    def post(self, request):
        serializer = AnalyzeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assistant = AssistantService()
        result = assistant.analyze_screenshot(
            request.user,
            educational=serializer.validated_data.get("educational", False),
        )
        return Response(
            {
                "conversation": AIConversationSerializer(result["conversation"]).data,
                "response": result["response"],
            },
            status=status.HTTP_201_CREATED,
        )


class AnalysisDetailView(AssistantBaseView):
    def get(self, request, pk: int):
        analysis = get_object_or_404(AIAnalysisSession, pk=pk, conversation__owner=request.user)
        return Response(AIAnalysisSessionSerializer(analysis).data)


__all__ = [
    "AnalysisDetailView",
    "AnalyzeView",
    "AssistantBaseView",
    "ConversationDetailView",
    "ConversationListView",
    "ConversationMessageView",
]
