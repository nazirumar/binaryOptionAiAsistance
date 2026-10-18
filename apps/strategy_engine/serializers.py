# apps/strategy_engine/serializers.py
"""Serializers for strategy evaluation API."""

from __future__ import annotations

from rest_framework import serializers

from apps.strategy_engine.models import StrategyEvaluation


class StrategyEvaluateRequestSerializer(serializers.Serializer):
    """Request serializer for strategy evaluation."""

    screenshot_analysis_id = serializers.IntegerField(required=False, allow_null=True)
    sync_session_id = serializers.IntegerField(required=False, allow_null=True)
    instrument = serializers.CharField(max_length=32, required=False, allow_blank=True)
    timeframe = serializers.CharField(max_length=4, required=False, allow_blank=True)
    candles = serializers.JSONField(required=False, default=list)
    price_action_result = serializers.JSONField(required=False, default=dict)
    now = serializers.DateTimeField(required=False, allow_null=True)

    class Meta:
        fields = (
            "screenshot_analysis_id",
            "sync_session_id",
            "instrument",
            "timeframe",
            "candles",
            "price_action_result",
            "now",
        )


class StrategyEvaluationSerializer(serializers.ModelSerializer):
    """Serializer for StrategyEvaluation."""

    class Meta:
        model = StrategyEvaluation
        fields = (
            "id",
            "evaluation_id",
            "instrument",
            "timeframe",
            "market_type",
            "direction",
            "strategy_family",
            "market_context",
            "status",
            "explanation",
            "warnings",
            "invalidation_conditions",
            "reason_codes",
            "primary_reason_code",
            "timing_validity",
            "probability_status",
            "sync_status",
            "feed_compatibility",
            "data_quality",
            "data_freshness",
            "confluence_score",
            "schema_version",
            "engine_config_version",
            "rule_version",
            "created_at",
            "updated_at",
            "output_snapshot",
        )
        read_only_fields = fields


__all__ = [
    "StrategyEvaluateRequestSerializer",
    "StrategyEvaluationSerializer",
]
