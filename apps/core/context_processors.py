"""Template context processors for shared UI state."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import HttpRequest

from apps.core import __version__

VALID_THEMES = {"light", "dark"}
DEFAULT_THEME = "dark"


def app_context(request: HttpRequest) -> dict[str, Any]:
    """Expose application metadata and the active theme to templates."""
    theme = request.COOKIES.get("theme", DEFAULT_THEME)
    if theme not in VALID_THEMES:
        theme = DEFAULT_THEME
    return {
        "app_name": "Nazbeen Academy Binary Ai Asisstance",
        "app_version": __version__,
        "theme": theme,
        "default_theme": DEFAULT_THEME,
        "debug": settings.DEBUG,
    }
