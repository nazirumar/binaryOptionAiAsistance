# apps/price_action/admin.py
from __future__ import annotations

from django.contrib import admin

from apps.price_action.models import EvidenceItem, PriceActionRun


@admin.register(PriceActionRun)
class PriceActionRunAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "candles_evaluated", "created_at")
    readonly_fields = ("created_at", "updated_at")


@admin.register(EvidenceItem)
class EvidenceItemAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "rule_id", "detector", "status", "direction")
    readonly_fields = ("created_at", "updated_at")
