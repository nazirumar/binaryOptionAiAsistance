# apps/research/apps.py
from __future__ import annotations

from django.apps import AppConfig


class ResearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.research"
    label = "research"
    verbose_name = "Research & Backtesting"
