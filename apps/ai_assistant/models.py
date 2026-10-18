# apps/ai_assistant/models.py
"""AI Assistant models (Phase 8)."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

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


class AIAnalysisJob(TimeStampedModel):
    """Durable, cross-worker analysis job (Phase 11 CP8).

    Replaces the old in-process ``_IN_FLIGHT`` dictionary, which could not
    coordinate two Celery workers. Durability comes from database semantics:

    * ``idempotency_key`` is **unique** — a duplicate submission cannot create
      a second job for the same (user, screenshot, prompt version) pair;
    * :meth:`claim` is an atomic compare-and-swap (``pending`` → ``running``)
      using a single ``UPDATE`` — two workers can never both win;
    * a **terminal state** (completed / failed / cancelled) is never
      overwritten by a redelivered task;
    * a ``running`` job whose heartbeat is stale (worker crash, restart or
      killed timeout) can be re-claimed, bounded by ``attempts``;
    * :meth:`cancel` only cancels a job that has not started.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    TERMINAL_STATUSES = frozenset({Status.COMPLETED, Status.FAILED, Status.CANCELLED})

    #: A ``running`` job with no heartbeat for this long is considered dead.
    STALE_RUNNING_SECONDS = 900

    #: Hard ceiling on delivery attempts (crash/timeout recovery included).
    MAX_ATTEMPTS = 3

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="analysis_jobs",
    )
    conversation = models.ForeignKey(
        AIConversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analysis_jobs",
    )
    screenshot = models.ForeignKey(
        "chart_vision.ChartScreenshot",
        on_delete=models.CASCADE,
        related_name="analysis_jobs",
    )
    session = models.ForeignKey(
        AIAnalysisSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jobs",
    )
    idempotency_key = models.CharField(max_length=160, unique=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    celery_task_id = models.CharField(max_length=64, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    result_summary = models.JSONField(default=dict, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "heartbeat_at"], name="aiaj_status_hb_idx"),
        ]

    def __str__(self) -> str:
        return f"AnalysisJob #{self.pk} ({self.status})"

    # -- durable coordination ---------------------------------------------

    @staticmethod
    def make_idempotency_key(
        user_id: int, screenshot_id: int, prompt_version: str, educational: bool
    ) -> str:
        return (
            f"analyze:{user_id}:{screenshot_id}:{prompt_version}:{'edu' if educational else 'std'}"
        )

    def claim(self) -> bool:
        """Atomically move the job ``pending`` → ``running``.

        Also re-claims a ``running`` job whose heartbeat is stale (worker
        lost), as long as the attempt budget allows. Returns ``False`` when
        another worker holds a live claim or the job is terminal.
        """
        from django.db.models import F

        now = timezone.now()
        claimed = AIAnalysisJob.objects.filter(pk=self.pk, status=self.Status.PENDING).update(
            status=self.Status.RUNNING,
            attempts=F("attempts") + 1,
            heartbeat_at=now,
            started_at=now,
        )
        if claimed:
            self.refresh_from_db()
            return True

        # Recovery path: a RUNNING job with a stale heartbeat may be taken
        # over once the attempt budget is not exhausted.
        stale_before = now - timedelta(seconds=self.STALE_RUNNING_SECONDS)
        claimed = (
            AIAnalysisJob.objects.filter(
                pk=self.pk,
                status=self.Status.RUNNING,
                attempts__lt=self.MAX_ATTEMPTS,
            )
            .filter(models.Q(heartbeat_at__lt=stale_before) | models.Q(heartbeat_at__isnull=True))
            .update(attempts=F("attempts") + 1, heartbeat_at=now)
        )
        if claimed:
            self.refresh_from_db()
            return True

        # Attempt budget exhausted on a stuck RUNNING job -> terminal failure.
        AIAnalysisJob.objects.filter(
            pk=self.pk,
            status=self.Status.RUNNING,
            attempts__gte=self.MAX_ATTEMPTS,
        ).exclude(heartbeat_at__gt=stale_before).update(
            status=self.Status.FAILED,
            error_code="attempts_exhausted",
            error_message="Job exceeded the maximum number of delivery attempts.",
            finished_at=now,
        )
        self.refresh_from_db()
        return False

    def heartbeat(self) -> None:
        AIAnalysisJob.objects.filter(pk=self.pk).update(heartbeat_at=timezone.now())

    def mark_completed(self, session=None, summary: dict | None = None) -> None:
        AIAnalysisJob.objects.filter(pk=self.pk).exclude(status__in=self.TERMINAL_STATUSES).update(
            status=self.Status.COMPLETED,
            session=session,
            result_summary=summary or {},
            finished_at=timezone.now(),
        )
        self.refresh_from_db()

    def mark_failed(self, code: str, message: str) -> None:
        AIAnalysisJob.objects.filter(pk=self.pk).exclude(status__in=self.TERMINAL_STATUSES).update(
            status=self.Status.FAILED,
            error_code=code[:64],
            error_message=message[:2000],
            finished_at=timezone.now(),
        )
        self.refresh_from_db()

    def cancel(self) -> bool:
        """Cancel a job that has not started; terminal/running jobs refuse."""
        updated = AIAnalysisJob.objects.filter(pk=self.pk, status=self.Status.PENDING).update(
            status=self.Status.CANCELLED, finished_at=timezone.now()
        )
        self.refresh_from_db()
        return bool(updated)

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES


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
    "AIAnalysisJob",
    "AIAnalysisSession",
    "AIAttachment",
    "AIConversation",
    "AIMessage",
    "AIResponseAudit",
    "AssistantConfiguration",
]
