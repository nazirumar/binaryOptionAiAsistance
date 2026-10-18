"""Access-control helpers for the market-synchronization API.

Sessions are strictly user-owned: a user may only read their own sessions
(superusers may read all). Instrument/MT5 data referenced by a session is never
exposed except through the owning session.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from apps.market_sync.models import MarketSyncSession


class IsSyncSessionOwner(BasePermission):
    """Object-level permission: the requester owns the session."""

    message = "You do not have access to this synchronization session."

    def has_object_permission(self, request, view, obj) -> bool:
        owner_id = getattr(obj, "owner_id", None)
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return owner_id is not None and owner_id == user.pk


def accessible_sessions(user):
    """Sessions a user may read."""
    if not user or not user.is_authenticated:
        return MarketSyncSession.objects.none()
    if user.is_superuser:
        return MarketSyncSession.objects.all()
    return MarketSyncSession.objects.filter(owner=user)


def resolve_session(user, session_id) -> MarketSyncSession | None:
    """Return a user-accessible session or ``None``."""
    return accessible_sessions(user).filter(pk=session_id).first()


__all__ = ["IsSyncSessionOwner", "accessible_sessions", "resolve_session"]
