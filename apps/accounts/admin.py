"""Admin registration for the custom user model."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "display_name", "is_staff", "is_active", "date_joined")
    search_fields = ("username", "email", "display_name")
    ordering = ("-date_joined",)
    fieldsets = (
        *DjangoUserAdmin.fieldsets,
        ("Profile", {"fields": ("display_name", "timezone", "preferred_theme")}),
    )
    add_fieldsets = (
        *DjangoUserAdmin.add_fieldsets,
        ("Profile", {"fields": ("email", "display_name", "timezone", "preferred_theme")}),
    )
