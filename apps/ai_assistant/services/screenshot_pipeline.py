# apps/ai_assistant/services/screenshot_pipeline.py
"""Screenshot → vision → MT5 sync → evaluation pipeline (Phase 11 CP1).

This is the single server-side execution path for screenshot analyses. It
*composes existing services* — it is not a second analysis engine:

1. vision extraction (``chart_vision`` provider + schema validation);
2. instrument / timeframe / broker / market-type extraction, uncertainty
   preserved (``UNKNOWN`` stays unknown — nothing is guessed);
3. MT5 reference verification (``market_sync.SynchronizationService``) —
   the ONLY source of ``sync_status`` / ``feed_compatibility`` / freshness;
4. trusted-input assembly (``TrustedInputBuilder``) from owned server rows;
5. deterministic evaluation + timing + invalidation + probability
   (``AnalysisOrchestrator`` → ``EvaluationService``);
6. persistence (``AIAnalysisSession`` + linked ``StrategyEvaluation``).

Nothing here reads an HTTP request: trusted verdicts cannot be forged
because the pipeline never accepts them from a client. Calibrated
probabilities are looked up server-side from approved ``CalibratedModel``
rows only; when none is compatible the response carries the exact
"Probability unavailable — model not calibrated." notice.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

from apps.ai_assistant.models import AIAnalysisSession
from apps.chart_vision.constants import PROMPT_VERSION, AnalysisStatus
from apps.chart_vision.services.exceptions import ChartVisionError
from apps.chart_vision.services.screenshot_analyzer import (
    ScreenshotAnalyzer,
    get_or_create_analysis,
)
from apps.market_sync.constants import SyncStatus
from apps.market_sync.services.synchronization_service import verify_alignment
from apps.strategy_engine.services.trusted_input_builder import TrustedInputBuilder

logger = logging.getLogger("apps.ai_assistant")

#: How the pipeline identifies itself in idempotency keys.
PIPELINE_VERSION = PROMPT_VERSION


class PipelineError(Exception):
    """A pipeline stage failed; ``code`` is machine-readable."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def json_safe(obj: Any) -> Any:
    """Recursively coerce ``obj`` into JSONField-safe primitives."""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, str | int | bool) or obj is None:
        return obj
    return str(obj)


def lookup_approved_model(instrument: str, timeframe: str) -> dict[str, Any] | None:
    """Server-side calibrated-model lookup.

    Returns the dict for an approved, active ``CalibratedModel`` compatible
    with this instrument/timeframe, or ``None``. The client can never supply
    this object.
    """
    from apps.ai_assistant.services.probability_presenter import ProbabilityPresenter
    from apps.research.models import CalibratedModel

    rows = CalibratedModel.objects.filter(is_approved=True).order_by("-created_at")
    for row in rows:
        model = ProbabilityPresenter.to_dict(row)
        if not model.get("prediction_target"):
            continue
        model_instrument = str(model.get("instrument") or "").strip().upper()
        model_timeframe = str(model.get("timeframe") or "").strip().upper()
        if model_instrument and model_instrument != (instrument or "").upper():
            continue
        if model_timeframe and model_timeframe != (timeframe or "").upper():
            continue
        return model
    return None


