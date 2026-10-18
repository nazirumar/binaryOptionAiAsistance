# apps/strategy_engine/admin.py
from __future__ import annotations

from django.contrib import admin

from apps.strategy_engine.models import (
    DecisionAuditLog,
    EvaluationConflict,
    EvaluationEvidence,
    StrategyCandidate,
    StrategyEvaluation,
    StrategyRuleConfiguration,
)


@admin.register(StrategyEvaluation)
class StrategyEvaluationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "owner",
        "direction",
        "strategy_family",
        "instrument",
        "timeframe",
        "created_at",
    )
    list_filter = ("direction", "strategy_family", "status", "market_type")
    search_fields = ("instrument", "canonical_instrument", "broker_symbol")
    readonly_fields = ("input_snapshot", "output_snapshot")


@admin.register(StrategyCandidate)
class StrategyCandidateAdmin(admin.ModelAdmin):
    list_display = ("id", "evaluation", "direction", "strategy_family", "status")
    list_filter = ("direction", "strategy_family", "status")


@admin.register(EvaluationEvidence)
class EvaluationEvidenceAdmin(admin.ModelAdmin):
    list_display = ("id", "evaluation", "rule_id", "detector", "direction")
    list_filter = ("direction", "detector")


@admin.register(EvaluationConflict)
class EvaluationConflictAdmin(admin.ModelAdmin):
    list_display = ("id", "evaluation", "conflict_type", "severity")
    list_filter = ("conflict_type", "severity")


@admin.register(DecisionAuditLog)
class DecisionAuditLogAdmin(admin.ModelAdmin):
    list_display = ("id", "evaluation", "event_type", "severity", "occurred_at")
    list_filter = ("event_type", "severity")


@admin.register(StrategyRuleConfiguration)
class StrategyRuleConfigurationAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active", "config_version", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
