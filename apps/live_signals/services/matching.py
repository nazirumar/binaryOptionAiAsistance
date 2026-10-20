# live_signals/services/matching.py
"""Strategy matching + eligibility gates for the live monitor (Phase 15).

This module is the *only* place that decides whether a detector result may
become a :class:`~apps.live_signals.models.LiveSignal`, and what category it
gets. Strategy logic itself is **not** reimplemented: matching delegates to the
existing deterministic detectors through
:class:`apps.book_strategies.services.recognition.BookStrategyRecognizer`, and
the approval gate reads the exact same ``BookStrategy.decision_use_approved``
flag the decision engine already honours.

Eligibility, in order (all must hold to even be considered):

1. candles are available and every one of them is closed;
2. the strategy is ``recognition_enabled``;
3. the strategy declares a deterministic detector;
4. the market-data feed is compatible with the instrument's market type.

Category assignment:

* ``RESEARCH_VALIDATED`` - only when the detector says ``CONFIRMED_PATTERN``
  **and** ``decision_use_approved`` is True **and** ``research_status`` is
  ``approved``. Only these carry a direction.
* ``CONFIRMED_PATTERN`` - detector confirmed but the strategy is not approved
  for decisions. Direction is stripped (recorded as ``none``).
* ``EXPERIMENTAL_PATTERN`` - a forming / awaiting setup. No direction.
* ``INVALIDATED`` status is emitted as a terminal observation for the record,
  never as a directional signal.
* ``INSUFFICIENT_DATA`` is skipped entirely (a monitor that has not seen enough
  closed candles must not emit a signal).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from apps.book_strategies.constants import BookPatternState, DataVerification
from apps.book_strategies.services.recognition import BookStrategyRecognizer
from apps.live_signals.constants import (
    DEFAULT_EXPIRY_CANDLES,
    PROBABILITY_STATUS,
    SignalCategory,
    SignalDirection,
    SignalStatus,
)
from apps.live_signals.services.providers import ProviderCandle

#: Recognition states that map onto a persisted signal status.
_STATE_TO_STATUS: dict[str, str] = {
    BookPatternState.FORMING: SignalStatus.FORMING,
    BookPatternState.AWAITING_CONFIRMATION: SignalStatus.AWAITING_CONFIRMATION,
    BookPatternState.CONFIRMED_PATTERN: SignalStatus.CONFIRMED_PATTERN,
    BookPatternState.INVALIDATED: SignalStatus.INVALIDATED,
}

#: Fed to the decision engine's vocabulary - patterns never trade.
_DECISION_NO_TRADE = "NO_TRADE"


@dataclass(slots=True)
class EligibilityDecision:
    """Whether a strategy may be evaluated for a monitor at all."""

    eligible: bool
    reason: str = ""
    feed_compatibility: str = DataVerification.OHLC_VERIFIED


@dataclass(slots=True)
class MatchedSignal:
    """A strategy evaluation mapped onto the live-signal shape."""

    strategy_key: str
    strategy_name: str
    strategy_version: str
    detector_key: str
    category: str
    status: str
    direction: str
    signal_candle_open_time: datetime
    signal_candle_close_time: datetime
    confirmation_candle_open_time: datetime | None
    candle_refs: list[int] = field(default_factory=list)
    observed_evidence: list[str] = field(default_factory=list)
    missing_conditions: list[str] = field(default_factory=list)
    invalidation_evidence: list[str] = field(default_factory=list)
    reference_level: float | None = None
    level_kind: str = ""
    approval_status: str = "not_approved"
    decision_use_approved: bool = False
    feed_compatibility: str = DataVerification.OHLC_VERIFIED
    data_verification: str = DataVerification.OHLC_VERIFIED
    expiry_rule: str = ""
    expires_after_candles: int = DEFAULT_EXPIRY_CANDLES
    decision: str = _DECISION_NO_TRADE
    probability_status: str = PROBABILITY_STATUS


def _candle_series(candles: list[ProviderCandle]) -> list[dict]:
    """Provider candles -> the detector's dict shape.

    Only closed candles are passed: the monitor's provider already guarantees
    this, and it is re-asserted here so a caller cannot slip a forming bar in.
    """
    return [c.as_detector_dict() for c in candles if c.is_complete]


def check_eligibility(
    strategy,
    *,
    instrument: str,
    timeframe: str,
    market_type: str,
    feed_is_otc: bool,
    instrument_is_otc: bool,
) -> EligibilityDecision:
    """Apply the approval + feed-compatibility gates for one strategy.

    A strategy is eligible only when it is recognition-enabled, has a detector,
    the feed's OTC nature matches the instrument's, and the timeframe is
    monitorable. Approval for *directional* signals is assessed separately (see
    :func:`categorise`), so an unapproved strategy stays visible as a pattern.
    """
    from apps.live_signals.constants import MONITORABLE_TIMEFRAMES

    if timeframe not in MONITORABLE_TIMEFRAMES:
        return EligibilityDecision(
            eligible=False,
            reason=f"timeframe {timeframe!r} is not monitored",
        )
    if not getattr(strategy, "recognition_enabled", False):
        return EligibilityDecision(
            eligible=False, reason="strategy recognition is disabled"
        )
    if not getattr(strategy, "detector_key", ""):
        return EligibilityDecision(
            eligible=False, reason="strategy has no deterministic detector"
        )
    # OTC guard: a regular feed may never stand in for an OTC instrument.
    if bool(feed_is_otc) != bool(instrument_is_otc):
        return EligibilityDecision(
            eligible=False,
            reason=(
                "market-data feed is incompatible: an OTC instrument cannot be "
                "verified with a non-OTC feed (or vice versa)"
            ),
            feed_compatibility=DataVerification.INCOMPATIBLE_FEEDS,
        )
    return EligibilityDecision(eligible=True)


def categorise(strategy, recognition_state: str) -> tuple[str, bool]:
    """Return ``(category, carries_direction)`` for a detector state.

    Only an approved strategy with documented validation and a confirmed
    pattern may carry a direction; every other state is a pattern observation.
    """
    approved = bool(getattr(strategy, "decision_use_approved", False))
    research_status = getattr(strategy, "research_status", "")
    validated = approved and research_status == "approved"

    if recognition_state == BookPatternState.CONFIRMED_PATTERN:
        if validated:
            return SignalCategory.RESEARCH_VALIDATED, True
        return SignalCategory.CONFIRMED_PATTERN, False
    # FORMING / AWAITING_CONFIRMATION are always experimental observations.
    return SignalCategory.EXPERIMENTAL_PATTERN, False


def _approved_status(strategy) -> str:
    if getattr(strategy, "decision_use_approved", False):
        return "approved_for_decision_use"
    research_status = getattr(strategy, "research_status", "")
    return f"not_approved ({research_status or 'extracted'})"


def match_strategy(
    strategy,
    candles: list[ProviderCandle],
    *,
    instrument: str,
    timeframe: str,
    market_type: str,
    feed_is_otc: bool,
    instrument_is_otc: bool,
    recognizer: BookStrategyRecognizer | None = None,
    persist_detection: bool = False,
) -> MatchedSignal | None:
    """Evaluate one strategy against closed candles and map the result.

    Returns ``None`` when the strategy is ineligible or the detector has
    insufficient data (no signal is fabricated for either case).
    """
    eligibility = check_eligibility(
        strategy,
        instrument=instrument,
        timeframe=timeframe,
        market_type=market_type,
        feed_is_otc=feed_is_otc,
        instrument_is_otc=instrument_is_otc,
    )
    if not eligibility.eligible:
        return None
    if not candles:
        return None

    series = _candle_series(candles)
    if not series:
        return None

    recognizer = recognizer or BookStrategyRecognizer()
    detection = recognizer.evaluate(
        strategy.key,
        series,
        instrument=instrument,
        timeframe=timeframe,
        market_type=market_type,
        last_candle_forming=False,
        persist=persist_detection,
    )

    if detection.recognition_status == BookPatternState.INSUFFICIENT_DATA:
        return None

    category, carries_direction = categorise(strategy, detection.recognition_status)
    status = _STATE_TO_STATUS.get(detection.recognition_status, SignalStatus.FORMING)

    direction = SignalDirection.NONE
    if carries_direction and detection.direction in ("bullish", "bearish"):
        direction = detection.direction

    from apps.market_data.services.timeframe_mapper import duration

    last_candle = candles[-1]
    close_time = last_candle.open_time + duration(timeframe)

    confirmation_open = None
    if detection.completed_at is not None and 0 <= detection.completed_at < len(candles):
        confirmation_open = candles[detection.completed_at].open_time

    version = getattr(getattr(strategy, "version", None), "version", "") or ""

    return MatchedSignal(
        strategy_key=strategy.key,
        strategy_name=strategy.name,
        strategy_version=str(version),
        detector_key=strategy.detector_key,
        category=category,
        status=status,
        direction=direction,
        signal_candle_open_time=last_candle.open_time,
        signal_candle_close_time=close_time,
        confirmation_candle_open_time=confirmation_open,
        candle_refs=list(detection.candle_refs),
        observed_evidence=list(detection.observed_evidence),
        missing_conditions=list(detection.missing_conditions),
        invalidation_evidence=list(detection.invalidations),
        reference_level=detection.reference_level,
        level_kind=detection.level_kind,
        approval_status=_approved_status(strategy),
        decision_use_approved=bool(getattr(strategy, "decision_use_approved", False)),
        feed_compatibility=eligibility.feed_compatibility,
        data_verification=detection.data_verification,
        expiry_rule=(
            f"expires {DEFAULT_EXPIRY_CANDLES} {timeframe} candle(s) after the "
            "confirmation candle"
        ),
        expires_after_candles=DEFAULT_EXPIRY_CANDLES,
        decision=_DECISION_NO_TRADE,
        probability_status=PROBABILITY_STATUS,
    )


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


__all__ = [
    "EligibilityDecision",
    "MatchedSignal",
    "categorise",
    "check_eligibility",
    "match_strategy",
    "utc_now",
]
