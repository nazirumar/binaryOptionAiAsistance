"""Custom user model.

A custom user model is defined from the first migration onward so the project
never has to swap ``AUTH_USER_MODEL`` later (a painful, error-prone change).
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.market_data.constants import Timeframe


class User(AbstractUser):
    """Project user with a small set of analyst-oriented preferences."""

    display_name = models.CharField(max_length=150, blank=True)
    timezone = models.CharField(
        max_length=64,
        default="UTC",
        help_text="IANA timezone used when rendering analysis timestamps.",
    )
    preferred_theme = models.CharField(
        max_length=8,
        choices=[("light", "Light"), ("dark", "Dark")],
        default="dark",
    )

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self) -> str:
        return self.display_name or self.get_full_name() or self.username

    @property
    def name(self) -> str:
        return self.display_name or self.get_full_name() or self.username


class UserPreference(models.Model):
    """Per-user dashboard, analysis and notification preferences (Phase 9).

    Kept in a separate table so the user model stays small and preferences can
    evolve without touching the authentication schema.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    preferred_instrument = models.CharField(max_length=32, blank=True)
    preferred_timeframe = models.CharField(max_length=4, choices=Timeframe.choices, blank=True)
    market_type = models.CharField(max_length=16, blank=True)
    #: Screenshot display/upload preferences (e.g. default timeframe, retention).
    screenshot_preferences = models.JSONField(default=dict, blank=True)
    #: Analysis display preferences (e.g. which sections to expand by default).
    analysis_display = models.JSONField(default=dict, blank=True)
    #: Notification preferences (e.g. analysis completion emails).
    notifications = models.JSONField(default=dict, blank=True)
    #: Days to retain raw screenshots; 0 = keep indefinitely.
    data_retention_days = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "user preference"
        verbose_name_plural = "user preferences"

    def __str__(self) -> str:
        return f"Preferences for {self.user}"
