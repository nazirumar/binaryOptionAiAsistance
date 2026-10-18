# ai_assistant/tasks.py
"""Background task helpers for expensive assistant jobs (Step 4).

Duplicate or uncontrolled jobs are prevented by an in-process job registry
keyed on (conversation, screenshot). In production this maps to a queue
backend; the guard semantics stay the same.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("apps.ai_assistant")

_IN_FLIGHT: dict[tuple[int, int], bool] = {}


def analysis_job_key(conversation_id: int, screenshot_id: int) -> tuple[int, int]:
    return (conversation_id, screenshot_id)


def is_duplicate_job(conversation_id: int, screenshot_id: int) -> bool:
    return analysis_job_key(conversation_id, screenshot_id) in _IN_FLIGHT


def begin_job(conversation_id: int, screenshot_id: int) -> bool:
    """Register a job; returns False when a duplicate is already running."""
    key = analysis_job_key(conversation_id, screenshot_id)
    if key in _IN_FLIGHT:
        return False
    _IN_FLIGHT[key] = True
    return True


def end_job(conversation_id: int, screenshot_id: int) -> None:
    _IN_FLIGHT.pop(analysis_job_key(conversation_id, screenshot_id), None)


def run_analysis_job(
    conversation_id: int,
    screenshot_id: int,
    orchestrator_run,
) -> dict[str, Any]:
    """Run the orchestration exactly once per (conversation, screenshot)."""
    if not begin_job(conversation_id, screenshot_id):
        return {"status": "duplicate_suppressed"}
    try:
        result = orchestrator_run()
        return {"status": "completed", "result": result}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("background analysis job failed")
        return {"status": "failed", "error": type(exc).__name__}
    finally:
        end_job(conversation_id, screenshot_id)


__all__ = [
    "analysis_job_key",
    "begin_job",
    "end_job",
    "is_duplicate_job",
    "run_analysis_job",
]
