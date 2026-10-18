# apps/strategy_knowledge/apps.py
from __future__ import annotations

from django.apps import AppConfig


class StrategyKnowledgeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.strategy_knowledge"
    label = "strategy_knowledge"
    verbose_name = "Strategy knowledge library"
