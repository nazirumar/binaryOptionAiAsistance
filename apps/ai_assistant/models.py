# apps/ai_assistant/models.py
"""AI Assistant models (Phase 8)."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class AIConversation(TimeStampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_conversations",
    )
    title = models.CharField(max_length=200, blank=True)
    is_educational = models.BooleanField(default=False)
    screenshot_analysis = models.ForeignKey(
        "chart_vision.ScreenshotAnalysis",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_conversations",
    )
    sync_session = models.ForeignKey(
        "market_sync.MarketSyncSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_conversations",
    )
    strategy_evaluation = models.ForeignKey(
        "strategy_engine.StrategyEvaluation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_conversations",
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.title or f"Conversation #{self.pk}"


class AIMessage(TimeStampedModel):
    conversation = models.ForeignKey(
        AIConversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=[("user", "User"), ("assistant", "Assistant")])
    content = models.TextField()
    analysis_session = models.ForeignKey(
        "ai_assistant.AIAnalysisSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.role}: {self.content[:50]}"


class AIAnalysisSession(TimeStampedModel):
    conversation = models.ForeignKey(
        AIConversation, on_delete=models.CASCADE, related_name="analysis_sessions"
    )
    screenshot = models.ForeignKey(
        "chart_vision.ChartScreenshot",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    strategy_evaluation = models.ForeignKey(
        "strategy_engine.StrategyEvaluation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    sync_session = models.ForeignKey(
        "market_sync.MarketSyncSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, default="completed")
    prompt_version = models.CharField(max_length=20, blank=True)
    model_version = models.CharField(max_length=80, blank=True)
    response_schema = models.JSONField(default=dict, blank=True)
    warnings = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-created_at"]


class AIAttachment(TimeStampedModel):
    conversation = models.ForeignKey(
        AIConversation, on_delete=models.CASCADE, related_name="attachments"
    )
    screenshot = models.ForeignKey(
        "chart_vision.ChartScreenshot",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]


class AIResponseAudit(TimeStampedModel):
    analysis_session = models.ForeignKey(
        AIAnalysisSession, on_delete=models.CASCADE, related_name="audits"
    )
    event_type = models.CharField(max_length=50)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]


class AssistantConfiguration(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return self.name


__all__ = [
    "AIAnalysisSession",
    "AIAttachment",
    "AIConversation",
    "AIMessage",
    "AIResponseAudit",
    "AssistantConfiguration",
]
