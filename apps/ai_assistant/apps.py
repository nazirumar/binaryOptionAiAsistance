# apps/ai_assistant/apps.py
from __future__ import annotations

from django.apps import AppConfig


class AIAssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai_assistant"
    label = "ai_assistant"
    verbose_name = "AI Assistant"
