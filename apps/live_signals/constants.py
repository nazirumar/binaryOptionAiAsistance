# live_signals/constants.py
"""Enumerations and invariants for the Phase 15 live-signals monitor.

Everything here is chosen so that the monitor can NEVER manufacture a signal:

* A candle is only ever evaluated once it is **closed** (see
  ``apps.market_data.services.candle_service.is_candle_complete``); a forming
  candle is reported, never traded on.
* A *pattern alert* records a recognised shape. A *directional signal* may only
  be produced by a strategy that is explicitly ``decision_use_approved`` — the
  exact same human-gated switch the decision engine already honours
  (``apps.book_strategies.services.decision_integration``).
* OTC instruments are never satisfied by a regular market feed and vice versa;
  incompatible feeds yield ``UNVERIFIABLE`` outcomes rather than a guessed one.
"""

from __future__ import annotations

from apps.market_data.constants import Timeframe


class SignalCategory:
    """What a signal row is allowed to claim.

    The three categories are deliberately separate so the UI (and any reader)
    can never confuse an observation with an approved directional call.
    """

    #: A shape the detector recognised from closed candles. No direction claim.
    EXPERIMENTAL_PATTERN = "experimental_pattern"
    #: A recognised shape that satisfied every deterministic book condition.
    CONFIRMED_PATTERN = "confirmed_pattern"
    #: A direction claim from a strategy with documented validation AND
    #: explicit decision-use approval. The only category that carries UP/DOWN.
    RESEARCH_VALIDATED = "research_validated"

    ALL = (EXPERIMENTAL_PATTERN, CONFIRMED_PATTERN, RESEARCH_VALIDATED)

    CHOICES = (
        (EXPERIMENTAL_PATTERN, "Experimental pattern detection"),
        (CONFIRMED_PATTERN, "Confirmed pattern alert"),
        (RESEARCH_VALIDATED, "Research-validated directional signal"),
    )


class SignalStatus:
    """Lifecycle of one monitored setup.

    ``FORMING`` and ``AWAITING_CONFIRMATION`` describe an in-progress pattern;
    ``CONFIRMED_PATTERN`` is a completed recognition; ``INVALIDATED`` records a
    fired invalidation rule; ``EXPIRED`` means the intended window passed with
    no confirmation; ``UNVERIFIABLE`` means the outcome can never be checked
    against a compatible feed.
    """

    FORMING = "FORMING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    CONFIRMED_PATTERN = "CONFIRMED_PATTERN"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    UNVERIFIABLE = "UNVERIFIABLE"

    ALL = (
        FORMING,
        AWAITING_CONFIRMATION,
        CONFIRMED_PATTERN,
        INVALIDATED,
        EXPIRED,
        UNVERIFIABLE,
    )

    CHOICES = (
        (FORMING, "Forming"),
        (AWAITING_CONFIRMATION, "Awaiting confirmation"),
        (CONFIRMED_PATTERN, "Confirmed pattern"),
        (INVALIDATED, "Invalidated"),
        (EXPIRED, "Expired"),
        (UNVERIFIABLE, "Unverifiable"),
    )

    #: Statuses that mean "this is a live, actionable recognition".
    CONFIRMED = (CONFIRMED_PATTERN,)
    #: Statuses that are terminal and never change again.
    TERMINAL = (INVALIDATED, EXPIRED, UNVERIFIABLE)


class SignalDirection:
    """Direction vocabulary; deliberately distinct from the engine's UP/DOWN."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NONE = "none"

    CHOICES = (
        (BULLISH, "Bullish"),
        (BEARISH, "Bearish"),
        (NONE, "None"),
    )


class OutcomeStatus:
    """Paper-outcome verification status (never a live trading result)."""

    PENDING = "pending"
    VERIFIED_CORRECT = "verified_correct"
    VERIFIED_INCORRECT = "verified_incorrect"
    TIE = "tie"
    UNVERIFIABLE = "unverifiable"

    ALL = (PENDING, VERIFIED_CORRECT, VERIFIED_INCORRECT, TIE, UNVERIFIABLE)

    CHOICES = (
        (PENDING, "Awaiting outcome"),
        (VERIFIED_CORRECT, "Verified correct"),
        (VERIFIED_INCORRECT, "Verified incorrect"),
        (TIE, "Tie"),
        (UNVERIFIABLE, "Unverifiable"),
    )


class MonitorState:
    """Whole-monitor lifecycle, persisted so restarts can resume honestly."""

    IDLE = "idle"
    RUNNING = "running"
    DEGRADED = "degraded"
    ERROR = "error"
    STOPPED = "stopped"

    CHOICES = (
        (IDLE, "Idle"),
        (RUNNING, "Running"),
        (DEGRADED, "Degraded"),
        (ERROR, "Error"),
        (STOPPED, "Stopped"),
    )


class FeedState:
    """Health of the candle feed backing one instrument monitor."""

    OK = "ok"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"

    CHOICES = (
        (OK, "OK"),
        (STALE, "Stale"),
        (UNAVAILABLE, "Unavailable"),
        (INCOMPATIBLE, "Incompatible"),
    )


#: The timeframes Phase 15 monitoring supports. Restricted to the low
#: timeframes the brief asks for; the wider ``Timeframe`` enum still exists for
#: storage, but monitors only ever accept these.
MONITORABLE_TIMEFRAMES: tuple[str, ...] = (
    Timeframe.M1,
    Timeframe.M2,
    Timeframe.M3,
    Timeframe.M5,
    Timeframe.M15,
)

#: Seconds per monitored timeframe (drives expiry and freshness windows).
TIMEFRAME_SECONDS: dict[str, int] = {
    Timeframe.M1: 60,
    Timeframe.M2: 120,
    Timeframe.M3: 180,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
}

#: Probability is never produced by the monitor. Recorded on every row so no
#: consumer can read an absent field as "zero".
PROBABILITY_STATUS = "UNAVAILABLE_UNCALIBRATED"

#: A signal's intended expiry: how many of its own candles may elapse after the
#: confirmation candle before an unconfirmed setup is declared EXPIRED.
DEFAULT_EXPIRY_CANDLES = 1

#: Human-readable disclaimer attached to every surface that shows signals.
SIGNALS_DISCLAIMER = (
    "Live signals are research and paper-monitoring records generated from "
    "closed candles only. They never place trades, never carry a probability, "
    "and a directional signal exists only for a strategy with documented "
    "validation and explicit decision-use approval."
)

MONITOR_DISCLAIMER = (
    "The monitor evaluates closed candles from a compatible market feed. "
    "OTC instruments cannot be verified against a regular feed and are marked "
    "UNVERIFIABLE rather than guessed."
)

__all__ = [
    "DEFAULT_EXPIRY_CANDLES",
    "MONITORABLE_TIMEFRAMES",
    "MONITOR_DISCLAIMER",
    "PROBABILITY_STATUS",
    "SIGNALS_DISCLAIMER",
    "TIMEFRAME_SECONDS",
    "FeedState",
    "MonitorState",
    "OutcomeStatus",
    "SignalCategory",
    "SignalDirection",
    "SignalStatus",
]
