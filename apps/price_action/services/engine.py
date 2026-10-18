"""The price-action engine (Phase 5 orchestrator).

The engine is a *pure* function of its input: given the same candles and config it
always returns the same result. It never predicts an outcome, never fabricates a
probability and never executes a trade. It converts a standardized market input
(Step 3) into structured evidence (Step 20) and structured conflicts (Step 21).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.price_action.constants import (
    PA_ENGINE_SCHEMA_VERSION,
    PA_KNOWLEDGE_VERSION,
    DataQuality,
    Direction,
    EvidenceStatus,
    ZoneKind,
)
from apps.price_action.schemas.market_input import build_market_input
from apps.price_action.services import (
    buyer_seller_failure as bsf,
)
from apps.price_action.services import (
    candle_sequences as seq,
)
from apps.price_action.services import (
    candlestick_patterns as patterns,
)
from apps.price_action.services import (
    fair_value_gaps as fvg,
)
from apps.price_action.services import (
    liquidity_sweeps as sweeps,
)
from apps.price_action.services import (
    market_context as context,
)
from apps.price_action.services import (
    market_cycle as cycle,
)
from apps.price_action.services import (
    market_structure as structure,
)
from apps.price_action.services import (
    opening_gaps as gaps,
)
from apps.price_action.services import (
    order_blocks as ob,
)
from apps.price_action.services import (
    support_resistance as sr,
)
from apps.price_action.services import (
    volume_analysis as volume,
)
from apps.price_action.services.config import PriceActionConfig
from apps.price_action.services.conflict_detector import detect_conflicts
from apps.price_action.services.dto import Candle, MarketInput
from apps.price_action.services.evidence_registry import Evidence, EvidenceRegistry

#: Engine version reported in every result document.
ENGINE_VERSION = "1.0"


def _plain(candle: Candle) -> dict[str, Any]:
    return {
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "open_time": candle.open_time.isoformat() if candle.open_time else None,
        "tick_volume": candle.tick_volume,
        "real_volume": candle.real_volume,
        "complete": candle.complete,
    }


def _timestamps(candles: list[Candle], refs: list[int]) -> tuple[str, ...]:
    out: list[str] = []
    for ref in refs:
        if 0 <= ref < len(candles) and candles[ref].open_time is not None:
            out.append(candles[ref].open_time.isoformat())  # type: ignore[union-attr]
    return tuple(out)


class PriceActionEngine:
    """Runs every detector over a standardized market input."""

    def __init__(self, config: PriceActionConfig | None = None) -> None:
        self.config = config or PriceActionConfig.from_settings()

    # -- public API --------------------------------------------------------
    def run(self, input_: Any = None, *, now: datetime | None = None) -> dict[str, Any]:
        market = self._normalise(input_)
        return self.run_market_input(market, now=now)

    def run_market_input(
        self, market: MarketInput, *, now: datetime | None = None
    ) -> dict[str, Any]:
        registry = EvidenceRegistry()
        completed = market.completed()
        candles = [_plain(c) for c in completed]

        context_result = context.build_context(candles, now=now, config=self.config)

        self._market_structure(candles, registry)
        self._support_resistance(candles, registry)
        self._buyer_seller(candles, registry)
        self._patterns(candles, registry)
        self._sequences(candles, registry)
        self._cycle(candles, registry)
        self._sweeps(candles, registry)
        self._order_blocks(candles, registry)
        self._fair_value_gaps(candles, registry)
        self._opening_gaps(candles, registry)
        self._volume(candles, registry)
        self._context(candles, context_result, registry)

        evidence = registry.all()
        conflicts = detect_conflicts(
            evidence,
            {
                "consolidation": context_result.get("consolidation"),
                "feed_compatibility": market.feed_compatibility,
                "sync_status": market.sync_status,
            },
        )

        return {
            "schema_version": PA_ENGINE_SCHEMA_VERSION,
            "engine_version": ENGINE_VERSION,
            "knowledge_version": self.config.knowledge_version or PA_KNOWLEDGE_VERSION,
            "canonical_instrument": market.canonical_instrument,
            "broker_symbol": market.broker_symbol,
            "timeframe": market.timeframe,
            "market_type": market.market_type,
            "data_quality": market.data_quality,
            "warnings": list(market.warnings),
            "candles_evaluated": len(candles),
            "context": context_result,
            "evidence": registry.to_dicts(),
            "conflicts": [c.to_dict() for c in conflicts],
            "summary": self._summarise(evidence),
        }

    # -- input normalisation ----------------------------------------------
    def _normalise(self, input_: Any) -> MarketInput:
        if isinstance(input_, MarketInput):
            return input_
        if isinstance(input_, list):
            payload: dict[str, Any] = {"candles": input_}
        elif isinstance(input_, dict):
            payload = input_
        elif input_ is None:
            payload = {"candles": []}
        else:  # pragma: no cover - defensive
            payload = {"candles": []}
        return build_market_input(payload, config=self.config)

    # -- helpers -----------------------------------------------------------
    def _ev(
        self,
        registry: EvidenceRegistry,
        *,
        rule_id: str,
        detector: str,
        direction: str,
        explanation: str,
        candle_refs: list[int] | None = None,
        levels: list[float] | None = None,
        reasons: list[str] | None = None,
        status: str = EvidenceStatus.DETECTED,
        metrics: dict[str, Any] | None = None,
        candles: list[Candle] | None = None,
        required: list[str] | None = None,
        invalidation: list[str] | None = None,
        missing: list[str] | None = None,
        data_quality: str = DataQuality.MEDIUM,
    ) -> None:
        refs = candle_refs or []
        registry.add(
            Evidence(
                rule_id=rule_id,
                detector=detector,
                status=status,
                direction=direction,
                explanation=explanation,
                candle_refs=tuple(refs),
                supporting_levels=tuple(levels or ()),
                timestamps=_timestamps(candles, refs) if candles else (),
                required_conditions=tuple(required or ()),
                invalidation_conditions=tuple(invalidation or ()),
                missing_inputs=tuple(missing or ()),
                data_quality=data_quality,
                reasons=tuple(reasons or ()),
                metrics=metrics or {},
            )
        )

    # -- detectors ---------------------------------------------------------
    def _market_structure(self, candles: list[dict[str, Any]], reg: EvidenceRegistry) -> None:
        if not candles:
            return
        swings = structure.label_swings(
            structure.detect_swings(candles, self.config.swing_lookback),
            self.config.equal_level_tolerance,
        )
        trend = structure.infer_trend(candles, self.config.swing_lookback, config=self.config)
        direction = (
            Direction.BULLISH
            if trend == "uptrend"
            else Direction.BEARISH
            if trend == "downtrend"
            else Direction.NEUTRAL
        )
        refs = [s.index for s in swings][-4:]
        self._ev(
            reg,
            rule_id="pa.structure.trend",
            detector="market_structure",
            direction=direction,
            explanation=f"market structure inferred as {trend}",
            candle_refs=refs,
            levels=[s.value for s in swings][-4:],
            reasons=[f"{s.kind}@{s.index}={s.label}" for s in swings][-6:],
            status=EvidenceStatus.DETECTED if trend != "unclear" else EvidenceStatus.INSUFFICIENT,
            metrics={"trend": trend, "swings": len(swings)},
        )

        bos = structure.detect_structure_break(candles, self.config.swing_lookback)
        if bos:
            self._ev(
                reg,
                rule_id=f"pa.structure.break.{bos['type']}",
                detector="market_structure",
                direction=Direction.BULLISH if "bullish" in bos["type"] else Direction.BEARISH,
                explanation=f"structure break detected ({bos['type']})",
                candle_refs=[bos["index"]],
                levels=[bos["level"]],
                invalidation=["voided if price closes back inside the broken swing"],
            )

        failed = structure.detect_failed_breakout(candles, self.config.swing_lookback)
        if failed:
            self._ev(
                reg,
                rule_id=f"pa.structure.failed_breakout.{failed['type']}",
                detector="market_structure",
                direction=(Direction.BEARISH if "high" in failed["type"] else Direction.BULLISH),
                explanation=f"failed breakout ({failed['type']})",
                candle_refs=[failed["index"]],
                levels=[failed["level"]],
            )

        cons = structure.detect_consolidation(candles, config=self.config)
        if cons:
            self._ev(
                reg,
                rule_id="pa.structure.consolidation",
                detector="market_structure",
                direction=Direction.NEUTRAL,
                explanation="price is consolidating inside a tight range",
                candle_refs=[cons["index"]],
                levels=[cons["low"], cons["high"]],
                metrics={"width": cons["width"], "candles": cons["candles"]},
            )

    def _support_resistance(self, candles: list[dict[str, Any]], reg: EvidenceRegistry) -> None:
        zones = sr.detect_zones(candles, config=self.config)
        for zone in zones:
            refs = [zone.first_index, zone.last_index]
            self._ev(
                reg,
                rule_id=f"pa.sr.zone.{zone.kind}",
                detector="support_resistance",
                direction=(
                    Direction.BULLISH if zone.kind == ZoneKind.SUPPORT else Direction.BEARISH
                ),
                explanation=f"{zone.kind} zone with {zone.touches} touches",
                candle_refs=refs,
                levels=[zone.low, zone.high],
                metrics={"touches": zone.touches, "strength": zone.strength},
            )
            rejection = sr.detect_rejection(candles, zone, config=self.config)
            if rejection:
                self._ev(
                    reg,
                    rule_id=f"pa.sr.rejection.{rejection['side']}",
                    detector="support_resistance",
                    direction=(
                        Direction.BEARISH if zone.kind == ZoneKind.RESISTANCE else Direction.BULLISH
                    ),
                    explanation=f"{rejection['kind']} at {zone.kind}",
                    candle_refs=[rejection["index"]],
                    levels=[zone.price],
                )
            breakout = sr.detect_breakout_confirmation(candles, zone, config=self.config)
            if breakout:
                self._ev(
                    reg,
                    rule_id=f"pa.sr.breakout.{breakout['type']}",
                    detector="support_resistance",
                    direction=(
                        Direction.BULLISH if "bullish" in breakout["type"] else Direction.BEARISH
                    ),
                    explanation=f"confirmed breakout ({breakout['type']})",
                    candle_refs=[breakout["index"]],
                    levels=[breakout["level"]],
                )
            flip = sr.detect_sbr_rbs(candles, zone, config=self.config)
            if flip:
                valid_break = True
                self._ev(
                    reg,
                    rule_id=f"pa.sr.sbr_rbs.{flip['type']}",
                    detector="support_resistance",
                    direction=(
                        Direction.BULLISH
                        if flip["type"] == "resistance_became_support"
                        else Direction.BEARISH
                    ),
                    explanation=f"{flip['type']} detected after a valid break and retest",
                    candle_refs=[flip["break_index"], flip["retest_index"]],
                    levels=[zone.price],
                    metrics={"valid_break": valid_break},
                )

    def _buyer_seller(self, candles: list[dict[str, Any]], reg: EvidenceRegistry) -> None:
        result = bsf.detect_buyer_seller_failure(candles, config=self.config)
        for event in result["events"]:
            self._ev(
                reg,
                rule_id=f"pa.bsf.{event['type']}",
                detector="buyer_seller_failure",
                direction=event.get("direction", Direction.NEUTRAL),
                explanation=event.get("note", event["type"]),
                candle_refs=[event["index"]],
                levels=[event["level"]] if "level" in event else None,
            )
        strength = result["source_strength"]
        if strength.get("available"):
            direction = (
                Direction.BULLISH
                if strength["direction"] == Direction.BULLISH
                else Direction.BEARISH
            )
            status = EvidenceStatus.INSUFFICIENT
            if strength["weakening"]:
                status = EvidenceStatus.DETECTED
            self._ev(
                reg,
                rule_id=f"pa.bsf.source_strength.{strength['direction']}",
                detector="buyer_seller_failure",
                direction=direction,
                explanation=(
                    f"{strength['direction']} source weakening"
                    if strength["weakening"]
                    else f"{strength['direction']} source strengthening"
                    if strength["strengthening"]
                    else "source strength unchanged"
                ),
                reasons=strength["reasons"],
                status=status,
                metrics={
                    "strengthening": strength["strengthening"],
                    "weakening": strength["weakening"],
                },
            )

    def _patterns(self, candles: list[dict[str, Any]], reg: EvidenceRegistry) -> None:
        if not candles:
            return
        found = patterns.detect_patterns(candles, len(candles) - 1, config=self.config)
        for pattern in found:
            self._ev(
                reg,
                rule_id=f"pa.candle.{pattern['name']}",
                detector="candlestick_patterns",
                direction=pattern["direction"],
                explanation=f"{pattern['name']} detected",
                candle_refs=pattern["candle_refs"],
                required=[pattern["context_requirement"]],
                invalidation=[pattern["invalidation_condition"]],
                reasons=pattern["reasons"],
            )

    def _sequences(self, candles: list[dict[str, Any]], reg: EvidenceRegistry) -> None:
        ref = seq.analyze_reference_sequences(candles, config=self.config)
        if ref.get("available"):
            self._ev(
                reg,
                rule_id="pa.sequence.reference",
                detector="candle_sequences",
                direction=(
                    Direction.BULLISH
                    if ref["current_direction"] == Direction.BULLISH
                    else Direction.BEARISH
                ),
                explanation=(
                    f"{ref['current_direction']} run of {ref['current_run_length']} candles"
                ),
                reasons=ref["reasons"],
                metrics={
                    "run_length": ref["current_run_length"],
                    "extended": ref["extended"],
                    "strengthening": ref["strengthening"],
                    "weakening": ref["weakening"],
                },
            )
        similar = seq.similar_sequences(candles, config=self.config)
        if similar.get("available"):
            self._ev(
                reg,
                rule_id="pa.sequence.similar",
                detector="candle_sequences",
                direction=Direction.NEUTRAL,
                explanation=(
                    f"{similar['occurrences']} historical matches for the trailing signature"
                ),
                reasons=similar["reasons"],
                status=(
                    EvidenceStatus.DETECTED
                    if similar["min_samples_met"]
                    else EvidenceStatus.INSUFFICIENT
                ),
                metrics={
                    "occurrences": similar["occurrences"],
                    "outcome_counts": similar["outcome_counts"],
                    "predictive_claim": False,
                },
            )
        for lonely in seq.lonely_candles(candles, config=self.config):
            self._ev(
                reg,
                rule_id="pa.sequence.lonely",
                detector="candle_sequences",
                direction=Direction.NEUTRAL,
                explanation=lonely["observation"],
                candle_refs=[lonely["index"]],
                levels=[lonely["level"]],
                reasons=[lonely["interpretation_note"]],
                metrics={"hypothesis": lonely["hypothesis"]},
            )
        for template in seq.psych_sequences(candles, config=self.config):
            self._ev(
                reg,
                rule_id=f"pa.sequence.psych.{template['name']}",
                detector="candle_sequences",
                direction=template["direction"],
                explanation=f"psychological template {template['name']} matched",
                candle_refs=template["candle_refs"],
                required=template["context_requirements"],
                metrics={"template_not_signal": True},
            )

    def _cycle(self, candles: list[dict[str, Any]], reg: EvidenceRegistry) -> None:
        result = cycle.classify_cycle(candles, config=self.config)
        direction = (
            Direction.BULLISH
            if result["phase"] == "bullish_reversal"
            else Direction.BEARISH
            if result["phase"] == "bearish_reversal"
            else Direction.NEUTRAL
        )
        self._ev(
            reg,
            rule_id="pa.cycle.phase",
            detector="market_cycle",
            direction=direction,
            explanation=f"market cycle phase: {result['phase']}",
            reasons=result["reasons"],
            status=(
                EvidenceStatus.DETECTED
                if result["phase"] != "unclear"
                else EvidenceStatus.INSUFFICIENT
            ),
            metrics={
                "phase": result["phase"],
                "confirmed": False,
                "ambiguous": result["ambiguous"],
            },
        )

    def _sweeps(self, candles: list[dict[str, Any]], reg: EvidenceRegistry) -> None:
        for sweep in sweeps.detect_sweep(candles, config=self.config):
            self._ev(
                reg,
                rule_id=f"pa.sweep.{sweep['type']}",
                detector="liquidity_sweeps",
                direction=sweep["direction"],
                explanation=f"{sweep['type']} with outcome {sweep['outcome']}",
                candle_refs=[sweep["index"]],
                levels=[sweep["level"]],
                reasons=[sweep["note"]],
                metrics={
                    "closed_back_inside": sweep["closed_back_inside"],
                    "engulfing_confirmation": sweep["engulfing_confirmation"],
                    "outcome": sweep["outcome"],
                },
            )

    def _order_blocks(self, candles: list[dict[str, Any]], reg: EvidenceRegistry) -> None:
        for zone in ob.annotate_ob_lifecycle(
            candles,
            ob.detect_order_blocks(candles, config=self.config),
        ):
            if zone.get("rejected"):
                continue
            self._ev(
                reg,
                rule_id=f"pa.ob.{zone['type']}",
                detector="order_blocks",
                direction=(Direction.BULLISH if "bullish" in zone["type"] else Direction.BEARISH),
                explanation=f"{zone['type']} candidate ({zone['definition']})",
                candle_refs=[zone["index"]],
                levels=[zone["bottom"], zone["top"]],
                reasons=["research hypothesis, not an institutional-order claim"],
                status=(
                    EvidenceStatus.DETECTED
                    if zone.get("state") == "active"
                    else EvidenceStatus.INVALIDATED
                ),
                metrics={
                    "definition": zone["definition"],
                    "strong_departure": zone["strong_departure"],
                    "sweep_before": zone["sweep_before"],
                    "retest_index": zone.get("retest_index"),
                },
            )

    def _fair_value_gaps(self, candles: list[dict[str, Any]], reg: EvidenceRegistry) -> None:
        found = fvg.annotate_fvg_states(candles, fvg.detect_fvg(candles, config=self.config))
        for gap in found:
            self._ev(
                reg,
                rule_id=f"pa.fvg.{gap['type']}",
                detector="fair_value_gaps",
                direction=(Direction.BULLISH if "bullish" in gap["type"] else Direction.BEARISH),
                explanation=f"{gap['type']} confirmed by a completed third candle",
                candle_refs=[gap["middle_index"], gap["index"]],
                levels=[gap["bottom"], gap["top"]],
                metrics={"state": gap["state"], "confirmed_by_close": True},
            )

    def _opening_gaps(self, candles: list[dict[str, Any]], reg: EvidenceRegistry) -> None:
        found = gaps.annotate_gap_reactions(
            candles, gaps.detect_opening_gaps(candles, config=self.config)
        )
        for gap in found:
            self._ev(
                reg,
                rule_id=f"pa.gap.{gap['type']}",
                detector="opening_gaps",
                direction=(Direction.BULLISH if gap["type"] == "bullish" else Direction.BEARISH),
                explanation=f"opening {gap['type']} gap ({gap['reaction']})",
                candle_refs=[gap["index"] - 1, gap["index"]],
                levels=[gap["gap_bottom"], gap["gap_top"]],
                reasons=[gap["note"]],
                metrics={"size": gap["size"], "reaction": gap["reaction"]},
            )

    def _volume(self, candles: list[dict[str, Any]], reg: EvidenceRegistry) -> None:
        for pattern in volume.detect_volume_patterns(candles, config=self.config):
            self._ev(
                reg,
                rule_id=f"pa.volume.{pattern['type']}",
                detector="volume_analysis",
                direction=Direction.NEUTRAL,
                explanation=pattern["type"],
                candle_refs=[pattern["index"]],
                reasons=[pattern.get("note", "")],
                metrics={k: v for k, v in pattern.items() if k not in ("type", "index", "note")},
            )

    def _context(
        self,
        candles: list[dict[str, Any]],
        context_result: dict[str, Any],
        reg: EvidenceRegistry,
    ) -> None:
        self._ev(
            reg,
            rule_id="pa.context.session",
            detector="market_context",
            direction=Direction.NEUTRAL,
            explanation=f"trading session: {context_result['session']}",
            metrics={
                "session": context_result["session"],
                "overlap": context_result["session_overlap"],
            },
        )
        self._ev(
            reg,
            rule_id="pa.context.regime",
            detector="market_context",
            direction=Direction.NEUTRAL,
            explanation=f"market regime: {context_result['regime']}",
            metrics={
                "regime": context_result["regime"],
                "volatility": context_result["volatility"],
                "news_status": context_result["news_status"],
                "freshness": context_result["freshness"],
            },
        )

    # -- summary -----------------------------------------------------------
    def _summarise(self, evidence: list[Evidence]) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for e in evidence:
            counts[str(e.direction)] = counts.get(str(e.direction), 0) + 1
        return {
            "evidence_count": len(evidence),
            "by_direction": counts,
            "note": "summary is descriptive; no trading probability is computed",
        }


__all__ = ["ENGINE_VERSION", "PriceActionEngine"]
