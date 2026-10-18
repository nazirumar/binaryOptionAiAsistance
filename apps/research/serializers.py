# apps/research/serializers.py
"""Research API serializers (Phase 11 CP3).

Read serializers expose only persisted, owner-relevant fields. Nothing here
computes or invents metrics: performance numbers are whatever the backtest
task actually stored, and calibration state is whatever ``CalibratedModel``
rows record — approval is never accepted from a client.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.research.models import BacktestRun, CalibratedModel, HistoricalDataset


class HistoricalDatasetSerializer(serializers.ModelSerializer):
    class Meta:
        model = HistoricalDataset
        fields = (
            "id",
            "name",
            "instrument",
            "timeframe",
            "market_type",
            "start_time",
            "end_time",
            "candle_count",
            "source",
            "is_validated",
            "data_quality_flags",
            "created_at",
        )
        read_only_fields = fields


class BacktestRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = BacktestRun
        fields = (
            "id",
            "dataset",
            "name",
            "status",
            "strategy_config",
            "metrics",
            "sample_count",
            "start_time",
            "end_time",
            "created_at",
        )
        read_only_fields = fields


class BacktestCreateSerializer(serializers.Serializer):
    """Queue a backtest against an owned or shared dataset."""

    dataset_id = serializers.IntegerField()
    name = serializers.CharField(max_length=128, required=False, allow_blank=True)
    strategy = serializers.CharField(max_length=64, required=False, allow_blank=True)
    instrument = serializers.CharField(max_length=32, required=False, allow_blank=True)
    timeframe = serializers.CharField(max_length=4, required=False, allow_blank=True)


class CalibratedModelSerializer(serializers.ModelSerializer):
    """Registry entry: approval and calibration evidence, never model_data."""

    class Meta:
        model = CalibratedModel
        fields = (
            "id",
            "name",
            "version",
            "is_active",
            "is_approved",
            "calibration_method",
            "brier_score",
            "calibration_error",
            "evaluation_metrics",
            "created_at",
        )
        read_only_fields = fields


__all__ = [
    "BacktestCreateSerializer",
    "BacktestRunSerializer",
    "CalibratedModelSerializer",
    "HistoricalDatasetSerializer",
]
