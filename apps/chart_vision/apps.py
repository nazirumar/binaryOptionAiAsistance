"""Chart vision application: screenshot analysis via a vision-capable model."""

from __future__ import annotations

from django.apps import AppConfig


class ChartVisionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.chart_vision"
    label = "chart_vision"
    verbose_name = "Chart Vision"
