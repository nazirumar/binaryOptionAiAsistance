"""Conflict detection (Step 21).

Takes the collected evidence and reports *structured* contradictions. Conflicts
are preserved, never resolved by inventing a probability: the caller sees both
sides and decides what to do in a later phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.price_action.constants import (
    ConflictType,
    Direction,
    EvidenceStatus,
    Severity,
)
from apps.price_action.services.evidence_registry import Evidence


@dataclass(frozen=True, slots=True)
class ConflictRecord:
    conflict_type: str
    severity: str
    explanation: str
    rule_a: str = ""
    rule_b: str = ""
    candle_refs: tuple[int, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_type": str(self.conflict_type),
            "severity": str(self.severity),
            "explanation": self.explanation,
            "rule_a": self.rule_a,
            "rule_b": self.rule_b,
            "candle_refs": list(self.candle_refs),
            "detail": dict(self.detail),
        }


def _detected(evidence: list[Evidence], detector: str) -> list[Evidence]:
    return [e for e in evidence if e.detector == detector and e.status == EvidenceStatus.DETECTED]


def _by_direction(evidence: list[Evidence], direction: str) -> list[Evidence]:
    return [e for e in evidence if e.direction == direction and e.status == EvidenceStatus.DETECTED]


def detect_conflicts(
    evidence: list[Evidence], context: dict[str, Any] | None = None
) -> list[ConflictRecord]:
    context = context or {}
    conflicts: list[ConflictRecord] = []

    bullish = _by_direction(evidence, Direction.BULLISH)
    bearish = _by_direction(evidence, Direction.BEARISH)
    if bullish and bearish:
        conflicts.append(
            ConflictRecord(
                conflict_type=ConflictType.OPPOSING_EVIDENCE,
                severity=Severity.WARNING,
                explanation="both bullish and bearish observations are present",
                rule_a=bullish[0].rule_id,
                rule_b=bearish[0].rule_id,
                detail={"bullish_count": len(bullish), "bearish_count": len(bearish)},
            )
        )

    # Bullish pattern after buyer failure / bearish pattern after seller failure.
    buyer_failures = _detected(evidence, "buyer_seller_failure")
    failures = [e for e in buyer_failures if "failed" in e.rule_id]
    if bullish and any("failed_to_break_resistance" in e.rule_id for e in failures):
        conflicts.append(
            ConflictRecord(
                conflict_type=ConflictType.BULLISH_AFTER_BUYER_FAILURE,
                severity=Severity.WARNING,
                explanation="a bullish observation appears alongside a recent buyer failure",
                rule_a=bullish[0].rule_id,
                rule_b=next(
                    e.rule_id for e in failures if "failed_to_break_resistance" in e.rule_id
                ),
            )
        )
    if bearish and any("failed_to_break_support" in e.rule_id for e in failures):
        conflicts.append(
            ConflictRecord(
                conflict_type=ConflictType.BEARISH_AFTER_SELLER_FAILURE,
                severity=Severity.WARNING,
                explanation="a bearish observation appears alongside a recent seller failure",
                rule_a=bearish[0].rule_id,
                rule_b=next(e.rule_id for e in failures if "failed_to_break_support" in e.rule_id),
            )
        )

    # Reversal pattern against a confirmed breakout.
    breakouts = [e for e in _detected(evidence, "support_resistance") if "breakout" in e.rule_id]
    reversals = [e for e in evidence if e.direction == "reversal"]
    if breakouts and reversals:
        conflicts.append(
            ConflictRecord(
                conflict_type=ConflictType.REVERSAL_AGAINST_BREAKOUT,
                severity=Severity.WARNING,
                explanation="a reversal observation opposes a confirmed breakout",
                rule_a=breakouts[0].rule_id,
                rule_b=reversals[0].rule_id,
            )
        )

    # SBR/RBS without a valid break (flagged by the detector's metrics).
    for e in _detected(evidence, "support_resistance"):
        if "sbr_rbs" in e.rule_id and e.metrics.get("valid_break") is False:
            conflicts.append(
                ConflictRecord(
                    conflict_type=ConflictType.SBR_RBS_WITHOUT_BREAK,
                    severity=Severity.ERROR,
                    explanation="SBR/RBS reported without a valid level break",
                    rule_a=e.rule_id,
                    candle_refs=e.candle_refs,
                )
            )

    # Liquidity sweep without recovery.
    for e in _detected(evidence, "liquidity_sweeps"):
        if e.metrics.get("closed_back_inside") is False:
            conflicts.append(
                ConflictRecord(
                    conflict_type=ConflictType.SWEEP_WITHOUT_RECOVERY,
                    severity=Severity.INFO,
                    explanation="a sweep did not recover back inside the prior range",
                    rule_a=e.rule_id,
                    candle_refs=e.candle_refs,
                )
            )

    # Pattern inside unresolved consolidation.
    if context.get("consolidation") and _detected(evidence, "candlestick_patterns"):
        pattern = _detected(evidence, "candlestick_patterns")[0]
        conflicts.append(
            ConflictRecord(
                conflict_type=ConflictType.PATTERN_IN_CONSOLIDATION,
                severity=Severity.INFO,
                explanation="a candlestick pattern formed inside an unresolved consolidation",
                rule_a=pattern.rule_id,
                candle_refs=pattern.candle_refs,
            )
        )

    # Unconfirmed pivot treated as confirmed.
    for e in evidence:
        if e.metrics.get("pivot_confirmed") is False:
            conflicts.append(
                ConflictRecord(
                    conflict_type=ConflictType.UNCONFIRMED_PIVOT,
                    severity=Severity.ERROR,
                    explanation="a pivot that is not yet confirmed was reported as usable",
                    rule_a=e.rule_id,
                    candle_refs=e.candle_refs,
                )
            )

    # Incompatible screenshot / MT5 observations.
    feed = str(context.get("feed_compatibility", ""))
    sync = str(context.get("sync_status", ""))
    feed_incompatible = bool(feed) and feed != "compatible"
    sync_incompatible = sync in ("data_mismatch", "incompatible_feed")
    if feed_incompatible or sync_incompatible:
        conflicts.append(
            ConflictRecord(
                conflict_type=ConflictType.SOURCE_INCOMPATIBLE,
                severity=Severity.ERROR,
                explanation="screenshot and market data feeds are not compatible",
                detail={"feed_compatibility": feed, "sync_status": sync},
            )
        )

    return conflicts


__all__ = ["ConflictRecord", "detect_conflicts"]
