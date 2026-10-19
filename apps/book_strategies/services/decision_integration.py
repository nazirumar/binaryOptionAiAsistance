# book_strategies/services/decision_integration.py
"""Book strategies as decision-engine candidates, behind the approval gate
(Phase 13, requirement 9).

The engine's existing NO TRADE safeguards are untouched: this module only
*adds* candidates, and only when ALL of the following hold:

1. ``decision_use_approved`` is True - set only by explicit human approval
   after documented validation (never by seed, import, backtest or test data);
2. ``recognition_enabled`` is True (the admin recognition switch);
3. a detector exists and reports CONFIRMED_PATTERN on the latest CLOSED
   candle (fresh; stale confirmations are not current setups);
4. the caller reports no forming candle.

Appended AFTER the engine's own candidates (book evidence never displaces
native candidates), exceptions degrade to "no book candidates", and the
decision engine still applies every invalidation, contradiction, timing and
data-quality gate - a book candidate can never override a NO TRADE. Nothing
here sets probability: it stays UNAVAILABLE_UNCALIBRATED.
"""

from __future__ import annotations

from typing import Any

from apps.book_strategies.constants import PROBABILITY_STATUS, BookPatternState
from apps.book_strategies.services.detectors import BOOK_DETECTORS
from apps.strategy_engine.constants import (
    CandidateStatus,
    EvaluationDirection,
    StrategyFamily,
)
from apps.strategy_engine.schemas.output import Candidate

#: Recorded inside every book candidate's evidence for auditability.
APPROVAL_NOTE = (
    "book candidate included only because decision_use_approved was set by "
    "explicit human approval; the engine's NO TRADE safeguards still apply "
    "and probability remains unavailable (uncalibrated)"
)


def approved_book_strategies() -> list[Any]:
    """Rows eligible to contribute candidates: approved AND recognition on."""
    from apps.book_strategies.models import BookStrategy

    return list(
        BookStrategy.objects.filter(
            decision_use_approved=True, recognition_enabled=True
        )
        .exclude(detector_key="")
        .order_by("key")
    )


def book_strategy_candidates(
    candles: list[dict[str, Any]],
    *,
    last_candle_forming: bool,
    instrument: str = "",
    timeframe: str = "",
    market_type: str = "",
) -> list[Candidate]:
    """Engine candidates from explicitly approved book strategies.

    Returns ``[]`` in the default world (nothing approved) - the integration
    is inert unless a human has approved a strategy.
    """
    if last_candle_forming or not candles:
        return []
    rows = approved_book_strategies()
    if not rows:
        return []

    candidates: list[Candidate] = []
    for row in rows:
        try:
            detector = BOOK_DETECTORS.get(row.detector_key)
            if detector is None:
                continue
            result = detector(list(candles))
            if result.state != BookPatternState.CONFIRMED_PATTERN:
                continue
            # Fresh setup only: completed on the latest closed candle.
            if result.completed_at != len(candles) - 1:
                continue
            if result.direction not in ("bullish", "bearish"):
                continue
            direction = (
                EvaluationDirection.UP
                if result.direction == "bullish"
                else EvaluationDirection.DOWN
            )
            candidates.append(
                Candidate(
                    direction=direction,
                    strategy_family=StrategyFamily.BOOK_PATTERN,
                    status=CandidateStatus.VALID,
                    supporting_evidence=[
                        {
                            "source": "book_pattern",
                            "strategy_key": row.key,
                            "strategy_name": row.name,
                            "state": result.state,
                            "evidence": list(result.observed_evidence),
                            "candle_refs": list(result.candle_refs),
                            "research_status": row.research_status,
                            "approval": "decision_use_approved=True",
                            "note": APPROVAL_NOTE,
                        }
                    ],
                    contradictory_evidence=[],
                    required_conditions=[],
                    missing_conditions=list(result.missing_conditions),
                    invalidation_conditions=list(result.invalidations),
                    candle_refs=list(result.candle_refs),
                    price_levels=(
                        [result.reference_level]
                        if result.reference_level is not None
                        else []
                    ),
                    metrics={
                        "book_key": row.key,
                        "detector": row.detector_key,
                        "market_type": market_type,
                        "instrument": instrument,
                        "timeframe": timeframe,
                        "state": result.state,
                        "decision_use_approved": True,
                        "probability_status": PROBABILITY_STATUS,
                    },
                )
            )
        except Exception:
            # A detector failure degrades to "no book candidate" - the engine
            # behaves exactly as before this integration existed.
            continue
    return candidates


__all__ = [
    "APPROVAL_NOTE",
    "approved_book_strategies",
    "book_strategy_candidates",
]