def run_job(job) -> dict[str, Any]:
    """Execute the full pipeline for one claimed ``AIAnalysisJob``.

    Returns ``{"session": AIAnalysisSession | None, "summary": dict,
    "analysis_id": int | None}``. Raises :class:`PipelineError` on
    deterministic stage failures (recorded on the job, never retried).
    """
    from apps.ai_assistant.services.analysis_orchestrator import AnalysisOrchestrator

    conversation = job.conversation
    if conversation is None:
        raise PipelineError("conversation_missing", "Job has no conversation.")
    screenshot = job.screenshot
    # The submission view seeds result_summary={"educational": bool} before
    # dispatch; the final mark_completed() replaces it with the full summary.
    seed = job.result_summary if isinstance(job.result_summary, dict) else {}
    educational = bool(seed.get("educational"))

    # -- 1. vision extraction ---------------------------------------------
    # Terminal *usable* outcomes: completed, partial and insufficient all
    # carry extracted metadata with UNKNOWN preserved — uncertainty is
    # never guessed away, only a FAILED run is a hard pipeline error.
    usable = {AnalysisStatus.COMPLETED, AnalysisStatus.PARTIAL, AnalysisStatus.INSUFFICIENT}
    analysis, _created = get_or_create_analysis(screenshot)
    if analysis.status not in usable:
        try:
            ScreenshotAnalyzer().analyze(screenshot, analysis)
        except ChartVisionError as exc:
            raise PipelineError("vision_failed", str(exc)) from exc
        analysis.refresh_from_db()
    if analysis.status == AnalysisStatus.FAILED:
        raise PipelineError(
            "vision_failed", analysis.error_message or analysis.error_code or "vision failed"
        )
    if analysis.status not in usable:
        raise PipelineError("vision_incomplete", f"analysis ended as {analysis.status}")

    # -- 2. metadata extraction (uncertainty preserved) ---------------------
    metadata = analysis.chart_metadata or {}
    timeframe = str(metadata.get("timeframe") or "").strip().upper()

    # -- 3. server-side MT5 verification (the only trusted sync source) -----
    # A verification *error* must degrade to "no verified session" (which the
    # dual-source policy turns into NO TRADE) — never crash the pipeline and
    # never fabricate an outcome.
    try:
        session = verify_alignment(
            analysis,
            timeframe=timeframe or None,
            owner=job.owner,
            idempotency_key=f"assistant-sync:{analysis.pk}:{timeframe}",
        )
    except Exception as exc:  # degrade honestly, log loudly
        logger.exception("analysis job %s: MT5 verification failed", job.pk)
        logger.warning("verification unavailable (%s): treating as unverified", type(exc).__name__)
        session = None
    if session is not None:
        conversation.screenshot_analysis = analysis
        conversation.sync_session = session
        conversation.save(update_fields=["screenshot_analysis", "sync_session", "updated_at"])
    else:
        conversation.screenshot_analysis = analysis
        conversation.save(update_fields=["screenshot_analysis", "updated_at"])

    # -- 4. trusted input assembly -----------------------------------------
    evidence = TrustedInputBuilder().build(
        owner=job.owner,
        analysis_obj=analysis,
        sync_session_obj=session,
    )
    input_data = evidence.input_data
    if not input_data.get("completed_candles"):
        # No reference candles anywhere: the evaluation engines cannot run.
        # This is an *unverifiable* case, so the orchestrator will emit NO
        # TRADE with explicit warnings — never a fabricated assessment and
        # never a hard job failure.
        logger.warning(
            "analysis job %s: no reference candles for %s/%s",
            job.pk,
            input_data.get("instrument"),
            input_data.get("timeframe"),
        )

    # -- 5. deterministic evaluation + probability + explanation -----------
    approved_model = lookup_approved_model(
        input_data.get("instrument", ""), input_data.get("timeframe", "")
    )
    response = AnalysisOrchestrator().run(
        conversation,
        screenshot=screenshot,
        evaluation_input=input_data,
        approved_model=approved_model,
        educational=educational,
    )

    summary = json_safe(
        {
            "direction": response.get("direction"),
            "instrument": response.get("instrument"),
            "timeframe": response.get("timeframe"),
            "market_type": response.get("market_type"),
            "mt5_verification_status": response.get("mt5_verification_status"),
            "market_context": response.get("market_context"),
            "strategy_family": response.get("strategy_family"),
            "supporting_evidence": response.get("supporting_evidence"),
            "contradictory_evidence": response.get("contradictory_evidence"),
            "invalidation_conditions": response.get("invalidation_conditions"),
            "timing_validity": response.get("timing_validity"),
            "probability_value": response.get("probability_value"),
            "probability_type": response.get("probability_type"),
            "calibration_status": response.get("calibration_status"),
            "explanation": response.get("explanation"),
            "warnings": response.get("warnings"),
            "primary_reason_code": response.get("primary_reason_code"),
            "reason_codes": response.get("reason_codes"),
            "educational": educational,
            "sync_evidence": {
                "sync_session_id": session.pk if session is not None else None,
                "sync_status": session.outcome if session is not None else "",
                "verified": bool(
                    session is not None and session.outcome == SyncStatus.VERIFIED_ALIGNMENT
                ),
                "feed_compatibility": (session.feed_compatibility if session is not None else ""),
                "freshness_status": session.freshness_status if session is not None else "",
                "candle_provenance": evidence.candle_provenance,
            },
            "validation_errors": response.get("validation_errors"),
        }
    )
    session_obj = (
        AIAnalysisSession.objects.filter(pk=response.get("analysis_id")).first()
        if response.get("analysis_id")
        else None
    )
    return {
        "session": session_obj,
        "session_id": response.get("analysis_id"),
        "analysis_id": response.get("analysis_id"),
        "summary": summary,
    }


__all__ = [
    "PIPELINE_VERSION",
    "PipelineError",
    "json_safe",
    "lookup_approved_model",
    "run_job",
]
