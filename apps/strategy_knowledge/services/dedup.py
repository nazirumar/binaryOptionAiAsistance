"""CP10: de-duplicate overlapping strategy candidates / detections.

When several strategies match the same candles — which is normal (an engulfing
at support is both a candlestick pattern and a level setup) — the recognition
layer must not present them as independent findings. This module groups
overlapping candidates and keeps one *primary* while recording the others as
related, so nothing is lost and nothing is double-counted.

Overlap is computed from candle references; strategies without candle refs are
grouped by (strategy family, direction) so a screenshot of one candle never
produces ten "independent" bullets.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from apps.strategy_knowledge.services.candidate_mapper import StrategyCandidate


@dataclass(slots=True)
class CandidateGroup:
    """A primary candidate plus the candidates it absorbs."""

    primary: StrategyCandidate
    related: list[StrategyCandidate] = field(default_factory=list)
    overlap_reason: str = ""

    @property
    def strategy_ids(self) -> list[str]:
        return [self.primary.strategy_id] + [c.strategy_id for c in self.related]


def _family(strategy_id: str) -> str:
    return strategy_id.split(".", 1)[0] if "." in strategy_id else strategy_id


def _refs_set(candidate: StrategyCandidate) -> frozenset[Any]:
    try:
        return frozenset(candidate.candle_refs or [])
    except TypeError:  # unhashable contents: fall back to no-ref grouping
        return frozenset()


def _overlaps(a: StrategyCandidate, b: StrategyCandidate) -> tuple[bool, str]:
    refs_a, refs_b = _refs_set(a), _refs_set(b)
    if refs_a and refs_b and refs_a & refs_b:
        return True, "shared_candles"
    if (
        not refs_a
        and not refs_b
        and _family(a.strategy_id) == _family(b.strategy_id)
        and a.direction == b.direction
    ):
        return True, "same_family_and_direction"
    return False, ""


def _priority(candidate: StrategyCandidate) -> tuple[int, float]:
    """Lower sorts first: deterministic-confirmed first, then higher confidence."""
    confirmed_rank = 0 if candidate.requires_ohlc_confirmation else 1
    confidence = candidate.confidence if candidate.confidence is not None else 0.0
    return (confirmed_rank, -confidence)


def dedupe_candidates(
    candidates: Iterable[StrategyCandidate],
) -> list[CandidateGroup]:
    """Group overlapping candidates; each group keeps one primary.

    Within a group the primary is chosen deterministically: candidates whose
    deterministic verification is pending (``requires_ohlc_confirmation``) are
    preferred over purely vision-derived ones, then by vision confidence. The
    ``related`` list preserves every absorbed candidate with its own labels.
    """
    remaining = sorted(candidates, key=_priority)
    groups: list[CandidateGroup] = []
    while remaining:
        candidate = remaining.pop(0)
        group = CandidateGroup(primary=candidate)
        still: list[StrategyCandidate] = []
        for other in remaining:
            overlaps, reason = _overlaps(candidate, other)
            if overlaps:
                group.related.append(other)
                group.overlap_reason = group.overlap_reason or reason
            else:
                still.append(other)
        remaining = still
        groups.append(group)
    return groups


def merge_detections(
    detections: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge persisted-detection dicts that reference overlapping candles.

    Same rules as :func:`dedupe_candidates` but for plain dicts (used by the
    API/serialization layer). The merged record records ``merged_into`` so the
    dashboard can render one primary with sub-observations.
    """
    items = list(detections)
    used: set[int] = set()
    merged: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        if i in used:
            continue
        refs = frozenset(item.get("candle_refs") or [])
        family = str(item.get("strategy_id", "")).split(".", 1)[0]
        group_members: list[dict[str, Any]] = []
        for j in range(i + 1, len(items)):
            if j in used:
                continue
            other = items[j]
            other_refs = frozenset(other.get("candle_refs") or [])
            other_family = str(other.get("strategy_id", "")).split(".", 1)[0]
            same_candles = bool(refs and other_refs and refs & other_refs)
            same_family = (
                not refs
                and not other_refs
                and family == other_family
                and item.get("direction") == other.get("direction")
            )
            if same_candles or same_family:
                used.add(j)
                group_members.append(other)
        record = dict(item)
        record["merged"] = group_members
        record["merged_count"] = len(group_members) + 1
        merged.append(record)
    return merged
