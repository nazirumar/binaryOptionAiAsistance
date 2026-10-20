# screenshot_eval/apps.py
from __future__ import annotations

from django.apps import AppConfig


class ScreenshotEvalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.screenshot_eval"
    verbose_name = "Screenshot evaluation"
