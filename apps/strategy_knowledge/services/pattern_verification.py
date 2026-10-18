"""CP9: deterministic verification of vision strategy candidates.

Statuses (never assigned by an LLM):

* ``detected`` — the strategy's deterministic detector confirmed the pattern
  on verified OHLC candles.
* ``possible`` — a vision candidate exists but precise-price confirmation was
  not possible (no candles, incompatible feed, or OTC screenshot). Screenshot-
  only observations are never upgraded to ``detected``.
* ``rejected`` — the deterministic detector ran on compatible candles and did
  not find the pattern.
* ``insufficient_evidence`` — neither a usable detector result nor a vision
  candidate is available.

OTC guard: an OTC screenshot is never confirmed with normal-session MT5
prices; the result is capped at ``possible`` with ``otc_incompatible`` set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from apps.chart_vision.models import ScreenshotAnalysis
from apps.price_action.services.config import PriceActionConfig
from apps.strategy_knowledge.constants import (
    ConditionKind,
    ConditionSource,
    DetectionStatus,
    EvidenceProvenance,
)
from apps.strategy_knowledge.models import (
    StrategyCondition,
    StrategyDefinition,
    StrategyDetection,
    StrategyDetectionEvidence,
)
from apps.strategy_knowledge.registry import run_detector
from apps.strategy_knowledge.services.candidate_mapper import StrategyCandidate

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VerificationResult:
    """Outcome of verifying one candidate."""

    definition: StrategyDefinition
    status: str
    provenance: str
    direction: str = "neutral"
    confidence: float | None = None
    summary: str = ""
    missing_conditions: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    invalidation: list[str] = field(default_factory=list)
    requires_ohlc_confirmation: bool = False
    ohlc_confirmed: bool = False
    otc_incompatible: bool = False
    detector_observation: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)


class PatternVerificationService:
    """Verify vision strategy candidates against deterministic evidence."""

    def __init__(self, *, config: PriceActionConfig | None = None) -> None:
        self.config = config or PriceActionConfig.from_settings()

    # -- public API --------------------------------------------------------

    def verify(
        self,
        analysis: ScreenshotAnalysis,
        candidates: list[StrategyCandidate],
        *,
        candles: list[dict[str, Any]] | None = None,
        candles_market_type: str = "",
    ) -> list[VerificationResult]:
        """Verify every candidate, persisting one :class:`StrategyDetection` per result."""
        screenshot_otc = _analysis_is_otc(analysis)
        results: list[VerificationResult] = []
        for candidate in candidates:
            result = self._verify_one(
                candidate,
                candles=candles,
                candles_market_type=candles_market_type,
                screenshot_otc=screenshot_otc,
            )
            self._persist(analysis, candidate, result)
            results.append(result)
        return results

    # -- internals ---------------------------------------------------------

    def _verify_one(
        self,
        candidate: StrategyCandidate,
        *,
        candles: list[dict[str, Any]] | None,
        candles_market_type: str,
        screenshot_otc: bool,
    ) -> VerificationResult:
        definition = candidate.definition
        detector_key = definition.detector_key
        invalidation = list(
            StrategyCondition.objects.filter(
                definition=definition, kind=ConditionKind.INVALIDATION
            ).values_list("label", flat=True)
        )
        base = VerificationResult(
            definition=definition,
            status=str(DetectionStatus.POSSIBLE),
            provenance=str(EvidenceProvenance.SCREENSHOT_ONLY),
            direction=candidate.direction,
            summary=candidate.evidence_summary,
            missing_conditions=list(candidate.missing_conditions),
            invalidation=invalidation,
            requires_ohlc_confirmation=candidate.requires_ohlc_confirmation,
        )

        # OTC screenshot: MT5 normal-session prices can never confirm it.
        if screenshot_otc and candles:
            base.otc_incompatible = True
            base.status = str(DetectionStatus.POSSIBLE)
            base.provenance = str(EvidenceProvenance.SCREENSHOT_ONLY)
            base.summary = (
                base.summary + " | " if base.summary else ""
            ) + "OTC screenshot: not confirmable with normal-session OHLC"
            base.evidence.append(_evidence(candidate, ConditionSource.MISSING, False))
            return base

        if not detector_key:
            # Knowledge-only definition: the vision candidate stands as a
            # screenshot observation; nothing deterministic exists to run.
            base.status = str(DetectionStatus.POSSIBLE)
            base.evidence.append(_evidence(candidate, ConditionSource.VISION, True))
            return base

        if not candles:
            # No verified candles: cannot confirm or reject.
            base.status = (
                str(DetectionStatus.POSSIBLE)
                if candidate.confidence is not None
                else str(DetectionStatus.INSUFFICIENT)
            )
            base.missing_conditions = _dedupe([*base.missing_conditions, "verified OHLC candles"])
            base.evidence.append(_evidence(candidate, ConditionSource.MISSING, False))
            return base

        observation = run_detector(detector_key, candles, config=self.config)
        if observation is not None:
            base.status = str(DetectionStatus.DETECTED)
            base.provenance = str(EvidenceProvenance.OHLC)
            base.ohlc_confirmed = True
            base.confidence = None  # deterministic: no LLM confidence involved
            base.detector_observation = observation
            base.summary = (
                f"deterministic detector {detector_key} confirmed on "
                f"{len(candles)} verified candles"
            )
            base.evidence.append(_evidence(candidate, ConditionSource.DETERMINISTIC, True))
        else:
            base.status = str(DetectionStatus.REJECTED)
            base.provenance = str(EvidenceProvenance.OHLC)
            base.summary = (
                f"deterministic detector {detector_key} did not find the pattern "
                "on the verified candles"
            )
            base.evidence.append(_evidence(candidate, ConditionSource.DETERMINISTIC, False))
        return base

    def _persist(
        self,
        analysis: ScreenshotAnalysis,
        candidate: StrategyCandidate,
        result: VerificationResult,
    ) -> StrategyDetection:
        definition = result.definition
        detection = StrategyDetection.objects.create(
            analysis=analysis,
            definition=definition,
            definition_version=(definition.version.version if definition.version_id else ""),
            status=result.status,
            direction=result.direction,
            provenance=result.provenance,
            confidence=result.confidence,
            summary=result.summary,
            missing_conditions=result.missing_conditions,
            invalidation=result.invalidation,
            requires_ohlc_confirmation=result.requires_ohlc_confirmation,
            ohlc_confirmed=result.ohlc_confirmed,
            otc_incompatible=result.otc_incompatible,
            metadata={
                "source_kind": candidate.source_kind,
                "source_label": candidate.source_label,
                "result_path": candidate.result_path,
                "vision_confirmed": candidate.vision_confirmed,
                "detector_observation": result.detector_observation,
                "knowledge_validation_status": definition.validation_status,
            },
        )
        for item in result.evidence:
            StrategyDetectionEvidence.objects.create(
                detection=detection,
                condition_kind=ConditionKind.REQUIRED,
                label=item["label"],
                source=item["source"],
                satisfied=item["satisfied"],
                candle_refs=candidate.candle_refs,
                detail=item.get("detail", ""),
            )
        return detection


def _evidence(candidate: StrategyCandidate, source: str, satisfied: bool) -> dict[str, Any]:
    return {
        "label": f"vision candidate: {candidate.source_label}",
        "source": source,
        "satisfied": satisfied,
        "detail": (f"from {candidate.source_kind} record (confidence={candidate.confidence})"),
    }


def _analysis_is_otc(analysis: ScreenshotAnalysis) -> bool:
    metadata = (analysis.result or {}).get("chart_metadata") or {}
    status = str(metadata.get("otc_status", "") or "").lower()
    return "otc" in status


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
