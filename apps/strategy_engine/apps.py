# apps/strategy_engine/apps.py
from __future__ import annotations

from django.apps import AppConfig


class StrategyEngineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.strategy_engine"
    label = "strategy_engine"
    verbose_name = "Strategy Evaluation Engine"
