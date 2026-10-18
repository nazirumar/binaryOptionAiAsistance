"""The versioned market-input schema (Step 3).

The schema is intentionally permissive about provenance (screenshot data may be
absent) but strict about the *numbers* it will hand to a detector: a candle that
does not satisfy ``low <= min(open, close) <= max(open, close) <= high`` is
rejected with an explicit warning rather than silently used.
"""

from __future__ import annotations

from typing import Any

from apps.price_action.constants import (
    PA_MARKET_INPUT_SCHEMA_VERSION,
    DataQuality,
    MarketType,
)
from apps.price_action.exceptions import SchemaValidationError
from apps.price_action.services.config import PriceActionConfig
from apps.price_action.services.dto import MarketInput, candles_from_dicts

#: A machine-readable description of the accepted payload. Kept as data (not
#: enforced by a heavyweight dependency) so the contract is easy to diff.
MARKET_INPUT_SCHEMA: dict[str, Any] = {
    "schema_version": PA_MARKET_INPUT_SCHEMA_VERSION,
    "type": "object",
    "required": ["candles"],
    "properties": {
        "canonical_instrument": {"type": "string"},
        "broker_symbol": {"type": "string"},
        "timeframe": {"type": "string"},
        "market_type": {"enum": [str(m) for m in MarketType]},
        "candles": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["open", "high", "low", "close"],
                "properties": {
                    "open": {"type": "number"},
                    "high": {"type": "number"},
                    "low": {"type": "number"},
                    "close": {"type": "number"},
                    "open_time": {"type": ["string", "null"]},
                    "complete": {"type": "boolean"},
                    "tick_volume": {"type": ["number", "null"]},
                    "real_volume": {"type": ["number", "null"]},
                },
            },
        },
        "screenshot_observations": {"type": "object"},
        "sync_status": {"type": "string"},
        "feed_compatibility": {"type": "string"},
    },
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_payload(payload: dict[str, Any]) -> list[str]:
    """Return a list of human-readable issues. An empty list means valid."""
    issues: list[str] = []
    if not isinstance(payload, dict):
        return ["payload must be a mapping"]
    candles = payload.get("candles")
    if candles is None:
        issues.append("missing required field: candles")
        return issues
    if not isinstance(candles, list):
        return ["candles must be a list"]
    for i, c in enumerate(candles):
        if not isinstance(c, dict):
            issues.append(f"candle[{i}] must be a mapping")
            continue
        for key in ("open", "high", "low", "close"):
            if not _is_number(c.get(key)):
                issues.append(f"candle[{i}].{key} must be numeric")
        if all(_is_number(c.get(k)) for k in ("open", "high", "low", "close")):
            high = float(c["high"])
            low = float(c["low"])
            top = max(float(c["open"]), float(c["close"]))
            bottom = min(float(c["open"]), float(c["close"]))
            if high < low:
                issues.append(f"candle[{i}] high < low")
            if high < top:
                issues.append(f"candle[{i}] high below the body")
            if low > bottom:
                issues.append(f"candle[{i}] low above the body")
    return issues


def _quality_from_warnings(warnings: list[str], count: int) -> str:
    if count == 0:
        return DataQuality.UNUSABLE
    if not warnings:
        return DataQuality.HIGH
    if len(warnings) >= count:
        return DataQuality.LOW
    return DataQuality.MEDIUM


def build_market_input(
    payload: dict[str, Any],
    *,
    config: PriceActionConfig | None = None,
    strict: bool = False,
) -> MarketInput:
    """Construct a :class:`MarketInput` from a loose payload.

    When ``strict`` is true any schema issue raises :class:`SchemaValidationError`.
    Otherwise issues are collected as warnings and reflected in ``data_quality``.
    """
    config = config or PriceActionConfig.from_settings()
    issues = validate_payload(payload)
    if strict and issues:
        raise SchemaValidationError("; ".join(issues))

    raw_candles = payload.get("candles") or []
    if len(raw_candles) > config.max_candles:
        raw_candles = raw_candles[-config.max_candles :]

    candles = candles_from_dicts(raw_candles)
    warnings: list[str] = list(issues)
    if len(candles) < config.min_candles:
        warnings.append("insufficient candles for reliable detection")

    market_type = payload.get("market_type") or MarketType.UNKNOWN
    if str(market_type) not in {str(m) for m in MarketType}:
        warnings.append(f"unknown market_type: {market_type}")
        market_type = MarketType.UNKNOWN

    return MarketInput(
        canonical_instrument=str(payload.get("canonical_instrument", "")),
        broker_symbol=str(payload.get("broker_symbol", "")),
        timeframe=str(payload.get("timeframe", "")),
        market_type=str(market_type),
        candles=tuple(candles),
        screenshot_observations=dict(payload.get("screenshot_observations") or {}),
        sync_status=str(payload.get("sync_status", "")),
        feed_compatibility=str(payload.get("feed_compatibility", "")),
        data_quality=_quality_from_warnings(warnings, len(candles)),
        warnings=tuple(warnings),
        schema_version=PA_MARKET_INPUT_SCHEMA_VERSION,
    )


__all__ = [
    "MARKET_INPUT_SCHEMA",
    "build_market_input",
    "validate_payload",
]
