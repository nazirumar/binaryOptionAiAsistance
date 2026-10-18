"""Projection of market structure, S/R zones, patterns and advanced concepts.

Turns the normalised structured output into compact observation/pattern/zone
records. Every record keeps ``confirmed`` semantics: a swing, level or pattern is
only ``confirmed`` when the model stated it and the confirming candles are
visible; otherwise it is uncertain (``None`` or ``False``). Visual pattern
detection is never presented as proof of a future move.
"""

from __future__ import annotations

from typing import Any

from apps.chart_vision.constants import UNKNOWN

#: Advanced concepts recognised by the course material.
ADVANCED_CONCEPT_KINDS = {
    "sweep",
    "order_block",
    "fair_value_gap",
    "opening_gap",
    "liquidity_sweep",
}


def build_structure_observations(structure: dict[str, Any]) -> list[dict[str, Any]]:
    if not structure:
        return []
    trend = structure.get("trend", UNKNOWN)
    parts = [f"Trend: {trend}"]
    for key, label in (
        ("higher_highs", "higher highs"),
        ("higher_lows", "higher lows"),
        ("lower_highs", "lower highs"),
        ("lower_lows", "lower lows"),
    ):
        value = structure.get(key)
        if value is not None:
            parts.append(f"{label}: {'yes' if value else 'no'}")
    if structure.get("consolidation") is not None:
        parts.append(f"consolidation: {'yes' if structure['consolidation'] else 'no'}")
    if structure.get("notes"):
        parts.append(str(structure["notes"]))

    swing_count = len(structure.get("swing_highs") or []) + len(structure.get("swing_lows") or [])
    return [
        {
            "kind": "market_structure",
            "label": "Market structure",
            "summary": " · ".join(parts),
            "confidence": structure.get("confidence"),
            "confirmed": None,
            "evidence": {
                "result_path": "market_structure",
                "swing_count": swing_count,
                "breakouts": structure.get("breakouts") or [],
                "failed_breakouts": structure.get("failed_breakouts") or [],
            },
        }
    ]


def build_price_zones(zones: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for zone in zones or []:
        if not isinstance(zone, dict):
            continue
        records.append(
            {
                "zone_type": zone.get("zone_type", "support"),
                "approx_location": zone.get("approx_location", "") or "",
                "price_hint": zone.get("price_hint", "") or "",
                "supporting_candles": zone.get("supporting_candles") or [],
                "repeated_rejection": bool(zone.get("repeated_rejection")),
                "broken": bool(zone.get("broken")),
                "flip": zone.get("flip", "") or "",
                "confidence": zone.get("confidence"),
                "description": zone.get("description", "") or "",
                "evidence": {"result_path": "support_resistance"},
            }
        )
    return records


def build_patterns(patterns: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for pattern in patterns or []:
        if not isinstance(pattern, dict):
            continue
        records.append(
            {
                "name": pattern.get("name", UNKNOWN),
                "category": pattern.get("category", "candlestick"),
                "direction": pattern.get("direction", "unknown"),
                "candle_refs": pattern.get("candles") or [],
                "confidence": pattern.get("confidence"),
                "confirmed": pattern.get("confirmed"),
                "description": pattern.get("description", "") or "",
                "evidence": {"result_path": "patterns"},
            }
        )
    return records


def build_sequence_observations(
    items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        records.append(
            {
                "kind": "candle_sequence",
                "label": str(item.get("kind", UNKNOWN)),
                "summary": str(item.get("notes", "") or ""),
                "confidence": item.get("confidence"),
                "confirmed": None,
                "evidence": {
                    "result_path": "sequence_observations",
                    "candles": item.get("candles") or [],
                },
            }
        )
    return records


def build_liquidity_observations(
    items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        records.append(
            {
                "kind": "liquidity",
                "label": str(item.get("kind", UNKNOWN)),
                "summary": str(item.get("notes", "") or ""),
                "confidence": item.get("confidence"),
                "confirmed": None,
                "evidence": {
                    "result_path": "liquidity",
                    "candles": item.get("candles") or [],
                },
            }
        )
    return records


def build_cycle_observations(cycle: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not cycle or not cycle.get("observed"):
        return []
    return [
        {
            "kind": "market_cycle",
            "label": str(cycle.get("phase", UNKNOWN)),
            "summary": str(cycle.get("description", "") or ""),
            "confidence": cycle.get("confidence"),
            "confirmed": None,
            "evidence": {"result_path": "market_cycle"},
        }
    ]


def build_volume_observations(volume: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not volume:
        return []
    patterns = volume.get("patterns") or []
    if not patterns and volume.get("indicator_present") is None and not volume.get("notes"):
        return []
    summary_parts = []
    if patterns:
        summary_parts.append("patterns: " + ", ".join(str(p) for p in patterns))
    if volume.get("indicator_present") is not None:
        summary_parts.append(
            "volume indicator present" if volume["indicator_present"] else "no volume indicator"
        )
    if volume.get("notes"):
        summary_parts.append(str(volume["notes"]))
    return [
        {
            "kind": "volume",
            "label": "Relative volume",
            "summary": " · ".join(summary_parts),
            "confidence": volume.get("confidence"),
            "confirmed": None,
            "evidence": {"result_path": "volume", "patterns": patterns},
        }
    ]


def advance_pattern_records(
    sequence_items: list[dict[str, Any]] | None,
    liquidity_items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Promote recognised advanced-course concepts into candidate patterns."""
    records: list[dict[str, Any]] = []
    for item in (sequence_items or []) + (liquidity_items or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).strip().lower()
        if kind in ADVANCED_CONCEPT_KINDS:
            records.append(
                {
                    "name": kind,
                    "category": "advanced",
                    "direction": "unknown",
                    "candle_refs": item.get("candles") or [],
                    "confidence": item.get("confidence"),
                    "confirmed": None,
                    "description": str(item.get("notes", "") or ""),
                    "evidence": {"result_path": "advanced_concepts"},
                }
            )
    return records


__all__ = [
    "ADVANCED_CONCEPT_KINDS",
    "advance_pattern_records",
    "build_cycle_observations",
    "build_liquidity_observations",
    "build_patterns",
    "build_price_zones",
    "build_sequence_observations",
    "build_structure_observations",
    "build_volume_observations",
]
