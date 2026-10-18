"""Strict validation + normalisation of the versioned structured output.

The vision model returns free text; this module turns it into a *validated*
result. It enforces the v1 schema, coerces enums to canonical values, clamps
observation confidence to ``[0, 1]`` and **rejects fabricated prices and
probabilities**: numeric candle OHLC fields are stripped with a warning, and any
probability / win-rate / prediction field is a hard error so no fabricated
trading odds can ever be surfaced.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from apps.chart_vision.constants import (
    SCHEMA_VERSION,
    UNKNOWN,
    CandleClassification,
    ChartOrientation,
    ConfidenceBand,
    OTCStatus,
    PatternCategory,
    PatternDirection,
    ScreenshotQuality,
    SizeBand,
    Trend,
    ZoneType,
)
from apps.chart_vision.services.exceptions import SchemaValidationError

REQUIRED_TOP_LEVEL = (
    "analysis_status",
    "screenshot_quality",
    "chart_metadata",
    "candles",
    "market_structure",
    "support_resistance",
    "patterns",
    "sequence_observations",
    "market_cycle",
    "liquidity",
    "volume",
    "missing_information",
    "warnings",
    "observation_confidence",
)

ANALYSIS_STATUSES = {"completed", "partial", "insufficient_evidence"}

#: Keys that would imply a fabricated trading probability / prediction.
_FORBIDDEN_KEY_PATTERN = re.compile(
    r"^(probabilit(y|ies)|win_?rate|success_?rate|accuracy|prediction|predictions|"
    r"up_probability|down_probability|expected_value|edge|signal)$",
    re.IGNORECASE,
)

#: Numeric price keys that must never be invented from pixels.
_FORBIDDEN_CANDLE_PRICE_KEYS = {
    "open",
    "high",
    "low",
    "close",
    "o",
    "h",
    "l",
    "c",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
}

_ENUM_SETS = {
    "classification": set(CandleClassification.values),
    "body_size": set(SizeBand.values),
    "upper_wick": set(SizeBand.values),
    "lower_wick": set(SizeBand.values),
    "rating": set(ScreenshotQuality.values),
    "orientation": set(ChartOrientation.values),
    "otc_status": set(OTCStatus.values),
    "trend": set(Trend.values),
    "direction": set(PatternDirection.values),
    "zone_type": set(ZoneType.values),
    "category": set(PatternCategory.values),
    "band": set(ConfidenceBand.values),
}


@dataclass(slots=True)
class SchemaValidationResult:
    """Outcome of validating a provider payload."""

    valid: bool
    payload: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_json_object(raw_text: str) -> dict[str, Any]:
    """Extract a JSON object from provider text (tolerating code fences).

    Raises :class:`~apps.chart_vision.services.exceptions.SchemaValidationError`
    when no JSON object can be found or decoded.
    """
    if raw_text is None or not str(raw_text).strip():
        raise SchemaValidationError("Provider returned no content.")
    text = str(raw_text).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        decoded = json.loads(text)
    except ValueError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise SchemaValidationError("Provider response contained no JSON object.") from None
        try:
            decoded = json.loads(text[start : end + 1])
        except ValueError as exc:
            raise SchemaValidationError(f"Provider JSON could not be decoded: {exc}") from exc
    if not isinstance(decoded, dict):
        raise SchemaValidationError("Provider JSON was not an object.")
    return decoded


def _find_forbidden_keys(node: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if _FORBIDDEN_KEY_PATTERN.match(str(key)):
                found.append(child)
            found.extend(_find_forbidden_keys(value, child))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(_find_forbidden_keys(item, f"{path}[{index}]"))
    return found


def _as_float(value: Any, *, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _confidence(value: Any) -> float | None:
    number = _as_float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number))


def _as_bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, "", UNKNOWN):
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes"}:
            return True
        if lowered in {"false", "no"}:
            return False
    return None


def _enum(value: Any, field_name: str, *, default: str, warnings: list[str]) -> str:
    choices = _ENUM_SETS.get(field_name, set())
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in choices:
            return candidate
    if value in (None, "", UNKNOWN):
        return default
    warnings.append(f"{field_name!r} value {value!r} is not recognised; using {default!r}.")
    return default


def _as_string(value: Any, *, default: str = UNKNOWN) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or default
    if isinstance(value, (int, float)):
        return str(value)
    return default


def _as_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    if isinstance(value, str):
        try:
            return round(float(value.strip()))
        except ValueError:
            return None
    return None


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value in (None, "", UNKNOWN):
        return []
    return [value]


def _strip_candle_prices(candle: dict, warnings: list[str]) -> dict:
    cleaned = {}
    removed = False
    for key, value in candle.items():
        if str(key).lower() in _FORBIDDEN_CANDLE_PRICE_KEYS and isinstance(value, (int, float)):
            removed = True
            continue
        cleaned[key] = value
    if removed:
        warnings.append(
            "Numeric candle OHLC price fields were removed (prices are never inferred from pixels)."
        )
    return cleaned


def _normalize_candle(index: int, raw: Any, warnings: list[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        warnings.append(f"Candle #{index} was not an object and was skipped.")
        return {
            "index": index,
            "classification": CandleClassification.UNKNOWN,
            "confidence": None,
        }
    candle = _strip_candle_prices(raw, warnings)
    return {
        "index": _as_int_or_none(candle.get("index", index)) or index,
        "position": _as_string(candle.get("position"), default=UNKNOWN),
        "classification": _enum(
            candle.get("classification"),
            "classification",
            default=CandleClassification.UNKNOWN,
            warnings=warnings,
        ),
        "body_size": _enum(
            candle.get("body_size"), "body_size", default=SizeBand.UNKNOWN, warnings=warnings
        ),
        "upper_wick": _enum(
            candle.get("upper_wick"), "upper_wick", default=SizeBand.UNKNOWN, warnings=warnings
        ),
        "lower_wick": _enum(
            candle.get("lower_wick"), "lower_wick", default=SizeBand.UNKNOWN, warnings=warnings
        ),
        "high_px": _as_int_or_none(candle.get("high_px")),
        "low_px": _as_int_or_none(candle.get("low_px")),
        "body_top_px": _as_int_or_none(candle.get("body_top_px")),
        "body_bottom_px": _as_int_or_none(candle.get("body_bottom_px")),
        "appears_complete": _as_bool_or_none(candle.get("appears_complete")),
        "confidence": _confidence(candle.get("confidence")),
        "ambiguity": candle.get("ambiguity") if isinstance(candle.get("ambiguity"), str) else None,
    }


def _normalize_market_structure(raw: Any, warnings: list[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        warnings.append("market_structure was not an object; using defaults.")
        raw = {}
    return {
        "trend": _enum(raw.get("trend"), "trend", default=Trend.UNCLEAR, warnings=warnings),
        "higher_highs": _as_bool_or_none(raw.get("higher_highs")),
        "higher_lows": _as_bool_or_none(raw.get("higher_lows")),
        "lower_highs": _as_bool_or_none(raw.get("lower_highs")),
        "lower_lows": _as_bool_or_none(raw.get("lower_lows")),
        "swing_highs": _as_list(raw.get("swing_highs")),
        "swing_lows": _as_list(raw.get("swing_lows")),
        "breakouts": _as_list(raw.get("breakouts")),
        "failed_breakouts": _as_list(raw.get("failed_breakouts")),
        "consolidation": _as_bool_or_none(raw.get("consolidation")),
        "notes": _as_string(raw.get("notes"), default=""),
        "confidence": _confidence(raw.get("confidence")),
    }


def _normalize_chart_metadata(raw: Any, warnings: list[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        warnings.append("chart_metadata was not an object; using UNKNOWN values.")
        raw = {}
    colors = raw.get("candle_colors")
    if not isinstance(colors, dict):
        colors = {}
    return {
        "platform": _as_string(raw.get("platform")),
        "instrument": _as_string(raw.get("instrument")),
        "otc_status": _enum(
            raw.get("otc_status"), "otc_status", default=OTCStatus.UNKNOWN, warnings=warnings
        ),
        "timeframe": _as_string(raw.get("timeframe")),
        "screenshot_timestamp": (
            raw.get("screenshot_timestamp")
            if isinstance(raw.get("screenshot_timestamp"), str)
            else None
        ),
        "visible_price_labels": [
            _as_string(item)
            for item in _as_list(raw.get("visible_price_labels"))
            if item not in (None, "")
        ],
        "candle_colors": {
            "bullish": _as_string(colors.get("bullish")),
            "bearish": _as_string(colors.get("bearish")),
        },
        "orientation": _enum(
            raw.get("orientation"),
            "orientation",
            default=ChartOrientation.UNKNOWN,
            warnings=warnings,
        ),
        "volume_indicator_present": _as_bool_or_none(raw.get("volume_indicator_present")),
        "technical_indicators": [
            _as_string(item)
            for item in _as_list(raw.get("technical_indicators"))
            if item not in (None, "")
        ],
        "confidence": _confidence(raw.get("confidence")),
    }


def _normalize_screenshot_quality(raw: Any, warnings: list[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        warnings.append("screenshot_quality was not an object; using UNKNOWN rating.")
        raw = {}
    return {
        "rating": _enum(
            raw.get("rating"),
            "rating",
            default=ScreenshotQuality.UNKNOWN,
            warnings=warnings,
        ),
        "issues": [
            _as_string(item) for item in _as_list(raw.get("issues")) if item not in (None, "")
        ],
        "notes": _as_string(raw.get("notes"), default=""),
    }


def validate_payload(
    payload: Any, *, schema_version: str = SCHEMA_VERSION, strict: bool = True
) -> SchemaValidationResult:
    """Validate and normalise a provider payload against the v1 schema."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(payload, dict):
        return SchemaValidationResult(
            valid=False, payload={}, errors=["Payload is not a JSON object."], warnings=[]
        )

    returned_version = str(payload.get("schema_version", "") or "")
    if returned_version:
        if returned_version.split(".")[0] != schema_version.split(".")[0]:
            errors.append(
                f"Schema version mismatch: provider returned {returned_version!r}, "
                f"expected {schema_version!r}."
            )
    else:
        warnings.append(f"Provider omitted schema_version; assuming {schema_version!r}.")

    forbidden = _find_forbidden_keys(payload)
    if forbidden:
        errors.append(
            "Fabricated probability/prediction fields are not permitted: "
            + ", ".join(sorted(set(forbidden)))
        )

    missing = [key for key in REQUIRED_TOP_LEVEL if key not in payload]
    if missing:
        errors.append("Missing required top-level keys: " + ", ".join(missing))

    normalized: dict[str, Any] = {"schema_version": schema_version}

    analysis_status = _as_string(payload.get("analysis_status"), default="partial").lower()
    if analysis_status not in ANALYSIS_STATUSES:
        warnings.append(f"analysis_status {analysis_status!r} is not recognised; using 'partial'.")
        analysis_status = "partial"
    normalized["analysis_status"] = analysis_status

    normalized["screenshot_quality"] = _normalize_screenshot_quality(
        payload.get("screenshot_quality"), warnings
    )
    normalized["chart_metadata"] = _normalize_chart_metadata(
        payload.get("chart_metadata"), warnings
    )

    raw_candles = payload.get("candles")
    if raw_candles is None:
        raw_candles = []
    if not isinstance(raw_candles, list):
        errors.append("`candles` must be a list.")
        raw_candles = []
    normalized["candles"] = [
        _normalize_candle(index, item, warnings) for index, item in enumerate(raw_candles)
    ]

    normalized["market_structure"] = _normalize_market_structure(
        payload.get("market_structure"), warnings
    )

    raw_zones = _as_list(payload.get("support_resistance"))
    zones: list[dict[str, Any]] = []
    for item in raw_zones:
        if not isinstance(item, dict):
            warnings.append("A support_resistance entry was not an object and was skipped.")
            continue
        zones.append(
            {
                "zone_type": _enum(
                    item.get("zone_type"),
                    "zone_type",
                    default=ZoneType.SUPPORT,
                    warnings=warnings,
                ),
                "approx_location": _as_string(item.get("approx_location"), default=""),
                "price_hint": _as_string(item.get("price_hint"), default=""),
                "supporting_candles": [
                    idx
                    for idx in (
                        _as_int_or_none(v) for v in _as_list(item.get("supporting_candles"))
                    )
                    if idx is not None
                ],
                "repeated_rejection": bool(_as_bool_or_none(item.get("repeated_rejection"))),
                "broken": bool(_as_bool_or_none(item.get("broken"))),
                "flip": _as_string(item.get("flip"), default=""),
                "confidence": _confidence(item.get("confidence")),
                "description": _as_string(item.get("description"), default=""),
            }
        )
    normalized["support_resistance"] = zones

    raw_patterns = _as_list(payload.get("patterns"))
    patterns: list[dict[str, Any]] = []
    for item in raw_patterns:
        if not isinstance(item, dict):
            warnings.append("A pattern entry was not an object and was skipped.")
            continue
        patterns.append(
            {
                "name": _as_string(item.get("name"), default=UNKNOWN),
                "category": _enum(
                    item.get("category"),
                    "category",
                    default=PatternCategory.CANDLESTICK,
                    warnings=warnings,
                ),
                "direction": _enum(
                    item.get("direction"),
                    "direction",
                    default=PatternDirection.UNKNOWN,
                    warnings=warnings,
                ),
                "candles": [
                    idx
                    for idx in (_as_int_or_none(v) for v in _as_list(item.get("candles")))
                    if idx is not None
                ],
                "confidence": _confidence(item.get("confidence")),
                "confirmed": _as_bool_or_none(item.get("confirmed")),
                "description": _as_string(item.get("description"), default=""),
            }
        )
    normalized["patterns"] = patterns

    normalized["sequence_observations"] = _normalize_generic_list(
        payload.get("sequence_observations"), warnings, label="sequence_observation"
    )
    normalized["liquidity"] = _normalize_generic_list(
        payload.get("liquidity"), warnings, label="liquidity"
    )

    cycle_raw = payload.get("market_cycle")
    if not isinstance(cycle_raw, dict):
        cycle_raw = {}
    normalized["market_cycle"] = {
        "observed": bool(_as_bool_or_none(cycle_raw.get("observed"))),
        "phase": _as_string(cycle_raw.get("phase"), default="insufficient"),
        "description": _as_string(cycle_raw.get("description"), default=""),
        "confidence": _confidence(cycle_raw.get("confidence")),
    }

    volume_raw = payload.get("volume")
    if not isinstance(volume_raw, dict):
        volume_raw = {}
    normalized["volume"] = {
        "patterns": [
            _as_string(item)
            for item in _as_list(volume_raw.get("patterns"))
            if item not in (None, "")
        ],
        "indicator_present": _as_bool_or_none(volume_raw.get("indicator_present")),
        "notes": _as_string(volume_raw.get("notes"), default=""),
        "confidence": _confidence(volume_raw.get("confidence")),
    }

    normalized["missing_information"] = [
        _as_string(item)
        for item in _as_list(payload.get("missing_information"))
        if item not in (None, "")
    ]
    normalized["warnings"] = [
        _as_string(item) for item in _as_list(payload.get("warnings")) if item not in (None, "")
    ]

    confidence_raw = payload.get("observation_confidence")
    if not isinstance(confidence_raw, dict):
        confidence_raw = {}
    normalized["observation_confidence"] = {
        "overall": _confidence(confidence_raw.get("overall")),
        "notes": _as_string(confidence_raw.get("notes"), default=""),
    }

    valid = not errors if strict else True
    return SchemaValidationResult(valid=valid, payload=normalized, errors=errors, warnings=warnings)


def _normalize_generic_list(raw: Any, warnings: list[str], *, label: str) -> list[dict[str, Any]]:
    items = _as_list(raw)
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            warnings.append(f"A {label} entry was not an object and was skipped.")
            continue
        normalized.append(
            {
                "kind": _as_string(item.get("kind"), default=UNKNOWN),
                "candles": [
                    idx
                    for idx in (_as_int_or_none(v) for v in _as_list(item.get("candles")))
                    if idx is not None
                ],
                "confidence": _confidence(item.get("confidence")),
                "notes": _as_string(item.get("notes"), default=""),
            }
        )
    return normalized


__all__ = [
    "ANALYSIS_STATUSES",
    "REQUIRED_TOP_LEVEL",
    "SchemaValidationResult",
    "parse_json_object",
    "validate_payload",
]
