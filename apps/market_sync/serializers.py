"""Serializers for the market-synchronization API."""

from __future__ import annotations

from rest_framework import serializers

from apps.market_data.constants import Timeframe
from apps.market_sync.models import (
    CandleAlignment,
    FeedCompatibilityAssessment,
    MarketSyncIssue,
    MarketSyncSession,
    SynchronizationAuditLog,
)


class CandleAlignmentSerializer(serializers.ModelSerializer):
    match_result_display = serializers.CharField(source="get_match_result_display", read_only=True)

    class Meta:
        model = CandleAlignment
        fields = (
            "id",
            "screenshot_index",
            "screenshot_classification",
            "screenshot_body_size",
            "screenshot_upper_wick",
            "screenshot_lower_wick",
            "screenshot_position",
            "mt5_candle",
            "mt5_open_time",
            "mt5_direction",
            "mt5_body_ratio",
            "mt5_upper_wick_ratio",
            "mt5_lower_wick_ratio",
            "match_result",
            "match_result_display",
            "direction_match",
            "body_match",
            "wick_match",
            "local_extreme_match",
            "confidence",
            "limitations",
            "evidence",
        )
        read_only_fields = fields


class MarketSyncIssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketSyncIssue
        fields = ("id", "code", "severity", "message", "candle_index", "detail")
        read_only_fields = fields


class FeedCompatibilityAssessmentSerializer(serializers.ModelSerializer):
    compatibility_display = serializers.CharField(
        source="get_compatibility_display", read_only=True
    )

    class Meta:
        model = FeedCompatibilityAssessment
        fields = (
            "screenshot_instrument",
            "canonical_instrument",
            "mt5_broker_symbol",
            "broker",
            "market_type",
            "mapping_source",
            "mapping_verification",
            "mapping_verified",
            "screenshot_is_otc",
            "reference_is_otc",
            "compatibility",
            "compatibility_display",
            "reasons",
            "evidence",
        )
        read_only_fields = fields


class SynchronizationAuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = SynchronizationAuditLog
        fields = ("id", "kind", "severity", "message", "detail", "occurred_at")
        read_only_fields = fields


class MarketSyncSessionSummarySerializer(serializers.ModelSerializer):
    outcome_display = serializers.CharField(source="get_outcome_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_verified = serializers.BooleanField(read_only=True)

    class Meta:
        model = MarketSyncSession
        fields = (
            "id",
            "status",
            "status_display",
            "outcome",
            "outcome_display",
            "is_verified",
            "comparison_method",
            "config_version",
            "screenshot",
            "analysis",
            "reference_symbol",
            "screenshot_instrument",
            "canonical_instrument",
            "mt5_broker_symbol",
            "broker",
            "market_type",
            "mapping_source",
            "mapping_status",
            "mapping_verified",
            "screenshot_timeframe",
            "mt5_timeframe",
            "alignment_anchor",
            "alignment_source",
            "alignment_confidence",
            "alignment_uncertain",
            "screenshot_candle_count",
            "completed_candle_count",
            "aligned_candle_count",
            "matched_candle_count",
            "mismatched_candle_count",
            "unaligned_candle_count",
            "direction_agreement",
            "structure_agreement",
            "feed_compatibility",
            "freshness_status",
            "price_comparison_method",
            "error_code",
            "started_at",
            "finished_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class MarketSyncSessionDetailSerializer(MarketSyncSessionSummarySerializer):
    alignments = CandleAlignmentSerializer(many=True, read_only=True)
    issues = MarketSyncIssueSerializer(many=True, read_only=True)
    audit_logs = SynchronizationAuditLogSerializer(many=True, read_only=True)
    feed_assessment = serializers.SerializerMethodField()

    class Meta(MarketSyncSessionSummarySerializer.Meta):
        fields = (
            *MarketSyncSessionSummarySerializer.Meta.fields,
            "mt5_snapshot",
            "metrics",
            "reasons",
            "alignments",
            "issues",
            "feed_assessment",
            "audit_logs",
        )
        read_only_fields = fields

    def get_feed_assessment(self, obj):
        assessment = getattr(obj, "feed_assessment", None)
        if assessment is None:
            return None
        return FeedCompatibilityAssessmentSerializer(assessment).data


class SyncVerifyRequestSerializer(serializers.Serializer):
    """Input for ``POST /api/sync/verify/``."""

    analysis_id = serializers.IntegerField(required=False, min_value=1)
    screenshot_id = serializers.IntegerField(required=False, min_value=1)
    profile = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    timeframe = serializers.ChoiceField(choices=Timeframe.choices, required=False, allow_blank=True)
    captured_at = serializers.DateTimeField(required=False, allow_null=True)
    tz_offset_minutes = serializers.IntegerField(
        required=False, allow_null=True, min_value=-720, max_value=840
    )
    idempotency_key = serializers.CharField(required=False, allow_blank=True, max_length=120)

    def validate(self, attrs):
        if not attrs.get("analysis_id") and not attrs.get("screenshot_id"):
            raise serializers.ValidationError("Provide either `analysis_id` or `screenshot_id`.")
        return attrs


__all__ = [
    "CandleAlignmentSerializer",
    "FeedCompatibilityAssessmentSerializer",
    "MarketSyncIssueSerializer",
    "MarketSyncSessionDetailSerializer",
    "MarketSyncSessionSummarySerializer",
    "SyncVerifyRequestSerializer",
    "SynchronizationAuditLogSerializer",
]
