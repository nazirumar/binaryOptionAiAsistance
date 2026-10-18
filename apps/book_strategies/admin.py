"""Admin registration for book strategies.

``decision_use_approved`` is intentionally NOT exposed as a casual checkbox:
approval requires documented validation and explicit user authorization, so it
is only settable through a deliberate change here (never by seed/imports).
"""

from django.contrib import admin

from apps.book_strategies.models import BookStrategy, BookStrategyDetection


@admin.register(BookStrategy)
class BookStrategyAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "number",
        "name",
        "chapter",
        "research_status",
        "recognition_enabled",
        "decision_use_approved",
    )
    list_filter = ("research_status", "recognition_enabled", "decision_use_approved")
    search_fields = ("key", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(BookStrategyDetection)
class BookStrategyDetectionAdmin(admin.ModelAdmin):
    list_display = ("strategy", "state", "direction", "data_verification", "decision", "created_at")
    list_filter = ("state", "decision")
    search_fields = ("strategy__key",)
    readonly_fields = ("created_at", "updated_at")
