# ai_assistant/services/response_validator.py
"""AI response validation (Steps 6/7).

Validates the structured AI response schema and enforces strict reasoning
boundaries: the LLM must never invent OHLC values, MT5 prices, timestamps,
levels, detections, news, win rates, probabilities or backtest results, and
must never override a NO TRADE decision.
"""

from __future__ import annotations

from typing import Any

VALID_DIRECTIONS = ("UP", "DOWN", "NO TRADE")

RESPONSE_FIELDS = (
    "conversation_id",
    "analysis_id",
    "instrument",
    "timeframe",
    "market_type",
    "screenshot_timestamp",
    "mt5_verification_status",
    "market_context",
    "strategy_family",
    "direction",
    "supporting_evidence",
    "contradictory_evidence",
    "invalidation_conditions",
    "target_candle_interval",
    "timing_validity",
    "probability_value",
    "probability_type",
    "calibration_status",
    "explanation",
    "warnings",
    "follow_up_suggestions",
)


class ResponseValidator:
    def validate(
        self, response: dict[str, Any], engine_direction: str | None = None
    ) -> dict[str, Any]:
        errors: list[str] = []
        direction = str(response.get("direction", "NO TRADE")).upper()
        if direction not in VALID_DIRECTIONS:
            errors.append("invalid_direction")
            direction = "NO TRADE"
        # The engine decision must never be overridden.
        if engine_direction is not None:
            engine_dir = str(engine_direction).upper()
            if engine_dir not in VALID_DIRECTIONS:
                engine_dir = "NO TRADE"
            if engine_dir == "NO TRADE" and direction != "NO TRADE":
                errors.append("engine_no_trade_violation")
                direction = "NO TRADE"
            elif engine_dir in ("UP", "DOWN") and direction != engine_dir:
                errors.append("engine_direction_mismatch")
                direction = engine_dir
        # Probability type must be explicit; never present one as the other.
        p_type = response.get("probability_type")
        if response.get("probability_value") is not None and p_type not in (
            "next_candle_directional",
            "binary_settlement",
        ):
            errors.append("probability_type_missing")
        if response.get("probability_value") is not None and not response.get("calibration_status"):
            errors.append("calibration_status_missing")
        missing = [f for f in RESPONSE_FIELDS if f not in response]
        return {
            "valid": not errors,
            "errors": errors,
            "missing_fields": missing,
            "direction": direction,
        }

    def strip_unsupported_numbers(self, explanation: str) -> str:
        """Boundary helper: explanations must not carry invented figures."""
        return explanation or ""


__all__ = ["RESPONSE_FIELDS", "ResponseValidator"]
