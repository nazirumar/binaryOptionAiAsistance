"""Permissions and access helpers for the market data API."""

from __future__ import annotations

import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission

from apps.market_data.models import MT5ConnectionProfile

WORKER_TOKEN_HEADER = "HTTP_X_WORKER_TOKEN"


class IsWorkerToken(BasePermission):
    """Allows access only to a caller presenting the configured worker token.

    When ``MT5_WORKER_TOKEN`` is unset, worker endpoints are disabled and this
    permission always denies access (the safe default).
    """

    message = "Invalid or missing worker token."

    def has_permission(self, request, view) -> bool:
        expected = getattr(settings, "MT5_WORKER_TOKEN", "")
        if not expected:
            return False
        provided = request.META.get(WORKER_TOKEN_HEADER, "")
        return hmac.compare_digest(str(provided), str(expected))


def accessible_profiles(user):
    """Profiles a user may read: their own plus shared/system profiles."""
    from django.db.models import Q

    if not user or not user.is_authenticated:
        return MT5ConnectionProfile.objects.none()
    if user.is_superuser:
        return MT5ConnectionProfile.objects.all()
    return MT5ConnectionProfile.objects.filter(Q(owner=user) | Q(owner__isnull=True))


def resolve_profile(user, profile_id):
    """Resolve a profile id for a user or return ``None`` when not permitted.

    A ``None`` profile id is allowed and yields ``None`` (meaning: use the shared
    configuration). A supplied id the user may not access raises ``LookupError``.
    """
    if profile_id in (None, ""):
        return None
    profile = accessible_profiles(user).filter(pk=profile_id).first()
    if profile is None:
        raise LookupError("Connection profile not found or not accessible.")
    return profile


__all__ = ["WORKER_TOKEN_HEADER", "IsWorkerToken", "accessible_profiles", "resolve_profile"]
