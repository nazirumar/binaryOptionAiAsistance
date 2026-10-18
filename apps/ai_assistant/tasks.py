# ai_assistant/tasks.py
"""Background analysis execution (Step 4; rebuilt in Phase 11 CP8).

The previous implementation coordinated duplicate jobs with an in-process
``_IN_FLIGHT`` dictionary — useless once more than one Celery worker runs.
Coordination is now **durable** and lives in the database:

* one ``AIAnalysisJob`` row per requested analysis, keyed by a **unique**
  idempotency key (user, screenshot, prompt version, mode);
* :meth:`AIAnalysisJob.claim` performs an atomic compare-and-swap so two
  workers can never both run the same job;
* terminal states are never overwritten by redelivered tasks
  (``task_acks_late`` + ``reject_on_worker_lost`` make redelivery likely);
* a crashed worker leaves a ``running`` row with a stale heartbeat, which the
  claim path re-takes up to ``AIAnalysisJob.MAX_ATTEMPTS`` times;
* retry policy: only *transient infrastructure* errors (database/redis) are
  retried with Celery's bounded retry; deterministic analysis failures
  (validation, vision provider, sync mismatch) are recorded as terminal and
  never retried — a retry cannot change deterministic evidence.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.db import OperationalError

logger = logging.getLogger("apps.ai_assistant")

#: Errors worth retrying: infrastructure, not analysis.
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (OperationalError,)


@shared_task(
    name="ai_assistant.run_analysis",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
)
def run_screenshot_analysis_task(self, job_id: int) -> dict[str, Any]:
    """Execute one screenshot-analysis job exactly once per claim.

    Returns a small, non-sensitive summary for the Celery result backend.
    """
    from apps.ai_assistant.models import AIAnalysisJob

    try:
        job = AIAnalysisJob.objects.select_related("owner", "screenshot").get(pk=job_id)
    except AIAnalysisJob.DoesNotExist:
        logger.warning("analysis job %s missing", job_id)
        return {"status": "missing", "job_id": job_id}

    # Re-delivery of a finished job must change nothing.
    if job.is_terminal:
        return {"status": "already_terminal", "job_id": job.pk, "job_status": job.status}

    # Atomic claim: the losing worker exits without touching the pipeline.
    if not job.claim():
        return {"status": "duplicate_suppressed", "job_id": job.pk, "job_status": job.status}

    try:
        # Imported lazily: the pipeline pulls in vision/sync/evaluation.
        from apps.ai_assistant.services.screenshot_pipeline import PipelineError, run_job

        result = run_job(job)
    except TRANSIENT_ERRORS as exc:
        if self.request.retries >= self.max_retries:
            job.mark_failed("transient_failure", f"{type(exc).__name__}: {exc}")
            logger.exception("analysis job %s failed transiently", job.pk)
            return {"status": "failed", "job_id": job.pk, "error": type(exc).__name__}
        job.heartbeat()
        logger.warning(
            "analysis job %s transient error; retrying (%d/%d)",
            job.pk,
            self.request.retries + 1,
            self.max_retries,
        )
        raise self.retry(exc=exc) from exc
    except PipelineError as exc:
        # Deterministic stage failure (vision rejected, no conversation, …):
        # the machine-readable stage code lands on the job; never retried.
        job.mark_failed(exc.code, str(exc))
        logger.error("analysis job %s failed at stage %s: %s", job.pk, exc.code, exc)
        return {"status": "failed", "job_id": job.pk, "error": exc.code}
    except Exception as exc:
        job.mark_failed(type(exc).__name__, str(exc))
        logger.exception("analysis job %s failed", job.pk)
        return {"status": "failed", "job_id": job.pk, "error": type(exc).__name__}

    session = result.get("session")
    job.mark_completed(session=session, summary=result.get("summary") or {})
    return {"status": "completed", "job_id": job.pk, "analysis_id": result.get("analysis_id")}


__all__ = [
    "TRANSIENT_ERRORS",
    "run_screenshot_analysis_task",
]
