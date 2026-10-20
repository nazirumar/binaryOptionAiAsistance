# screenshot_eval/services/recognition.py
"""Screenshot recognition pass (Checkpoint 2).

This service does **not** re-implement pattern recognition. It orchestrates the
existing Phase 13 machinery over a screenshot case:

* :func:`~apps.book_strategies.services.recognition.build_book_candidates`
  maps the analysis' persisted vision records through the fixed vision->book
  table (capped at ``AWAITING_CONFIRMATION`` / ``SCREENSHOT_ONLY``; no OHLC is
  invented from pixels).
* :class:`~apps.book_strategies.services.recognition.BookStrategyRecognizer`
  runs the deterministic state machine when compatible OHLC candles are
  available (matched via a sync session's reference symbol), and refuses with
  ``INCOMPATIBLE_FEEDS`` when an OTC screenshot is checked against non-OTC
  data.

Every result is persisted as a :class:`~apps.screenshot_eval.models.ScreenshotRecognition`
row with the full Step-9 shape: strategy id, state, visible evidence, missing
conditions, invalidation evidence and data verification status.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from apps.book_strategies.constants import IMPLEMENTED_SPEC_KEYS, SPEC_BY_KEY
from apps.book_strategies.services.recognition import (
    BookDetection,
    BookStrategyRecognizer,
    analysis_is_otc,
    build_book_candidates,
)
from apps.screenshot_eval.constants import (
    RECOGNITION_METRIC_SCOPE,
    RECOGNITION_SEPARATION,
)
from apps.screenshot_eval.models import (
    ScreenshotCase,
    ScreenshotRecognition,
    ScreenshotRecognitionRun,
)

RECOGNITION_DISCLAIMER = (
    RECOGNITION_SEPARATION
    + " A recognised pattern is an observation, never a trade: decision is "
    "always NO_TRADE and probability is unavailable (uncalibrated)."
)


@dataclass(slots=True)
class RecognitionOutcome:
    """Result of one recognition pass (chemistry-free, JSON-serialisable)."""

    run: ScreenshotRecognitionRun
    recognitions: list[ScreenshotRecognition]
    candidates: list[dict[str, Any]]


def _configured_strategy_keys() -> list[str]:
    """Keys the evaluator will attempt: every implemented detector.

    Screenshot evaluation runs the *deterministic* detectors (the implemented
    specs) plus the vision mapper. Catalogued-only entries surface through the
    mapper when a vision label maps to them.
    """
    return sorted(IMPLEMENTED_SPEC_KEYS)


class ScreenshotRecognitionService:
    """Run and persist recognition over a screenshot case."""

    def __init__(self) -> None:
        self._recognizer = BookStrategyRecognizer()

    @transaction.atomic
    def run(
        self,
        *,
        case: ScreenshotCase,
        owner,
        candles: list[dict[str, Any]] | None = None,
        data_source: str = "",
        feed_market_type: str = "",
    ) -> RecognitionOutcome:
        """Evaluate a case and persist one run + per-strategy recognitions.

        ``candles`` are optional: when a compatible candle series is supplied
        (matched externally via the sync session) the deterministic detectors
        run; without candles the run records the vision-mapper candidates only.
        Nothing is ever fabricated to fill a gap.
        """
        analysis = case.screenshot.analyses.order_by("-created_at").first()
        screenshot_is_otc = case.market_type == "otc" or (
            analysis is not None and analysis_is_otc(analysis)
        )

        run = ScreenshotRecognitionRun.objects.create(
            case=case,
            analysis=analysis,
            owner=owner,
            ohlc_available=bool(candles),
            data_source=data_source,
            market_type=case.market_type,
            disclaimer=RECOGNITION_DISCLAIMER,
        )

        recognitions: list[ScreenshotRecognition] = []
        evaluated_keys: list[str] = []
        if candles:
            for key in _configured_strategy_keys():
                detection = self._recognizer.evaluate(
                    key,
                    candles,
                    instrument=case.instrument,
                    timeframe=case.timeframe,
                    market_type=case.market_type,
                    feed_market_type=feed_market_type,
                    screenshot_is_otc=screenshot_is_otc,
                    analysis=analysis,
                    persist=False,
                )
                recognitions.append(
                    self._to_row(run, case, detection)
                )
                evaluated_keys.append(key)

        candidates = build_book_candidates(analysis) if analysis is not None else []
        candidate_dicts = [c.as_dict() | {"strategy_key": c.strategy_key} for c in candidates]
        # Vision-mapper candidates for strategies not already covered by a
        # deterministic row are persisted too (as screenshot-only observations).
        covered = {r.strategy_key for r in recognitions}
        for candidate in candidates:
            if candidate.strategy_key in covered:
                continue
            spec = SPEC_BY_KEY.get(candidate.strategy_key)
            row = ScreenshotRecognition.objects.create(
                run=run,
                strategy_key=candidate.strategy_key,
                strategy_id=candidate.as_dict()["strategy_id"],
                strategy_name=candidate.strategy_name,
                book_number=spec.number if spec else 0,
                recognition_state=candidate.state,
                direction="neutral",
                observed_evidence=list(candidate.evidence),
                missing_conditions=list(candidate.missing_conditions),
                invalidation_evidence=[],
                data_verification=candidate.data_verification,
                matches_label=self._matches_label(case, candidate.strategy_key),
                probability=None,
            )
            recognitions.append(row)
            evaluated_keys.append(candidate.strategy_key)

        run.strategies_evaluated = sorted(set(evaluated_keys))
        run.summary = {
            "metric_scope": RECOGNITION_METRIC_SCOPE,
            "n_recognitions": len(recognitions),
            "ohlc_available": bool(candles),
            "state_counts": self._state_counts(recognitions),
        }
        run.save(update_fields=["strategies_evaluated", "summary", "updated_at"])
        return RecognitionOutcome(run=run, recognitions=recognitions, candidates=candidate_dicts)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _to_row(
        run: ScreenshotRecognitionRun,
        case: ScreenshotCase,
        detection: BookDetection,
    ) -> ScreenshotRecognition:
        return ScreenshotRecognition.objects.create(
            run=run,
            strategy_key=detection.strategy_key,
            strategy_id=detection.strategy_id,
            strategy_name=detection.strategy_name,
            book_number=detection.book_pattern_number,
            recognition_state=detection.recognition_status,
            direction=detection.direction,
            observed_evidence=list(detection.observed_evidence),
            missing_conditions=list(detection.missing_conditions),
            invalidation_evidence=list(detection.invalidations),
            contradictions=list(detection.contradictions),
            candle_refs=list(detection.candle_refs),
            reference_level=detection.reference_level,
            data_verification=detection.data_verification,
            matches_label=ScreenshotRecognitionService._matches_label(
                case, detection.strategy_key
            ),
            decision=detection.decision,
            probability=None,
            probability_status=detection.probability_status,
        )

    @staticmethod
    def _matches_label(case: ScreenshotCase, strategy_key: str) -> bool | None:
        """Whether a recognition matches the case's human label.

        Returns ``None`` for unreviewed cases (no ground truth) - never guesses.
        """
        if case.review_state not in ("confirmed", "corrected"):
            return None
        recognised = strategy_key in set(case.expected_strategy_keys or [])
        return recognised

    @staticmethod
    def _state_counts(rows: list[ScreenshotRecognition]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.recognition_state] = counts.get(row.recognition_state, 0) + 1
        return counts


__all__ = [
    "RECOGNITION_DISCLAIMER",
    "RecognitionOutcome",
    "ScreenshotRecognitionService",
]
