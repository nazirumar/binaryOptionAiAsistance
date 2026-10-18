"""CP8: map validated vision output to strategy *candidates*.

The vision model's structured output (patterns, zones, observations) is
translated into strategy candidates **deterministically**: names are normalised
through a fixed mapping table and the :class:`StrategyPatternLabel` registry.
The LLM never picks strategies directly and a candidate is never a
confirmation — every candidate carries its provenance (``vision``), the
evidence path it came from, and the conditions that still require OHLC
confirmation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from django.db.models import Q

from apps.chart_vision.models import ScreenshotAnalysis
from apps.strategy_knowledge.constants import (
    ConditionKind,
    EvidenceProvenance,
    StrategyVariant,
)
from apps.strategy_knowledge.models import (
    StrategyCondition,
    StrategyDefinition,
    StrategyPatternLabel,
)

#: Fixed translation of normalised vision labels → knowledge-base pattern
#: labels. Keys are lowercase, ``[a-z0-9_]``-normalised names as they appear in
#: the versioned vision schema. Values are the canonical labels stored in
#: :class:`StrategyPatternLabel`. Anything absent here is simply not mapped —
#: no fuzzy guessing, no invented strategy IDs.
PATTERN_LABEL_MAP: dict[str, str] = {
    "bullish_engulfing": "bullish_engulfing",
    "bearish_engulfing": "bearish_engulfing",
    "hammer": "hammer",
    "shooting_star": "shooting_star",
    "doji": "doji",
    "bullish_harami": "bullish_harami",
    "bearish_harami": "bearish_harami",
    "inside_bar": "inside_bar",
    "outside_bar": "outside_bar",
    "piercing": "piercing",
    "dark_cloud_cover": "dark_cloud_cover",
    "morning_star": "morning_star",
    "evening_star": "evening_star",
    "three_white_soldiers": "three_white_soldiers",
    "three_black_crows": "three_black_crows",
    "pin_bar_bullish": "bullish_pin_bar",
    "pin_bar_bearish": "bearish_pin_bar",
    "bullish_pin_bar": "bullish_pin_bar",
    "bearish_pin_bar": "bearish_pin_bar",
    "inverted_hammer": "inverted_hammer",
    "hanging_man": "hanging_man",
    "dragonfly_doji": "dragonfly_doji",
    "gravestone_doji": "gravestone_doji",
    "spinning_top": "spinning_top",
    "tweezer_top": "tweezer_top",
    "tweezer_bottom": "tweezer_bottom",
}

#: Zone/observation labels (from zones and liquidity/structure observations)
#: mapped the same way.
ZONE_LABEL_MAP: dict[str, str] = {
    "support_becomes_resistance": "support_becomes_resistance",
    "resistance_becomes_support": "resistance_becomes_support",
    "sbr": "support_becomes_resistance",
    "rbs": "resistance_becomes_support",
    "false_breakout": "false_breakout",
    "liquidity_sweep": "bearish_sweep",
    "sweep": "bearish_sweep",
    "high_sweep": "bearish_sweep",
    "low_sweep": "bullish_sweep",
    "order_block": "bullish_order_block",
    "fair_value_gap": "bullish_fvg",
    "fvg": "bullish_fvg",
    "break_of_structure": "bos_bullish",
    "bos": "bos_bullish",
    "change_of_character": "choch_bullish",
    "choch": "choch_bullish",
}

_NORMALISE_RE = re.compile(r"[^a-z0-9]+")


def _normalise(name: str) -> str:
    return _NORMALISE_RE.sub("_", str(name).strip().lower()).strip("_")


@dataclass(slots=True)
class StrategyCandidate:
    """A vision-sourced strategy candidate awaiting deterministic verification."""

    definition: StrategyDefinition
    strategy_id: str
    direction: str
    source_kind: str  # pattern | zone | observation
    source_label: str
    confidence: float | None
    vision_confirmed: bool | None
    evidence_summary: str
    candle_refs: list[Any] = field(default_factory=list)
    result_path: str = ""
    missing_conditions: list[str] = field(default_factory=list)
    requires_ohlc_confirmation: bool = True
    provenance: str = str(EvidenceProvenance.VISION)


def _lookup_definitions(labels: Iterable[str]) -> dict[str, StrategyDefinition]:
    labels = [name for name in labels if name]
    if not labels:
        return {}
    rows = StrategyPatternLabel.objects.filter(
        Q(label__in=labels) | Q(label__in=[_normalise(name) for name in labels])
    ).select_related("definition", "definition__version")
    out: dict[str, StrategyDefinition] = {}
    for row in rows:
        out[row.label] = row.definition
        out[_normalise(row.label)] = row.definition
    return out


def _missing_for(definition: StrategyDefinition, source_label: str) -> list[str]:
    """Required conditions the vision source cannot establish by itself."""
    missing: list[str] = []
    conditions = StrategyCondition.objects.filter(
        definition=definition, kind=ConditionKind.REQUIRED
    )
    for condition in conditions:
        # The vision record that matched proves the *pattern shape* only.
        if _normalise(condition.label) != _normalise(source_label):
            missing.append(condition.label)
    return missing


def _map_record(name: str, *, kind_hint: str) -> str | None:
    normalised = _normalise(name)
    table = PATTERN_LABEL_MAP if kind_hint == "pattern" else ZONE_LABEL_MAP
    if normalised in table:
        return table[normalised]
    # tolerate direction prefixes like "bullish_engulfing_pattern"
    for key, value in table.items():
        if normalised.startswith(key) or normalised.endswith(key):
            return value
    return None


def build_candidates(analysis: ScreenshotAnalysis) -> list[StrategyCandidate]:
    """Translate a completed vision analysis into strategy candidates.

    Reads the compact derived rows (patterns, zones, observations) persisted by
    the chart-vision pipeline. Every candidate keeps ``provenance=vision`` and
    lists the required conditions that still need deterministic OHLC
    confirmation — a candidate produced here can never be a detection.
    """
    patterns = list(analysis.patterns.all())
    zones = list(analysis.price_zones.all())
    observations = list(analysis.observations.all())

    wanted: dict[str, tuple[str, str]] = {}  # label -> (kind, source_name)
    for record in patterns:
        label = _map_record(record.name, kind_hint="pattern")
        if label:
            wanted.setdefault(label, ("pattern", record.name))
    for record in zones:
        for name in (record.zone_type, record.flip):
            label = _map_record(name, kind_hint="zone")
            if label:
                wanted.setdefault(label, ("zone", name))
    for record in observations:
        label = _map_record(record.label, kind_hint="zone")
        if label:
            wanted.setdefault(label, ("observation", record.label))

    definitions = _lookup_definitions(wanted.keys())
    candidates: list[StrategyCandidate] = []
    for label, (kind, source_name) in wanted.items():
        definition = definitions.get(label) or definitions.get(_normalise(label))
        if definition is None or not definition.enabled:
            continue
        source_row = _source_row(kind, source_name, patterns, zones, observations)
        direction = getattr(definition, "variant", StrategyVariant.NEUTRAL)
        confidence: float | None = None
        confirmed: bool | None = None
        summary = ""
        candle_refs: list[Any] = []
        result_path = ""
        if source_row is not None:
            confidence = source_row.get("confidence")
            confirmed = source_row.get("confirmed")
            summary = source_row.get("summary") or source_row.get("description") or ""
            candle_refs = source_row.get("candle_refs") or []
            result_path = (source_row.get("evidence") or {}).get("result_path", "")
        candidates.append(
            StrategyCandidate(
                definition=definition,
                strategy_id=definition.strategy_id,
                direction=str(direction),
                source_kind=kind,
                source_label=source_name,
                confidence=confidence,
                vision_confirmed=confirmed,
                evidence_summary=str(summary)[:500],
                candle_refs=list(candle_refs),
                result_path=result_path,
                missing_conditions=_missing_for(definition, label),
                # Any definition backed by a deterministic detector needs real
                # OHLC confirmation; the vision name alone never verifies it.
                requires_ohlc_confirmation=bool(definition.detector_key),
                provenance=str(EvidenceProvenance.VISION),
            )
        )
    return candidates


def _source_row(
    kind: str,
    source_name: str,
    patterns: list[Any],
    zones: list[Any],
    observations: list[Any],
) -> dict[str, Any] | None:
    pool: list[Any]
    name_attr = "name"
    if kind == "pattern":
        pool = patterns
    elif kind == "zone":
        pool = zones
        name_attr = "zone_type"
    else:
        pool = observations
        name_attr = "label"
    normalised = _normalise(source_name)
    for row in pool:
        value = _normalise(getattr(row, name_attr, "") or "")
        if value == normalised or normalised in value or value in normalised:
            payload: dict[str, Any] = {}
            for attr in ("confidence", "confirmed", "description", "summary", "evidence"):
                payload[attr] = getattr(row, attr, None)
            payload["candle_refs"] = (
                getattr(row, "candle_refs", None) or getattr(row, "supporting_candles", None) or []
            )
            return payload
    return None
