# apps/price_action/models.py
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.price_action.constants import (
    DataQuality,
    EvidenceStatus,
    PatternDirection,
)


class PriceActionRun(TimeStampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pa_runs",
        null=True,
        blank=True,
    )
    input_snapshot = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    schema_version = models.CharField(max_length=16, blank=True)
    engine_version = models.CharField(max_length=16, blank=True)
    candles_evaluated = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"pa#{self.pk}"


class EvidenceItem(TimeStampedModel):
    run = models.ForeignKey(PriceActionRun, on_delete=models.CASCADE, related_name="evidence")
    rule_id = models.CharField(max_length=120)
    detector = models.CharField(max_length=80)
    status = models.CharField(max_length=20, choices=EvidenceStatus.choices)
    direction = models.CharField(max_length=20, choices=PatternDirection.choices, blank=True)
    explanation = models.CharField(max_length=500, blank=True)
    candle_refs = models.JSONField(default=list, blank=True)
    supporting_levels = models.JSONField(default=list, blank=True)
    reasons = models.JSONField(default=list, blank=True)
    missing_inputs = models.JSONField(default=list, blank=True)
    data_quality = models.CharField(
        max_length=20, choices=DataQuality.choices, default=DataQuality.MEDIUM
    )

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.rule_id
