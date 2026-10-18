# apps/strategy_engine/schemas/output.py
"""Strategy evaluation output schema (Step 11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from apps.strategy_engine.constants import (
    STRATEGY_OUTPUT_SCHEMA_VERSION,
    EvaluationDirection,
    MarketContextState,
    ProbabilityStatus,
    StrategyFamily,
    TimingValidity,
)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A strategy candidate (bullish or bearish)."""

    direction: str
    strategy_family: str
    status: str
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    contradictory_evidence: list[dict[str, Any]] = field(default_factory=list)
    required_conditions: list[str] = field(default_factory=list)
    missing_conditions: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    candle_refs: list[int] = field(default_factory=list)
    price_levels: list[float] = field(default_factory=list)
    confluence_score: float | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "strategy_family": self.strategy_family,
            "status": self.status,
            "supporting_evidence": list(self.supporting_evidence),
            "contradictory_evidence": list(self.contradictory_evidence),
            "required_conditions": list(self.required_conditions),
            "missing_conditions": list(self.missing_conditions),
            "invalidation_conditions": list(self.invalidation_conditions),
            "candle_refs": list(self.candle_refs),
            "price_levels": list(self.price_levels),
            "confluence_score": self.confluence_score,
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class EvaluationOutput:
    """Strict output for strategy evaluation."""

    evaluation_id: str
    instrument: str = ""
    timeframe: str = ""
    market_type: str = ""
    target_candle_interval: str = ""
    direction: str = EvaluationDirection.NO_TRADE
    strategy_family: str = StrategyFamily.UNKNOWN
    market_context: str = MarketContextState.UNCERTAIN
    candidates: list[Candidate] = field(default_factory=list)
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    contradictory_evidence: list[dict[str, Any]] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    primary_reason_code: str = ""
    reason_codes: list[str] = field(default_factory=list)
    sync_status: str = ""
    feed_compatibility: str = ""
    timing_validity: str = TimingValidity.UNCERTAIN
    data_quality: str = ""
    data_freshness: str = ""
    confluence_score: float | None = None
    statistical_probability_status: str = ProbabilityStatus.UNAVAILABLE_UNCALIBRATED
    explanation: str = ""
    warnings: list[str] = field(default_factory=list)
    schema_version: str = STRATEGY_OUTPUT_SCHEMA_VERSION
    rule_version: str = "1.0"
    engine_config_version: str = "1.0"
    created_at: datetime | None = None
    signal_candle_open_time: datetime | None = None
    signal_candle_close_time: datetime | None = None
    target_candle_open_time: datetime | None = None
    target_candle_close_time: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "market_type": self.market_type,
            "target_candle_interval": self.target_candle_interval,
            "direction": self.direction,
            "strategy_family": self.strategy_family,
            "market_context": self.market_context,
            "candidates": [c.to_dict() for c in self.candidates],
            "supporting_evidence": list(self.supporting_evidence),
            "contradictory_evidence": list(self.contradictory_evidence),
            "invalidation_conditions": list(self.invalidation_conditions),
            "primary_reason_code": self.primary_reason_code,
            "reason_codes": list(self.reason_codes),
            "sync_status": self.sync_status,
            "feed_compatibility": self.feed_compatibility,
            "timing_validity": self.timing_validity,
            "data_quality": self.data_quality,
            "data_freshness": self.data_freshness,
            "confluence_score": self.confluence_score,
            "statistical_probability_status": self.statistical_probability_status,
            "explanation": self.explanation,
            "warnings": list(self.warnings),
            "schema_version": self.schema_version,
            "rule_version": self.rule_version,
            "engine_config_version": self.engine_config_version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "signal_candle_open_time": self.signal_candle_open_time.isoformat()
            if self.signal_candle_open_time
            else None,
            "signal_candle_close_time": self.signal_candle_close_time.isoformat()
            if self.signal_candle_close_time
            else None,
            "target_candle_open_time": self.target_candle_open_time.isoformat()
            if self.target_candle_open_time
            else None,
            "target_candle_close_time": self.target_candle_close_time.isoformat()
            if self.target_candle_close_time
            else None,
        }


__all__ = ["Candidate", "EvaluationOutput"]
