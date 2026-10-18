# ai_assistant/views.py
"""Authenticated assistant API endpoints (Step 18).

Enforce user ownership, request limits and safe attachment handling.

Phase 11 CP1: ``POST /analyze/`` accepts a real screenshot (multipart upload
or owned reference), links it to a conversation and dispatches one **durable**
``AIAnalysisJob``. The job executes the server-side pipeline (vision → MT5
sync → trusted input → evaluation); the response carries the job state and,
when eager execution finished inline, the full structured assessment. No
client field ever becomes a trusted verdict — those are derived server-side.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.ai_assistant.models import AIAnalysisJob, AIAnalysisSession, AIAttachment, AIConversation
from apps.ai_assistant.serializers import (
    AIAnalysisJobSerializer,
    AIAnalysisSessionSerializer,
    AIConversationSerializer,
    AIMessageSerializer,
    AnalyzeUploadSerializer,
    ConversationCreateSerializer,
    MessageCreateSerializer,
)
from apps.ai_assistant.services.assistant_service import AssistantService
from apps.ai_assistant.services.conversation_manager import ConversationManager
from apps.ai_assistant.services.screenshot_pipeline import PIPELINE_VERSION
from apps.ai_assistant.tasks import run_screenshot_analysis_task
from apps.chart_vision.models import ChartScreenshot
from apps.chart_vision.services.exceptions import ImageValidationError
from apps.chart_vision.services.upload import create_screenshot_from_upload


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
    """Screenshot → durable analysis job (Phase 11 CP1).

    Accepts exactly one of:

    * ``screenshot`` — multipart image upload (validated, stored privately);
    * ``screenshot_id`` — a reference to an existing screenshot owned by the
      caller.

    A unique idempotency key ``(user, screenshot, prompt version, mode)``
    guarantees the same submission never dispatches a second job: replays
    return the original job (200) instead of a duplicate (201).
    """

    throttle_scope = "assistant_upload"

    def post(self, request):
        serializer = AnalyzeUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        educational = bool(data.get("educational", False))

        # 1. Resolve the screenshot — upload or owned reference (404 otherwise).
        if data.get("screenshot") is not None:
            try:
                screenshot = create_screenshot_from_upload(request.user, data["screenshot"])
            except ImageValidationError as exc:
                return Response(
                    {"code": "invalid_image", "detail": str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            screenshot = get_object_or_404(
                ChartScreenshot, pk=data["screenshot_id"], owner=request.user
            )

        # 2. Idempotent replay: the same (user, screenshot, mode) submission
        #    returns the already-dispatched job without creating anything.
        job_key = AIAnalysisJob.make_idempotency_key(
            request.user.pk, screenshot.pk, PIPELINE_VERSION, educational
        )
        existing = AIAnalysisJob.objects.filter(idempotency_key=job_key).first()
        if existing is not None:
            payload = AIAnalysisJobSerializer(existing).data
            if existing.conversation_id:
                payload["conversation"] = AIConversationSerializer(existing.conversation).data
            return Response(payload, status=status.HTTP_200_OK)

        # 3. Conversation + attachment + job created atomically so a concurrent
        #    duplicate submission cannot leave an orphaned conversation behind.
        try:
            with transaction.atomic():
                if data.get("conversation_id"):
                    conversation = get_object_or_404(
                        AIConversation, pk=data["conversation_id"], owner=request.user
                    )
                else:
                    conversation = ConversationManager().create_conversation(
                        request.user,
                        title=data.get("title", ""),
                        is_educational=educational,
                    )
                AIAttachment.objects.get_or_create(
                    conversation=conversation,
                    screenshot=screenshot,
                    defaults={
                        "file_name": screenshot.original_filename,
                        "file_size": screenshot.size_bytes,
                    },
                )
                job = AIAnalysisJob.objects.create(
                    owner=request.user,
                    conversation=conversation,
                    screenshot=screenshot,
                    idempotency_key=job_key,
                    # Seed: the pipeline reads the requested mode from here;
                    # completion replaces it with the full structured summary.
                    result_summary={"educational": educational},
                )
        except IntegrityError:
            # Lost a race against an identical submission — replay that one.
            existing = AIAnalysisJob.objects.get(idempotency_key=job_key)
            payload = AIAnalysisJobSerializer(existing).data
            if existing.conversation_id:
                payload["conversation"] = AIConversationSerializer(existing.conversation).data
            return Response(payload, status=status.HTTP_200_OK)

        # 4. Dispatch (eager in dev/test, real Celery in production).
        async_result = run_screenshot_analysis_task.delay(job.pk)
        task_id = getattr(async_result, "id", None)
        if task_id:
            AIAnalysisJob.objects.filter(pk=job.pk).update(celery_task_id=str(task_id))
        job.refresh_from_db()
        # Eager execution may have linked the analysis/sync session to the
        # conversation inside run_job; reload so the response reflects the
        # persisted state rather than the pre-dispatch snapshot.
        conversation.refresh_from_db()

        payload = AIAnalysisJobSerializer(job).data
        payload["conversation"] = AIConversationSerializer(conversation).data
        return Response(payload, status=status.HTTP_201_CREATED)


class AnalysisJobDetailView(AssistantBaseView):
    """Owner-scoped status/result view for a durable analysis job."""

    def get(self, request, pk: int):
        job = get_object_or_404(AIAnalysisJob, pk=pk, owner=request.user)
        return Response(AIAnalysisJobSerializer(job).data)


class AnalysisJobCancelView(AssistantBaseView):
    """Cancel a job that has not started yet (409 otherwise)."""

    throttle_scope = "assistant_upload"

    def post(self, request, pk: int):
        job = get_object_or_404(AIAnalysisJob, pk=pk, owner=request.user)
        if job.is_terminal:
            return Response(
                {"code": "already_terminal", "detail": f"Job is {job.status}."},
                status=status.HTTP_409_CONFLICT,
            )
        if not job.cancel():
            return Response(
                {"code": "not_cancellable", "detail": "Job already running."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"cancelled": True, "job": AIAnalysisJobSerializer(job).data})


class AnalysisDetailView(AssistantBaseView):
    def get(self, request, pk: int):
        analysis = get_object_or_404(AIAnalysisSession, pk=pk, conversation__owner=request.user)
        return Response(AIAnalysisSessionSerializer(analysis).data)


__all__ = [
    "AnalysisDetailView",
    "AnalysisJobCancelView",
    "AnalysisJobDetailView",
    "AnalyzeView",
    "AssistantBaseView",
    "ConversationDetailView",
    "ConversationListView",
    "ConversationMessageView",
]
