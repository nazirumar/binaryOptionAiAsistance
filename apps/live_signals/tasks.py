# live_signals/tasks.py
"""Celery tasks for the live-signals monitor (Phase 15).

The beat schedule calls :func:`run_monitors_task` every 45 seconds. The task is
idempotent: duplicate-signal prevention lives in the model's unique constraint,
so a redelivered or overlapping run cannot create a second signal for the same
(monitor, strategy, candle, status).

Failures are bounded: each monitor records its error and, after
``MAX_CONSECUTIVE_FAILURES``, is marked ERROR and skipped until re-enabled.
The task itself never raises for a per-monitor problem, so one bad instrument
cannot stop the others.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

from apps.live_signals.services.alerts import create_alerts_for_signal
from apps.live_signals.services.monitor import (
    MAX_CONSECUTIVE_FAILURES,
    LiveSignalMonitor,
    ensure_monitors,
)
from apps.live_signals.services.providers import get_provider

logger = logging.getLogger(__name__)


@shared_task(name="live_signals.run_monitors", bind=True, max_retries=2)
def run_monitors_task(self) -> dict:
    """Run every enabled monitor once and alert on new confirmed events."""
    provider_name = getattr(settings, "LIVE_SIGNAL_PROVIDER", "db")
    engine = LiveSignalMonitor(provider=get_provider(provider_name))
    summary = {"monitors": 0, "new_signals": 0, "alerts": 0, "errors": 0}

    try:
        monitors = ensure_monitors()
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("live_signals: could not load monitors")
        raise self.retry(exc=exc) from exc

    for monitor in monitors:
        if not monitor.enabled:
            continue
        try:
            before_ids = set(
                monitor.signals.values_list("id", flat=True)
            )
            result = engine.run_monitor(monitor)
            summary["monitors"] += 1
            summary["new_signals"] += result.new_signals
            if result.new_signals:
                summary["alerts"] += _alert_new_signals(monitor, before_ids)
        except Exception:  # pragma: no cover - isolate per-monitor failures
            logger.exception("live_signals: monitor %s failed", monitor.pk)
            summary["errors"] += 1

    logger.info("live_signals run complete: %s", summary)
    return summary


def _alert_new_signals(monitor, before_ids: set) -> int:
    """Create alerts for signals added since ``before_ids``."""
    created = 0
    new_signals = monitor.signals.exclude(id__in=before_ids)
    for signal in new_signals:
        created += len(create_alerts_for_signal(signal))
    return created


@shared_task(name="live_signals.run_monitor")
def run_single_monitor_task(monitor_id: int) -> dict:
    """Run one monitor by id (manual trigger / targeted retry)."""
    from apps.live_signals.models import InstrumentMonitor

    monitor = InstrumentMonitor.objects.filter(pk=monitor_id).first()
    if monitor is None:
        return {"ok": False, "reason": "monitor not found"}

    provider_name = getattr(settings, "LIVE_SIGNAL_PROVIDER", "db")
    engine = LiveSignalMonitor(provider=get_provider(provider_name))
    result = engine.run_monitor(monitor)
    alerts = _alert_new_signals(monitor, set())
    return {
        "ok": True,
        "monitor": monitor_id,
        "new_signals": result.new_signals,
        "alerts": alerts,
        "feed_state": result.feed_state,
    }


__all__ = [
    "MAX_CONSECUTIVE_FAILURES",
    "run_monitors_task",
    "run_single_monitor_task",
]
