"""Access-control helpers for the chart-vision API.

Screenshots are strictly user-owned: a user may only access their own uploads and
analyses (superusers may access all). Image bytes are only ever streamed through
an ownership-checked view.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from apps.chart_vision.models import ChartScreenshot, ScreenshotAnalysis


class IsScreenshotOwner(BasePermission):
    """Object-level permission: the requester owns the screenshot/analysis."""

    message = "You do not have access to this screenshot."

    def has_object_permission(self, request, view, obj) -> bool:
        owner_id = getattr(obj, "owner_id", None)
        if owner_id is None:
            return False
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        return bool(user.is_superuser or owner_id == user.pk)


def accessible_screenshots(user):
    """Screenshots a user may read."""
    if not user or not user.is_authenticated:
        return ChartScreenshot.objects.none()
    if user.is_superuser:
        return ChartScreenshot.objects.all()
    return ChartScreenshot.objects.filter(owner=user)


def accessible_analyses(user):
    """Analyses a user may read."""
    if not user or not user.is_authenticated:
        return ScreenshotAnalysis.objects.none()
    if user.is_superuser:
        return ScreenshotAnalysis.objects.all()
    return ScreenshotAnalysis.objects.filter(owner=user)


def resolve_screenshot(user, screenshot_id) -> ChartScreenshot | None:
    """Return a user-accessible screenshot or ``None``."""
    return accessible_screenshots(user).filter(pk=screenshot_id).first()


def resolve_analysis(user, analysis_id) -> ScreenshotAnalysis | None:
    """Return a user-accessible analysis (with its screenshot) or ``None``."""
    return accessible_analyses(user).select_related("screenshot").filter(pk=analysis_id).first()


__all__ = [
    "IsScreenshotOwner",
    "accessible_analyses",
    "accessible_screenshots",
    "resolve_analysis",
    "resolve_screenshot",
]
