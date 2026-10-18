"""CP10: multi-strategy recognition over one screenshot analysis.

Pipeline: vision records -> strategy candidates -> overlap de-duplication ->
deterministic verification -> persisted :class:`StrategyDetection` rows.

Guarantees enforced here:

* Every detection records ``provenance`` and the definition version applied.
* Overlapping candidates (same candles / same family) are merged instead of
  double-counted; absorbed candidates land in ``deduped_from``.
* Experimental/unapproved definitions are never hidden — they are recognised
  only when explicitly enabled and always carry their validation status in
  ``metadata``.
* Nothing in this module predicts a next candle or influences a trade; it only
  records what was observed and how well it was verified.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from apps.chart_vision.models import ScreenshotAnalysis
from apps.price_action.services.config import PriceActionConfig
from apps.strategy_knowledge.services.candidate_mapper import (
    build_candidates,
)
from apps.strategy_knowledge.services.dedup import CandidateGroup, dedupe_candidates
from apps.strategy_knowledge.services.pattern_verification import (
    PatternVerificationService,
    VerificationResult,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecognitionOutcome:
    """Result of recognising strategies on one analysis."""

    analysis: ScreenshotAnalysis
    candidate_count: int = 0
    group_count: int = 0
    results: list[VerificationResult] = field(default_factory=list)
    groups: list[CandidateGroup] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis.pk,
            "candidate_count": self.candidate_count,
            "group_count": self.group_count,
            "status_counts": self.status_counts,
            "detections": [
                {
                    "strategy_id": r.definition.strategy_id,
                    "status": r.status,
                    "provenance": r.provenance,
                    "direction": r.direction,
                    "validation_status": r.definition.validation_status,
                    "otc_incompatible": r.otc_incompatible,
                    "missing_conditions": r.missing_conditions,
                }
                for r in self.results
            ],
            "notes": self.notes,
        }


class MultiStrategyRecognitionService:
    """Recognise several strategies on one analysis without double-counting."""

    def __init__(self, *, config: PriceActionConfig | None = None) -> None:
        self.config = config or PriceActionConfig.from_settings()
        self.verifier = PatternVerificationService(config=self.config)

    def recognize(
        self,
        analysis: ScreenshotAnalysis,
        *,
        candles: list[dict[str, Any]] | None = None,
        candles_market_type: str = "",
    ) -> RecognitionOutcome:
        """Run the full CP8 -> CP10 -> CP9 pipeline for one analysis.

        ``candles`` are *verified* OHLC rows (e.g. from MT5). When they are not
        supplied — or the screenshot is OTC while the feed is not — verification
        stays screenshot-only and every status is capped at ``possible``.
        """
        outcome = RecognitionOutcome(analysis=analysis)
        candidates = build_candidates(analysis)
        outcome.candidate_count = len(candidates)
        if not candidates:
            outcome.notes.append("no strategy candidates matched the vision output")
            return outcome

        groups = dedupe_candidates(candidates)
        outcome.groups = groups
        outcome.group_count = len(groups)

        # Verify each group's primary; absorb the related candidates' labels so
        # nothing is lost and nothing is counted twice.
        for group in groups:
            results = self.verifier.verify(
                analysis,
                [group.primary],
                candles=candles,
                candles_market_type=candles_market_type,
            )
            if not results:
                continue
            result = results[0]
            if group.related:
                result.evidence.append(
                    {
                        "label": "merged_overlapping_candidates",
                        "source": "deterministic",
                        "satisfied": True,
                        "detail": (
                            f"overlap={group.overlap_reason}; absorbed: "
                            + ", ".join(c.strategy_id for c in group.related)
                        ),
                    }
                )
                # Record absorption on the persisted detection so the dashboard
                # can render one primary with its sub-observations.
                detection = (
                    analysis.strategy_detections.filter(definition=result.definition)
                    .order_by("-created_at")
                    .first()
                )
                if detection is not None:
                    detection.deduped_from = [
                        {
                            "strategy_id": c.strategy_id,
                            "source_label": c.source_label,
                            "source_kind": c.source_kind,
                            "overlap_reason": group.overlap_reason,
                        }
                        for c in group.related
                    ]
                    detection.save(update_fields=["deduped_from", "updated_at"])
            outcome.results.append(result)

        if any(r.definition.validation_status == "experimental" for r in outcome.results):
            outcome.notes.append(
                "experimental definitions were recognised; they are labelled "
                "and never usable as validated knowledge"
            )
        return outcome


__all__ = ["MultiStrategyRecognitionService", "RecognitionOutcome"]
