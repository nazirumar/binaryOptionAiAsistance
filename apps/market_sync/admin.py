"""Django admin registration for market synchronization."""

from __future__ import annotations

from django.contrib import admin

from apps.market_sync.models import (
    CandleAlignment,
    FeedCompatibilityAssessment,
    MarketSyncIssue,
    MarketSyncSession,
    SynchronizationAuditLog,
)


class CandleAlignmentInline(admin.TabularInline):
    model = CandleAlignment
    extra = 0
    can_delete = False
    readonly_fields = (
        "screenshot_index",
        "screenshot_classification",
        "mt5_open_time",
        "mt5_direction",
        "match_result",
        "confidence",
    )


class MarketSyncIssueInline(admin.TabularInline):
    model = MarketSyncIssue
    extra = 0
    can_delete = False


@admin.register(MarketSyncSession)
class MarketSyncSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "owner",
        "outcome",
        "status",
        "canonical_instrument",
        "mt5_broker_symbol",
        "mt5_timeframe",
        "alignment_source",
        "created_at",
    )
    list_filter = (
        "outcome",
        "status",
        "feed_compatibility",
        "freshness_status",
        "structure_agreement",
    )
    search_fields = ("canonical_instrument", "mt5_broker_symbol", "screenshot_instrument")
    readonly_fields = ("config_version", "created_at", "updated_at")
    inlines = [CandleAlignmentInline, MarketSyncIssueInline]


@admin.register(CandleAlignment)
class CandleAlignmentAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "screenshot_index", "match_result", "mt5_direction")
    list_filter = ("match_result",)


@admin.register(FeedCompatibilityAssessment)
class FeedCompatibilityAssessmentAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "compatibility", "screenshot_is_otc", "reference_is_otc")
    list_filter = ("compatibility",)


@admin.register(MarketSyncIssue)
class MarketSyncIssueAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "code", "severity")
    list_filter = ("severity", "code")


@admin.register(SynchronizationAuditLog)
class SynchronizationAuditLogAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "kind", "severity", "occurred_at")
    list_filter = ("kind", "severity")
