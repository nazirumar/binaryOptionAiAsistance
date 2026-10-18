# apps/price_action/apps.py
from __future__ import annotations

from django.apps import AppConfig


class PriceActionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.price_action"
    label = "price_action"
    verbose_name = "Price action knowledge engine"
