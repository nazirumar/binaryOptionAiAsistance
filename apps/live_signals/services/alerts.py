# live_signals/services/alerts.py
"""In-app notifications for confirmed live-signal events (Phase 15, cp 6).

Deduplication is structural: :class:`~apps.live_signals.models.SignalAlert` has a
unique ``(user, signal)`` constraint, so one confirmed event yields exactly one
alert per user no matter how many times the monitor runs.

Browser notifications are **only** created/flagged when a user has explicitly
enabled ``browser_notifications``. No external messaging service is contacted:
the application does not claim SMS/email/push delivery anywhere.
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction

from apps.live_signals.constants import SignalStatus
from apps.live_signals.models import LiveSignal, SignalAlert, UserMonitorSettings

logger = logging.getLogger(__name__)

#: Statuses that warrant an alert.
ALERTABLE_STATUSES = (SignalStatus.CONFIRMED_PATTERN,)

#: Statuses that also warrant a "directional" alert.
DIRECTIONAL_STATUSES = (SignalStatus.CONFIRMED_PATTERN,)


def _title_for(signal: LiveSignal) -> str:
    if signal.is_directional:
        arrow = "UP" if signal.direction == "bullish" else "DOWN"
        return f"{arrow} {signal.strategy_name or signal.strategy_key} ({signal.instrument} {signal.timeframe})"
    return f"Pattern {signal.strategy_name or signal.strategy_key} ({signal.instrument} {signal.timeframe})"


def _body_for(signal: LiveSignal) -> str:
    if signal.is_directional:
        return (
            "Research-validated directional signal from an approved strategy. "
            "Paper monitoring only."
        )
    return "Confirmed pattern detected from closed candles. Observation only - not a trade signal."


def create_alerts_for_signal(signal: LiveSignal) -> list[SignalAlert]:
    """Create alerts for every user watching this instrument/timeframe.

    Returns the alerts actually created (deduplicated by the DB constraint).
    """
    if signal.status not in ALERTABLE_STATUSES:
        return []

    from django.contrib.auth import get_user_model

    User = get_user_model()
    created: list[SignalAlert] = []

    for user in User.objects.filter(is_active=True):
        settings_obj = UserMonitorSettings.objects.filter(user=user).first()
        if settings_obj is not None:
            if not settings_obj.alerts_enabled:
                continue
            if settings_obj.only_approved and not signal.is_directional:
                # The user asked for approved signals only: pattern alerts are
                # suppressed, but the pattern row itself remains visible in the
                # feed for honesty.
                continue
            if not settings_obj.show_experimental and signal.category == "experimental_pattern":
                continue
            if settings_obj.instruments and signal.instrument not in settings_obj.instruments:
                continue
            if settings_obj.timeframes and signal.timeframe not in settings_obj.timeframes:
                continue
        try:
            with transaction.atomic():
                alert = SignalAlert.objects.create(
                    user=user,
                    signal=signal,
                    title=_title_for(signal),
                    body=_body_for(signal),
                    delivered_browser=bool(
                        settings_obj is not None and settings_obj.browser_notifications
                    ),
                )
            created.append(alert)
        except IntegrityError:
            # Already alerted for this event: deduplicated.
            continue
    return created


def unread_alerts_for(user, limit: int = 20):
    """Unread alerts for a user, newest first."""
    if user is None or not getattr(user, "is_authenticated", False):
        return SignalAlert.objects.none()
    return SignalAlert.objects.filter(user=user, read_at__isnull=True).select_related(
        "signal"
    )[:limit]


def mark_alert_read(user, alert_id: int) -> bool:
    """Mark one of the user's own alerts read. Owner-scoped; False if not theirs."""
    from django.utils import timezone

    updated = SignalAlert.objects.filter(
        pk=alert_id, user=user, read_at__isnull=True
    ).update(read_at=timezone.now())
    return bool(updated)


__all__ = [
    "ALERTABLE_STATUSES",
    "create_alerts_for_signal",
    "mark_alert_read",
    "unread_alerts_for",
]
