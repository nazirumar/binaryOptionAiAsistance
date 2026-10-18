"""Celery tasks for the core application."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="core.health_probe")
def health_probe() -> dict[str, str]:
    """Trivial task used to verify the Celery worker/broker wiring.

    Returns a deterministic payload so it can be asserted in tests.
    """
    logger.info("core.health_probe.executed")
    return {"status": "ok", "task": "core.health_probe"}
