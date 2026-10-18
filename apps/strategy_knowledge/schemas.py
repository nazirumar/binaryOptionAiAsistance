# apps/strategy_knowledge/schemas.py
"""Validation helpers for structured strategy rules.

Only whitelisted, scalar-valued keys are accepted inside condition ``params``.
Anything else — nested code, callables, expressions — is rejected, so content
stored in the database can never be evaluated as logic.
"""

from __future__ import annotations

from typing import Any

#: Whitelisted param keys → (type, minimum, maximum). Windows/thresholds only.
ALLOWED_PARAMS: dict[str, tuple[str, float | None, float | None]] = {
    "min_wick_ratio": ("float", 0.0, 1.0),
    "max_body_ratio": ("float", 0.0, 1.0),
    "min_body_ratio": ("float", 0.0, 1.0),
    "min_touches": ("int", 2, 50),
    "lookback": ("int", 1, 200),
    "window": ("int", 1, 100),
    "retest_window": ("int", 1, 50),
    "min_leg_ratio": ("float", 0.0, 10.0),
    "retracement_min": ("float", 0.0, 1.0),
    "retracement_max": ("float", 0.0, 2.0),
    "tolerance": ("float", 0.0, 0.1),
    "min_range_multiple": ("float", 0.0, 20.0),
    "min_distance_ratio": ("float", 0.0, 1.0),
}

_MAX_PARAMS = 24


def validate_condition_params(params: Any) -> list[str]:
    """Return a list of problems (empty when valid).

    Accepts ``{}``/``None``; rejects non-dict containers, unknown keys,
    non-scalar values and out-of-range numbers.
    """
    if params in (None, ""):
        return []
    if not isinstance(params, dict):
        return ["params must be a JSON object of scalar thresholds"]
    errors: list[str] = []
    if len(params) > _MAX_PARAMS:
        errors.append(f"too many params (max {_MAX_PARAMS})")
    for key, value in params.items():
        if key not in ALLOWED_PARAMS:
            errors.append(f"unknown param key {key!r}")
            continue
        expected, low, high = ALLOWED_PARAMS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"param {key!r} must be a number")
            continue
        if low is not None and value < low:
            errors.append(f"param {key!r} must be >= {low}")
        if high is not None and value > high:
            errors.append(f"param {key!r} must be <= {high}")
        if expected == "int" and isinstance(value, float) and not value.is_integer():
            errors.append(f"param {key!r} must be an integer")
    return errors


def params_get(params: dict[str, Any] | None, key: str, default: Any) -> Any:
    """Fetch a validated param, falling back to ``default`` on any surprise."""
    if not isinstance(params, dict):
        return default
    value = params.get(key, default)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


__all__ = ["ALLOWED_PARAMS", "params_get", "validate_condition_params"]
