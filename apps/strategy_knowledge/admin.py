# apps/strategy_knowledge/admin.py
from __future__ import annotations

from django.contrib import admin

from apps.strategy_knowledge.models import (
    StrategyCategory,
    StrategyCondition,
    StrategyDatasetSample,
    StrategyDefinition,
    StrategyDetection,
    StrategyDetectionEvidence,
    StrategyExample,
    StrategyPatternLabel,
    StrategyVersion,
)


class StrategyConditionInline(admin.TabularInline):
    model = StrategyCondition
    extra = 1
    fields = ("order", "kind", "label", "description", "detector_key", "params")


@admin.register(StrategyDefinition)
class StrategyDefinitionAdmin(admin.ModelAdmin):
    list_display = (
        "strategy_id",
        "name",
        "category",
        "variant",
        "validation_status",
        "enabled",
        "version",
    )
    list_filter = ("validation_status", "enabled", "category", "variant")
    search_fields = ("strategy_id", "name", "description")
    readonly_fields = ("created_at", "updated_at")
    inlines = (StrategyConditionInline,)


@admin.register(StrategyCategory)
class StrategyCategoryAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "order")
    readonly_fields = ("created_at", "updated_at")


@admin.register(StrategyVersion)
class StrategyVersionAdmin(admin.ModelAdmin):
    list_display = ("version", "released_at", "created_at")
    readonly_fields = ("created_at", "updated_at")


@admin.register(StrategyPatternLabel)
class StrategyPatternLabelAdmin(admin.ModelAdmin):
    list_display = ("label", "definition", "notes")
    search_fields = ("label",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(StrategyExample)
class StrategyExampleAdmin(admin.ModelAdmin):
    list_display = ("title", "definition", "is_bullish", "source")
    list_filter = ("is_bullish", "definition")
    readonly_fields = ("created_at", "updated_at")


class StrategyDetectionEvidenceInline(admin.TabularInline):
    model = StrategyDetectionEvidence
    extra = 0
    fields = ("condition_kind", "label", "source", "satisfied", "confidence", "detail")
    readonly_fields = fields


@admin.register(StrategyDetection)
class StrategyDetectionAdmin(admin.ModelAdmin):
    list_display = ("definition", "analysis", "status", "provenance", "created_at")
    list_filter = ("status", "provenance", "otc_incompatible")
    search_fields = ("definition__strategy_id", "summary")
    readonly_fields = ("created_at", "updated_at")
    inlines = (StrategyDetectionEvidenceInline,)


@admin.register(StrategyDatasetSample)
class StrategyDatasetSampleAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "sample_kind",
        "label_source",
        "reviewer",
        "reviewer_approved",
        "dataset_version",
    )
    list_filter = ("sample_kind", "label_source", "reviewer_approved", "dataset_version")
    search_fields = ("label", "instrument")
    readonly_fields = ("created_at", "updated_at")
