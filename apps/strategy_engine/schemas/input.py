# apps/strategy_engine/schemas/input.py
"""Strategy evaluation input schema (Step 3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from apps.strategy_engine.constants import (
    STRATEGY_INPUT_SCHEMA_VERSION,
)
from apps.strategy_engine.exceptions import InvalidStrategyInputError


@dataclass(frozen=True, slots=True)
class StrategyInput:
    """Versioned input for strategy evaluation."""

    screenshot_analysis_id: int | None = None
    screenshot_metadata: dict[str, Any] = field(default_factory=dict)
    sync_session_id: int | None = None
    instrument: str = ""
    timeframe: str = ""
    market_type: str = ""
    otc_status: str | None = None
    mt5_snapshot: dict[str, Any] = field(default_factory=dict)
    sync_status: str = ""
    data_freshness: str = ""
    completed_candles: tuple[dict[str, Any], ...] = ()
    all_candles: tuple[dict[str, Any], ...] = ()
    price_action_result: dict[str, Any] = field(default_factory=dict)
    screenshot_observations: dict[str, Any] = field(default_factory=dict)
    detected_patterns: list[dict[str, Any]] = field(default_factory=list)
    market_structure: dict[str, Any] = field(default_factory=dict)
    support_resistance_zones: list[dict[str, Any]] = field(default_factory=list)
    market_cycle_observations: list[dict[str, Any]] = field(default_factory=list)
    liquidity_observations: list[dict[str, Any]] = field(default_factory=list)
    volume_observations: list[dict[str, Any]] = field(default_factory=list)
    session_context: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    schema_version: str = STRATEGY_INPUT_SCHEMA_VERSION
    evaluation_timestamp: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "screenshot_analysis_id": self.screenshot_analysis_id,
            "screenshot_metadata": dict(self.screenshot_metadata),
            "sync_session_id": self.sync_session_id,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "market_type": self.market_type,
            "otc_status": self.otc_status,
            "mt5_snapshot": dict(self.mt5_snapshot),
            "sync_status": self.sync_status,
            "data_freshness": self.data_freshness,
            "completed_candles": list(self.completed_candles),
            "all_candles": list(self.all_candles),
            "price_action_result": dict(self.price_action_result),
            "screenshot_observations": dict(self.screenshot_observations),
            "detected_patterns": list(self.detected_patterns),
            "market_structure": dict(self.market_structure),
            "support_resistance_zones": list(self.support_resistance_zones),
            "market_cycle_observations": list(self.market_cycle_observations),
            "liquidity_observations": list(self.liquidity_observations),
            "volume_observations": list(self.volume_observations),
            "session_context": dict(self.session_context),
            "warnings": list(self.warnings),
            "schema_version": self.schema_version,
            "evaluation_timestamp": self.evaluation_timestamp.isoformat()
            if self.evaluation_timestamp
            else None,
        }

    @property
    def evidence(self) -> list[dict[str, Any]]:
        return list(self.price_action_result.get("evidence", []))

    @property
    def conflicts(self) -> list[dict[str, Any]]:
        return list(self.price_action_result.get("conflicts", []))

    @property
    def context(self) -> dict[str, Any]:
        return dict(self.price_action_result.get("context", {}))

    def has_completed_candles(self) -> bool:
        return len(self.completed_candles) > 0

    def get_completed_candles_list(self) -> list[dict[str, Any]]:
        return list(self.completed_candles)

    def get_all_candles_list(self) -> list[dict[str, Any]]:
        return list(self.all_candles)


def build_strategy_input(
    data: dict[str, Any], *, evaluation_timestamp: datetime | None = None
) -> StrategyInput:
    """Build StrategyInput from raw data."""
    warnings: list[str] = []

    completed = data.get("completed_candles") or data.get("candles") or []
    all_candles = data.get("all_candles") or completed

    if not completed:
        warnings.append("No completed candles provided")

    strategy_input = StrategyInput(
        screenshot_analysis_id=data.get("screenshot_analysis_id"),
        screenshot_metadata=data.get("screenshot_metadata") or {},
        sync_session_id=data.get("sync_session_id"),
        instrument=data.get("instrument", ""),
        timeframe=data.get("timeframe", ""),
        market_type=data.get("market_type", ""),
        otc_status=data.get("otc_status"),
        mt5_snapshot=data.get("mt5_snapshot") or {},
        sync_status=data.get("sync_status", ""),
        data_freshness=data.get("data_freshness", ""),
        completed_candles=tuple(completed),
        all_candles=tuple(all_candles),
        price_action_result=data.get("price_action_result") or {},
        screenshot_observations=data.get("screenshot_observations") or {},
        detected_patterns=data.get("detected_patterns") or [],
        market_structure=data.get("market_structure") or {},
        support_resistance_zones=data.get("support_resistance_zones") or [],
        market_cycle_observations=data.get("market_cycle_observations") or [],
        liquidity_observations=data.get("liquidity_observations") or [],
        volume_observations=data.get("volume_observations") or [],
        session_context=data.get("session_context") or {},
        warnings=tuple(warnings),
        evaluation_timestamp=evaluation_timestamp,
    )

    if not strategy_input.has_completed_candles():
        raise InvalidStrategyInputError("Strategy input requires completed candles")

    return strategy_input


__all__ = ["StrategyInput", "build_strategy_input"]
