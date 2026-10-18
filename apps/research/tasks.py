# apps/research/tasks.py
"""Background backtest execution (Phase 9 dashboard, Phase 10 reliability).

Backtests are *only* ever run from a worker: the HTTP layer creates a
``BacktestRun`` row and queues this task, so an expensive replay can never
block or exhaust a web worker.

Honesty rules enforced here:

* The run records **decisions only**. ``HistoricalReplay`` does not settle
  forward outcomes, so no win-rate or accuracy figure is invented: when no
  result carries a measured outcome, ``directional_accuracy`` is reported as
  ``None`` with ``accuracy_status="not_evaluated"``.
* A failure sets ``status="failed"`` with an explicit reason. It never writes
  plausible-looking metrics.
* Re-delivery is safe: a run that already reached a terminal state is left
  untouched (workers run with ``task_acks_late``).
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)

#: Minimum candles of history the replay engine requires before it emits a
#: single evaluation point. Below this there is nothing to report.
MIN_HISTORY = 20

#: Bound on how many candles a single run will load, so a very large dataset
#: cannot exhaust worker memory.
MAX_CANDLES = 20_000

#: Terminal states: a re-delivered task must not overwrite a finished run.
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})


@shared_task(
    name="research.run_backtest",
    bind=True,
    max_retries=2,
    default_retry_delay=15,
)
def run_backtest_task(self, run_id: int) -> dict[str, Any]:
    """Execute one backtest run and persist its outcome.

    Returns a small, non-sensitive summary for the Celery result backend; the
    authoritative record stays in the ``BacktestRun`` row.
    """
    from apps.research.models import BacktestRun, HistoricalCandle
    from apps.research.services.historical_replay import HistoricalReplay
    from apps.research.services.performance_metrics import PerformanceMetrics

    try:
        run = BacktestRun.objects.select_related("dataset", "owner").get(pk=run_id)
    except BacktestRun.DoesNotExist:
        logger.warning("research.backtest_missing", extra={"run_id": run_id})
        return {"status": "missing", "run_id": run_id}

    # Idempotency guard for redelivered messages.
    if run.status in TERMINAL_STATES:
        logger.info(
            "research.backtest_already_terminal",
            extra={"run_id": run_id, "status": run.status},
        )
        return {"status": run.status, "run_id": run_id, "skipped": True}

    run.status = "running"
    run.save(update_fields=["status", "updated_at"])

    candles_qs = HistoricalCandle.objects.filter(dataset=run.dataset).order_by("open_time")[
        :MAX_CANDLES
    ]
    candles = [
        {
            "open_time": candle.open_time,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "complete": candle.is_complete,
            "instrument": run.dataset.instrument,
            "timeframe": run.dataset.timeframe,
        }
        for candle in candles_qs
    ]

    # Validation happens *before* any work: an undersized dataset cannot
    # produce a single evaluation point, so the run fails loudly rather than
    # finishing with a misleading "0 samples, 100% win rate" style report.
    if len(candles) <= MIN_HISTORY:
        _fail(
            run,
            code="insufficient_candles",
            detail=(
                f"Dataset '{run.dataset.name}' has {len(candles)} candles; "
                f"at least {MIN_HISTORY + 2} are required for a single "
                "lookahead-free evaluation point."
            ),
        )
        return {"status": "failed", "run_id": run_id, "reason": "insufficient_candles"}

    from django.utils import timezone

    started_at = timezone.now()
    try:
        results = HistoricalReplay().replay(candles, min_history=MIN_HISTORY)
    except Exception as exc:  # pragma: no cover - defensive failure path
        logger.exception("research.backtest_error", extra={"run_id": run_id})
        _fail(run, code="replay_error", detail=f"{type(exc).__name__}: {exc}")
        return {"status": "failed", "run_id": run_id, "reason": "replay_error"}

    metrics = PerformanceMetrics().compute(results)

    # Only report accuracy when outcomes were actually settled. Replay records
    # decisions, so by default accuracy is NOT measurable and must stay null.
    outcomes_measured = any("hit" in item for item in results)
    if outcomes_measured:
        metrics["accuracy_status"] = "measured"
    else:
        metrics["directional_accuracy"] = None
        metrics["accuracy_status"] = "not_evaluated"
        metrics["accuracy_note"] = (
            "The replay recorded decisions only; forward outcomes were not "
            "settled, so no accuracy is reported."
        )

    run.status = "completed"
    run.results = _json_safe({"decisions": results})
    run.metrics = metrics
    run.sample_count = len(results)
    run.start_time = started_at
    run.end_time = timezone.now()
    run.save(
        update_fields=[
            "status",
            "results",
            "metrics",
            "sample_count",
            "start_time",
            "end_time",
            "updated_at",
        ]
    )
    logger.info(
        "research.backtest_completed",
        extra={"run_id": run_id, "sample_count": len(results)},
    )
    return {
        "status": "completed",
        "run_id": run_id,
        "sample_count": len(results),
        "accuracy_status": metrics.get("accuracy_status"),
    }


def _json_safe(value):
    """Recursively convert datetimes (etc.) to JSON-serialisable values.

    ``HistoricalReplay`` returns ``signal_time`` as a ``datetime``; the
    ``results`` JSONField cannot store that, so persisting raw would raise
    ``TypeError: Object of type datetime is not JSON serializable`` and lose
    the whole run.
    """
    from datetime import date, datetime

    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return value


def _fail(run, *, code: str, detail: str) -> None:  # type: ignore[no-untyped-def]
    """Mark a run failed with an explicit, non-fabricated reason."""
    from django.utils import timezone

    run.status = "failed"
    run.results = {}
    run.metrics = {"error": code, "detail": detail}
    run.sample_count = 0
    run.end_time = timezone.now()
    run.save(
        update_fields=[
            "status",
            "results",
            "metrics",
            "sample_count",
            "end_time",
            "updated_at",
        ]
    )
    logger.warning(
        "research.backtest_failed",
        extra={"run_id": run.pk, "error": code, "detail": detail},
    )


__all__ = ["MIN_HISTORY", "run_backtest_task"]
