# screenshot_eval/services/forward.py
"""Immutable forward paper predictions from screenshots (Checkpoint 4).

The workflow enforced here, in order:

1. capture the screenshot (already stored as a case),
2. record the exact decision timestamp,
3. identify instrument + timeframe (from the case),
4. run pattern recognition (a persisted
   :class:`~apps.screenshot_eval.models.ScreenshotRecognitionRun`),
5. verify eligible strategy conditions (only a strategy whose human label is
   present, or whose deterministic recognition is a fresh CONFIRMED, is
   eligible),
6. record the strategy definition version,
7. record UP / DOWN / NO TRADE,
8. store a probability only when a calibrated value is supplied,
9. lock the prediction record.

Resolution (step 10 of the checkpoint: evaluate the result after the defined
period) lives in ``outcome_verification.py`` and can only move a ``locked``
record once. A prediction is never modified after its outcome is known.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.screenshot_eval.constants import (
    PREDICTION_METRIC_SCOPE,
    PROBABILITY_UNAVAILABLE,
    PredictionDirection,
    PredictionStatus,
)
from apps.screenshot_eval.models import (
    ForwardPaperPrediction,
    ScreenshotCase,
    ScreenshotRecognitionRun,
    case_payload_digest,
)

PREDICTION_DISCLAIMER = (
    "Screenshot-driven forward paper predictions: each record is locked before "
    "its outcome window exists and can only be verified once. NO TRADE records "
    "are decisions, not predictions, and are excluded from directional hit "
    "rate. Nothing here enables trading."
)


@dataclass(slots=True)
class ForwardRecordInput:
    """Everything needed to lock one prediction (captured before the outcome)."""

    strategy_key: str
    strategy_id: str
    direction: str
    decision_timestamp: Any = None
    strategy_version: str = ""
    entry_price: float | None = None
    probability: float | None = None
    probability_status: str = PROBABILITY_UNAVAILABLE
    source: str = ""


class ForwardPredictionService:
    """Create locked forward predictions; never mutate one afterwards."""

    @transaction.atomic
    def record(
        self,
        *,
        case: ScreenshotCase,
        owner,
        data: ForwardRecordInput,
        recognition_run: ScreenshotRecognitionRun | None = None,
    ) -> ForwardPaperPrediction:
        """Lock one prediction for a case + strategy.

        Idempotent on ``(case, strategy_key)``: a second attempt returns the
        existing locked record unchanged rather than rewriting it.
        """
        if data.direction not in PredictionDirection.ALL:
            raise ValueError(f"direction must be one of {PredictionDirection.ALL}")

        existing = ForwardPaperPrediction.objects.filter(
            case=case, strategy_key=data.strategy_key
        ).first()
        if existing is not None:
            return existing

        # Step 5 (eligibility): a screenshot-driven prediction requires either a
        # human label naming the strategy or a fresh CONFIRMED recognition.
        eligible, eligibility_reason = self._eligible(case, data.strategy_key, recognition_run)
        if not eligible:
            raise ValueError(f"strategy {data.strategy_key} not eligible: {eligibility_reason}")

        # Step 8: probability only when calibrated (never from recognition).
        probability = data.probability
        probability_status = data.probability_status
        if probability is not None and probability_status in ("", PROBABILITY_UNAVAILABLE):
            raise ValueError(
                "a probability may only be recorded with a calibrated, approved "
                "status - recognition alone never yields one"
            )

        decision_ts = data.decision_timestamp or timezone.now()
        payload = {
            "case_id": case.pk,
            "screenshot_id": case.screenshot_id,
            "strategy_key": data.strategy_key,
            "strategy_version": data.strategy_version,
            "direction": data.direction,
            "decision_timestamp": decision_ts.isoformat(),
            "instrument": case.instrument,
            "timeframe": case.timeframe,
            "market_type": case.market_type,
            "entry_price": data.entry_price,
            "probability": probability,
            "probability_status": probability_status,
            "metric_scope": PREDICTION_METRIC_SCOPE,
            "written_before_outcome": True,
        }
        return ForwardPaperPrediction.objects.create(
            case=case,
            recognition_run=recognition_run,
            owner=owner,
            strategy_key=data.strategy_key,
            strategy_id=data.strategy_id,
            strategy_version=data.strategy_version,
            instrument=case.instrument,
            timeframe=case.timeframe,
            market_type=case.market_type,
            source=data.source,
            direction=data.direction,
            decision_timestamp=decision_ts,
            entry_price=data.entry_price,
            probability=probability,
            probability_status=probability_status,
            prediction_payload=payload,
            payload_sha256=case_payload_digest(payload),
            status=PredictionStatus.LOCKED,
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _eligible(
        case: ScreenshotCase,
        strategy_key: str,
        recognition_run: ScreenshotRecognitionRun | None,
    ) -> tuple[bool, str]:
        """A strategy is eligible for a screenshot prediction when labelled or
        freshly, deterministically confirmed - never from a guess."""
        if case.expected_strategy_keys and strategy_key in set(case.expected_strategy_keys):
            return True, "named in the human label"
        if recognition_run is not None:
            confirmed = recognition_run.recognitions.filter(
                strategy_key=strategy_key, recognition_state="CONFIRMED_PATTERN"
            ).exists()
            if confirmed:
                return True, "fresh deterministic CONFIRMED_PATTERN recognition"
        return False, "no human label and no confirmed recognition"

    @staticmethod
    def summary(predictions: list[ForwardPaperPrediction] | None = None) -> dict[str, Any]:
        """Honest aggregate over screenshot predictions (no invented rates).

        NO TRADE records are reported separately and never counted as
        directional predictions. Only VERIFIED outcomes enter the hit rate.
        """
        rows = (
            list(predictions)
            if predictions is not None
            else list(ForwardPaperPrediction.objects.all())
        )
        from apps.screenshot_eval.services.metrics import wilson_interval

        directions = {"up": 0, "down": 0, "no_trade": 0}
        status_counts: dict[str, int] = {}
        verified_correct = 0
        verified_total = 0
        for row in rows:
            directions[row.direction] = directions.get(row.direction, 0) + 1
            status_counts[row.status] = status_counts.get(row.status, 0) + 1
            if row.direction == PredictionDirection.NO_TRADE:
                continue
            if row.status == PredictionStatus.VERIFIED:
                outcome = getattr(row, "outcome", None)
                if outcome is not None and outcome.counts_as_verified:
                    verified_total += 1
                    if outcome.verdict == "correct":
                        verified_correct += 1
        accuracy = (verified_correct / verified_total) if verified_total else None
        lo, hi = wilson_interval(verified_correct, verified_total)
        return {
            "metric_scope": PREDICTION_METRIC_SCOPE,
            "disclaimer": PREDICTION_DISCLAIMER,
            "total": len(rows),
            "directions": directions,
            "status_counts": status_counts,
            "verified_total": verified_total,
            "verified_correct": verified_correct,
            "accuracy": accuracy,
            "wilson_95": [lo, hi],
            "approved_for_decision_use": False,
            "approval_effect": "none: forward predictions never approve a strategy",
        }


__all__ = [
    "PREDICTION_DISCLAIMER",
    "ForwardPredictionService",
    "ForwardRecordInput",
]
