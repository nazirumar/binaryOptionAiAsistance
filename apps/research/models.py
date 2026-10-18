# apps/research/models.py
"""Research models for backtesting and calibration (Phase 7)."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class HistoricalDataset(TimeStampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="historical_datasets",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=128)
    instrument = models.CharField(max_length=32)
    timeframe = models.CharField(max_length=4)
    market_type = models.CharField(max_length=16, blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    candle_count = models.PositiveIntegerField(default=0)
    data_quality_flags = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=64, blank=True)
    is_validated = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.instrument} {self.timeframe})"


class HistoricalCandle(TimeStampedModel):
    dataset = models.ForeignKey(HistoricalDataset, on_delete=models.CASCADE, related_name="candles")
    open_time = models.DateTimeField(db_index=True)
    close_time = models.DateTimeField(null=True, blank=True)
    open = models.FloatField()
    high = models.FloatField()
    low = models.FloatField()
    close = models.FloatField()
    tick_volume = models.FloatField(null=True, blank=True)
    real_volume = models.FloatField(null=True, blank=True)
    is_complete = models.BooleanField(default=True)

    class Meta:
        ordering = ["open_time"]
        unique_together = ("dataset", "open_time")
        indexes = [models.Index(fields=["dataset", "open_time"])]

    def __str__(self) -> str:
        return f"{self.open_time.isoformat()} {self.open}/{self.close}"


class BacktestRun(TimeStampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="backtest_runs",
        null=True,
        blank=True,
    )
    dataset = models.ForeignKey(
        HistoricalDataset, on_delete=models.SET_NULL, null=True, related_name="backtests"
    )
    name = models.CharField(max_length=128)
    status = models.CharField(max_length=20, default="pending")
    strategy_config = models.JSONField(default=dict, blank=True)
    results = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    sample_count = models.PositiveIntegerField(default=0)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class CalibratedModel(TimeStampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="calibrated_models",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=128)
    version = models.CharField(max_length=32)
    is_active = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False)
    train_period_start = models.DateTimeField(null=True, blank=True)
    train_period_end = models.DateTimeField(null=True, blank=True)
    val_period_start = models.DateTimeField(null=True, blank=True)
    val_period_end = models.DateTimeField(null=True, blank=True)
    test_period_start = models.DateTimeField(null=True, blank=True)
    test_period_end = models.DateTimeField(null=True, blank=True)
    feature_schema = models.JSONField(default=dict, blank=True)
    calibration_method = models.CharField(max_length=32, blank=True)
    evaluation_metrics = models.JSONField(default=dict, blank=True)
    brier_score = models.FloatField(null=True, blank=True)
    calibration_error = models.FloatField(null=True, blank=True)
    model_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("name", "version")

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"


__all__ = [
    "BacktestRun",
    "CalibratedModel",
    "HistoricalCandle",
    "HistoricalDataset",
]
