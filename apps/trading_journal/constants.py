# apps/trading_journal/constants.py
"""Enumerations for the manual/simulated trading journal (Phase 9).

The journal records *manually entered* outcomes. Nothing here triggers or
represents automatic trading. Real, demo, backtested and hypothetical records
are strictly separated so their statistics are never silently combined.
"""

from __future__ import annotations

from django.db import models


class TradeType(models.TextChoices):
    """Provenance of a journal entry.

    The distinction is contractual: a hypothetical or backtested record must
    never be presented as a real executed trade.
    """

    REAL = "real", "Real (executed with real money)"
    DEMO = "demo", "Demo (executed on a demo account)"
    BACKTEST = "backtest", "Backtested (historical simulation)"
    HYPOTHETICAL = "hypothetical", "Hypothetical research example"


class TradeDirection(models.TextChoices):
    """Direction of the binary-option contract."""

    CALL = "call", "Call (UP)"
    PUT = "put", "Put (DOWN)"


class TradeResult(models.TextChoices):
    """Settlement outcome."""

    WIN = "win", "Win"
    LOSS = "loss", "Loss"
    TIE = "tie", "Tie / refund"
    PENDING = "pending", "Pending (not settled)"


class EmotionalState(models.TextChoices):
    """Optional self-reported emotional state (analyst self-review)."""

    CALM = "calm", "Calm"
    CONFIDENT = "confident", "Confident"
    ANXIOUS = "anxious", "Anxious"
    FRUSTRATED = "frustrated", "Frustrated"
    FOMO = "fomo", "FOMO"
    REVENGE = "revenge", "Revenge trading"
    NEUTRAL = "neutral", "Neutral"


#: Types that represent money at risk (real or on a demo account).
EXECUTED_TYPES = frozenset({TradeType.REAL, TradeType.DEMO})
#: Types that are simulations / research only.
SIMULATED_TYPES = frozenset({TradeType.BACKTEST, TradeType.HYPOTHETICAL})

#: Human-readable assurance shown next to each type in the UI.
PROVENANCE_LABELS = {
    TradeType.REAL: "Real executed trade",
    TradeType.DEMO: "Demo account trade",
    TradeType.BACKTEST: "Backtested simulation",
    TradeType.HYPOTHETICAL: "Hypothetical research example",
}

#: Result values that are considered "settled" (exclude pending).
SETTLED_RESULTS = frozenset({TradeResult.WIN, TradeResult.LOSS, TradeResult.TIE})
