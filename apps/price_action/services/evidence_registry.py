"""The evidence registry (Step 20).

Every detector appends :class:`Evidence` records here. The registry is
append-only and never deletes or rewrites an observation, so conflicting
evidence can coexist and be reported by the conflict detector (Step 21).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.price_action.constants import (
    PA_RULE_VERSION,
    DataQuality,
    Direction,
    EvidenceStatus,
)


@dataclass(frozen=True, slots=True)
class Evidence:
    """A single structured observation produced by one detector.

    The fields mirror the Phase 5 specification exactly so that the future
    strategy-evaluation engine can consume them without guessing.
    """

    rule_id: str
    detector: str
    status: str = EvidenceStatus.DETECTED
    direction: str = Direction.NEUTRAL
    explanation: str = ""
    rule_version: str = PA_RULE_VERSION
    #: Stable references to the candles that justify the observation.
    candle_refs: tuple[int, ...] = ()
    #: Price levels the observation refers to (zone bounds, gaps, swings...).
    supporting_levels: tuple[float, ...] = ()
    #: ISO-8601 timestamps of the referenced candles, when available.
    timestamps: tuple[str, ...] = ()
    #: Conditions that had to hold for the observation to be reported.
    required_conditions: tuple[str, ...] = ()
    #: Conditions under which the observation would be voided.
    invalidation_conditions: tuple[str, ...] = ()
    #: Inputs the detector needed but did not receive.
    missing_inputs: tuple[str, ...] = ()
    data_quality: str = DataQuality.MEDIUM
    #: Human-readable reasons, in evaluation order.
    reasons: tuple[str, ...] = ()
    #: Detector-specific numeric detail (kept machine-readable, never a
    #: probability of any future outcome).
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "detector": self.detector,
            "status": str(self.status),
            "direction": str(self.direction),
            "explanation": self.explanation,
            "candle_refs": list(self.candle_refs),
            "supporting_levels": list(self.supporting_levels),
            "timestamps": list(self.timestamps),
            "required_conditions": list(self.required_conditions),
            "invalidation_conditions": list(self.invalidation_conditions),
            "missing_inputs": list(self.missing_inputs),
            "data_quality": str(self.data_quality),
            "reasons": list(self.reasons),
            "metrics": dict(self.metrics),
        }


class EvidenceRegistry:
    """Append-only collection of :class:`Evidence` records."""

    def __init__(self) -> None:
        self._items: list[Evidence] = []

    def add(self, evidence: Evidence) -> Evidence:
        self._items.append(evidence)
        return evidence

    def extend(self, items: list[Evidence]) -> None:
        self._items.extend(items)

    def all(self) -> list[Evidence]:
        return list(self._items)

    def by_detector(self, detector: str) -> list[Evidence]:
        return [e for e in self._items if e.detector == detector]

    def by_status(self, status: str) -> list[Evidence]:
        return [e for e in self._items if e.status == status]

    def directions(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._items:
            counts[str(e.direction)] = counts.get(str(e.direction), 0) + 1
        return counts

    def to_dicts(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._items]


__all__ = ["Evidence", "EvidenceRegistry"]
