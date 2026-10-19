# book_strategies/services/paper_forward.py
"""Paper forward-validation with immutable pre-outcome predictions (requirement 8).

Workflow, each step gated on honesty:

* ``record`` - only from CLOSED candles (caller asserts), only for
  recognition-enabled strategies, only when the detector confirms the pattern
  exactly on the latest closed candle (a fresh signal, never a stale one).
  The written row freezes its prediction fields (model-level immutability +
  ``payload_sha256``) while the outcome candle does not exist yet.
* ``resolve`` - exactly one candle later: the outcome candle must open when
  the signal candle closes and must be complete. Outcomes are next-candle
  close direction, the same definition as validation - explicitly NOT binary
  settlement (that is ``services/settlement.py``, gated on platform quotes).
* ``summary`` - reports resolved counts, next-candle hit rate with Wilson
  interval and explicit insufficiency below threshold. Paper records never
  change ``research_status`` or ``decision_use_approved``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.book_strategies.constants import SPEC_BY_KEY, BookPatternState
from apps.book_strategies.models import (
    BookStrategy,
    PaperForwardPrediction,
    payload_digest,
)
from apps.book_strategies.services.detectors import BOOK_DETECTORS
from apps.book_strategies.services.validation import DEFAULT_MIN_SIGNALS, wilson_interval

PAPER_METRIC_SCOPE = "next_candle_direction"

#: Timeframe code -> candle duration (matches the dataset import gaps table).
TIMEFRAME_INTERVALS: dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

PAPER_DISCLAIMER = (
    "Paper forward-validation records: predictions were written and frozen "
    "before the outcome candle existed. Metrics are next-candle close "
    "direction - not binary settlement, not a live win rate - and these "
    "records never approve a strategy for decision use."
)


class PaperForwardService:
    """Record and resolve immutable paper predictions."""

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record(
        self,
        candles: list[dict[str, Any]],
        *,
        instrument: str,
        timeframe: str,
        market_type: str = "",
        source: str = "unknown",
        last_candle_closed: bool = False,
    ) -> list[PaperForwardPrediction]:
        """Create one fresh, immutable prediction per eligible strategy.

        Returns only rows newly created; duplicates for the same
        (strategy, signal candle) are never written twice.
        """
        if not last_candle_closed or len(candles) < 2:
            return []
        interval = TIMEFRAME_INTERVALS.get(timeframe.upper())
        if interval is None:
            return []
        signal_open = candles[-1].get("open_time")
        if signal_open is None:
            # Timestamps are mandatory: without them no outcome window exists.
            return []

        created: list[PaperForwardPrediction] = []
        strategies = (
            BookStrategy.objects.filter(recognition_enabled=True)
            .exclude(detector_key="")
            .order_by("key")
        )
        for strategy in strategies:
            spec = SPEC_BY_KEY.get(strategy.key)
            detector = BOOK_DETECTORS.get(strategy.detector_key)
            if spec is None or detector is None:
                continue
            result = detector(list(candles))
            if result.state != BookPatternState.CONFIRMED_PATTERN:
                continue
            # Fresh means: completed on the latest CLOSED candle. Stale
            # confirmations are never turned into "predictions" after the fact.
            if result.completed_at != len(candles) - 1:
                continue
            if result.direction not in ("bullish", "bearish"):
                continue
            if PaperForwardPrediction.objects.filter(
                strategy=strategy, signal_candle_open_time=signal_open
            ).exists():
                continue

            payload = {
                "catalog_key": spec.key,
                "pdf_pages": spec.pdf_pages,
                "detector_key": strategy.detector_key,
                "state": result.state,
                "direction": result.direction,
                "evidence": list(result.observed_evidence),
                "missing_conditions": list(result.missing_conditions),
                "candle_refs": list(result.candle_refs),
                "reference_level": result.reference_level,
                "level_kind": result.level_kind,
                "stochastic_supported": result.stochastic_supported,
                "written_before_outcome": True,
            }
            created.append(
                PaperForwardPrediction.objects.create(
                    strategy=strategy,
                    instrument=instrument,
                    timeframe=timeframe,
                    market_type=market_type,
                    source=source,
                    detector_key=strategy.detector_key,
                    direction=result.direction,
                    signal_candle_open_time=signal_open,
                    signal_candle_close_time=signal_open + timedelta(seconds=interval),
                    signal_close_price=float(candles[-1]["close"]),
                    prediction_payload=payload,
                    payload_sha256=payload_digest(payload),
                )
            )
        return created

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def resolve(
        self,
        candles: list[dict[str, Any]],
        *,
        instrument: str = "",
        timeframe: str = "",
        source: str = "",
        resolved_at=None,
    ) -> list[PaperForwardPrediction]:
        """Resolve pending predictions whose outcome candle is complete.

        ``instrument``/``timeframe``/``source`` scope the search so candles of
        one feed can never resolve a prediction recorded from another feed
        (matching is by exact outcome-window timestamp).
        """
        by_open = {c.get("open_time"): c for c in candles if c.get("open_time") is not None}
        resolved: list[PaperForwardPrediction] = []
        pending = PaperForwardPrediction.objects.filter(
            status=PaperForwardPrediction.PENDING
        ).order_by("signal_candle_open_time")
        if instrument:
            pending = pending.filter(instrument=instrument)
        if timeframe:
            pending = pending.filter(timeframe=timeframe)
        if source:
            pending = pending.filter(source=source)
        for prediction in pending:
            outcome = by_open.get(prediction.signal_candle_close_time)
            if outcome is None:
                continue  # outcome window not in this data - nothing guessed
            if not bool(outcome.get("complete", outcome.get("is_complete", False))):
                continue  # forming candle - never read as an outcome
            prediction.resolve(
                outcome_candle={
                    "open_time": outcome["open_time"],
                    "close": float(outcome["close"]),
                    "complete": True,
                },
                resolved_at=resolved_at or timezone.now(),
            )
            resolved.append(prediction)
        return resolved

    # ------------------------------------------------------------------
    # Settlement bridge (quotes required - see settlement service)
    # ------------------------------------------------------------------
    def settle(
        self,
        prediction: PaperForwardPrediction,
        *,
        entry_quote: float | None = None,
        settlement_quote: float | None = None,
        price_source: str = "",
        payout_rate: float = 80.0,
        stake: float = 1.0,
        expiry_time: str = "",
    ) -> dict[str, Any]:
        """Evaluate settlement for one prediction from supplied platform quotes."""
        from apps.book_strategies.services.settlement import BookSettlementService

        record = BookSettlementService().evaluate(
            direction=prediction.direction,
            entry_quote=entry_quote,
            settlement_quote=settlement_quote,
            price_source=price_source,
            market_type=prediction.market_type,
            payout_rate=payout_rate,
            stake=stake,
            expiry_time=expiry_time,
        )
        prediction.settlement_status = record["status"]
        prediction.settlement = record
        prediction.save(update_fields=["settlement_status", "settlement", "updated_at"])
        return record

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def summary(
        self,
        predictions: list[PaperForwardPrediction] | None = None,
        *,
        min_signals: int = DEFAULT_MIN_SIGNALS,
    ) -> dict[str, Any]:
        """Honest aggregate: pending excluded, no invented rates."""
        rows = (
            list(predictions)
            if predictions is not None
            else list(PaperForwardPrediction.objects.all())
        )
        per_strategy: dict[str, dict[str, Any]] = {}
        settlement_counts: dict[str, int] = {}
        for row in rows:
            bucket = per_strategy.setdefault(
                row.strategy.key,
                {
                    "strategy_key": row.strategy.key,
                    "recorded": 0,
                    "pending": 0,
                    "resolved": 0,
                    "correct": 0,
                    "up": 0,
                    "down": 0,
                },
            )
            bucket["recorded"] += 1
            settlement_counts[row.settlement_status] = (
                settlement_counts.get(row.settlement_status, 0) + 1
            )
            if row.status == PaperForwardPrediction.PENDING:
                bucket["pending"] += 1
                continue
            bucket["resolved"] += 1
            if row.outcome_correct:
                bucket["correct"] += 1
            if row.outcome_up:
                bucket["up"] += 1
            else:
                bucket["down"] += 1

        resolved_total = sum(b["resolved"] for b in per_strategy.values())
        correct_total = sum(b["correct"] for b in per_strategy.values())
        accuracy = (correct_total / resolved_total) if resolved_total else None
        lo, hi = wilson_interval(correct_total, resolved_total)
        for bucket in per_strategy.values():
            n = bucket["resolved"]
            c = bucket["correct"]
            bucket["accuracy"] = (c / n) if n else None
            bucket["wilson_95"] = list(wilson_interval(c, n))
            bucket["sufficient_data"] = n >= min_signals
            bucket["insufficient_reason"] = (
                None
                if n >= min_signals
                else f"only {n} resolved paper predictions; below the "
                f"{min_signals}-record threshold for validation claims"
            )

        return {
            "metric_scope": PAPER_METRIC_SCOPE,
            "disclaimer": PAPER_DISCLAIMER,
            "recorded": len(rows),
            "pending": sum(1 for r in rows if r.status == PaperForwardPrediction.PENDING),
            "resolved": resolved_total,
            "correct": correct_total,
            "accuracy": accuracy,
            "wilson_95": [lo, hi],
            "sufficient_data": resolved_total >= min_signals,
            "insufficient_reason": (
                None
                if resolved_total >= min_signals
                else f"only {resolved_total} resolved paper predictions; below "
                f"the {min_signals}-record threshold for validation claims"
            ),
            "settlement_status_counts": settlement_counts,
            "per_strategy": [per_strategy[k] for k in sorted(per_strategy)],
            "integrity": {
                "method": "sha256 canonical payload digest",
                "rows_checked": len(rows),
                "mismatches": sum(1 for r in rows if not r.verify_integrity()),
            },
            "approval_effect": "none: paper records never change research_status or decision_use_approved",
            "approved_for_decision_use": False,
        }


__all__ = ["PAPER_DISCLAIMER", "PAPER_METRIC_SCOPE", "PaperForwardService"]
