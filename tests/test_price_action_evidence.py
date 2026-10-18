"""Tests for the evidence registry and the conflict detector (Steps 20-21)."""

from __future__ import annotations

from apps.price_action.constants import (
    ConflictType,
    DataQuality,
    Direction,
    EvidenceStatus,
    Severity,
)
from apps.price_action.services.conflict_detector import detect_conflicts
from apps.price_action.services.evidence_registry import Evidence, EvidenceRegistry


def _ev(rule_id: str, detector: str, direction: str, **kwargs) -> Evidence:
    return Evidence(
        rule_id=rule_id,
        detector=detector,
        direction=direction,
        status=kwargs.pop("status", EvidenceStatus.DETECTED),
        **kwargs,
    )


def test_registry_append_only_and_query():
    reg = EvidenceRegistry()
    reg.add(_ev("a", "d1", Direction.BULLISH))
    reg.add(_ev("b", "d2", Direction.BEARISH))
    assert len(reg.all()) == 2
    assert len(reg.by_detector("d1")) == 1
    assert len(reg.by_status(EvidenceStatus.DETECTED)) == 2
    assert reg.directions() == {"bullish": 1, "bearish": 1}
    assert all("rule_id" in d for d in reg.to_dicts())


def test_evidence_to_dict_round_trips_fields():
    e = _ev(
        "a",
        "d1",
        Direction.BULLISH,
        candle_refs=(1, 2),
        supporting_levels=(1.0,),
        reasons=("because",),
        metrics={"k": 1},
    )
    d = e.to_dict()
    assert d["candle_refs"] == [1, 2]
    assert d["supporting_levels"] == [1.0]
    assert d["data_quality"] == DataQuality.MEDIUM


def test_opposing_evidence_conflict():
    evidence = [
        _ev("pa.candle.hammer", "candlestick_patterns", Direction.BULLISH),
        _ev("pa.sr.zone.resistance", "support_resistance", Direction.BEARISH),
    ]
    conflicts = detect_conflicts(evidence)
    assert any(c.conflict_type == ConflictType.OPPOSING_EVIDENCE for c in conflicts)


def test_bullish_after_buyer_failure_conflict():
    evidence = [
        _ev("pa.candle.hammer", "candlestick_patterns", Direction.BULLISH),
        _ev(
            "pa.bsf.buyers_failed_to_break_resistance",
            "buyer_seller_failure",
            Direction.BEARISH,
        ),
    ]
    conflicts = detect_conflicts(evidence)
    assert any(c.conflict_type == ConflictType.BULLISH_AFTER_BUYER_FAILURE for c in conflicts)


def test_sweep_without_recovery_conflict():
    evidence = [
        _ev(
            "pa.sweep.high_sweep",
            "liquidity_sweeps",
            Direction.BEARISH,
            metrics={"closed_back_inside": False},
        )
    ]
    conflicts = detect_conflicts(evidence)
    assert any(c.conflict_type == ConflictType.SWEEP_WITHOUT_RECOVERY for c in conflicts)


def test_unconfirmed_pivot_conflict():
    evidence = [
        _ev(
            "pa.structure.trend",
            "market_structure",
            Direction.NEUTRAL,
            metrics={"pivot_confirmed": False},
        )
    ]
    conflicts = detect_conflicts(evidence)
    assert any(c.conflict_type == ConflictType.UNCONFIRMED_PIVOT for c in conflicts)
    assert all(c.severity == Severity.ERROR for c in conflicts if "pivot" in c.conflict_type)


def test_source_incompatible_conflict():
    conflicts = detect_conflicts([], {"feed_compatibility": "incompatible_feed"})
    assert any(c.conflict_type == ConflictType.SOURCE_INCOMPATIBLE for c in conflicts)


def test_no_conflicts_for_consistent_evidence():
    evidence = [_ev("pa.candle.hammer", "candlestick_patterns", Direction.BULLISH)]
    assert detect_conflicts(evidence) == []


def test_conflict_to_dict():
    conflicts = detect_conflicts(
        [_ev("a", "d", Direction.BULLISH), _ev("b", "e", Direction.BEARISH)]
    )
    d = conflicts[0].to_dict()
    assert {"conflict_type", "severity", "explanation", "rule_a", "rule_b"} <= set(d)
