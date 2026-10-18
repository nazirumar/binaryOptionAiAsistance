"""Celery tasks for market synchronization.

Verification is cheap and DB-only, so the API runs it synchronously. This task
exists for deployments that prefer to enqueue runs: it executes the same service
against an already-persisted session and is fully idempotent (re-running a
completed session simply recomputes its derived rows).
"""

from __future__ import annotations

import logging

from celery import shared_task

from apps.market_sync.services.synchronization_service import SynchronizationService

logger = logging.getLogger(__name__)


@shared_task(name="market_sync.run_verification", bind=True, max_retries=0)
def run_verification_task(self, session_id: int) -> int | None:
    """Run verification for a persisted session id; return the session id."""
    try:
        session = SynchronizationService().run_session_by_id(session_id)
    except Exception:
        logger.exception("market_sync.run_verification failed for session %s", session_id)
        return None
    return session.pk


__all__ = ["run_verification_task"]
