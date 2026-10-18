"""Core application: shared infrastructure used across the project."""

from __future__ import annotations

from django.apps import AppConfig
from django.core.checks import register


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Core"

    def ready(self) -> None:
        """Register custom system checks explicitly (deterministic, idempotent)."""
        from apps.core.checks import check_production_database

        register(check_production_database, deploy=True)
