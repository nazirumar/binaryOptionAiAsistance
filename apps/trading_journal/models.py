# apps/trading_journal/models.py
"""Trading-journal models (Phase 9).

A journal entry is a *manually recorded* observation of a trade outcome. The
model never places a trade and never invents an outcome: profit/loss is derived
only from values the user supplies (``stake``, ``payout_percent``, ``result``).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel
from apps.trading_journal.constants import (
    SETTLED_RESULTS,
    EmotionalState,
    TradeDirection,
    TradeResult,
    TradeType,
)


def _to_decimal(value, default: Decimal | None = None) -> Decimal | None:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


class JournalTrade(TimeStampedModel):
    """A single manually recorded trade (real, demo, backtest or hypothetical)."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="journal_trades",
    )

    trade_type = models.CharField(
        max_length=16,
        choices=TradeType.choices,
        default=TradeType.DEMO,
        db_index=True,
        help_text="Provenance. Real, demo, backtest and hypothetical records are never combined.",
    )

    # Identification
    instrument = models.CharField(max_length=32, db_index=True)
    market_type = models.CharField(max_length=16, blank=True)
    direction = models.CharField(max_length=8, choices=TradeDirection.choices)
    strategy_family = models.CharField(max_length=32, blank=True, db_index=True)

    # Timing
    entry_timestamp = models.DateTimeField(db_index=True)
    expiration_timestamp = models.DateTimeField(null=True, blank=True)

    # Quotes and settlement (all user-supplied; never fabricated)
    entry_quote = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    settlement_quote = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)

    # Money
    stake = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    payout_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Net payout rate as a percentage of stake on a win (e.g. 80.00).",
    )
    result = models.CharField(
        max_length=8,
        choices=TradeResult.choices,
        default=TradeResult.PENDING,
        db_index=True,
    )
    profit_loss = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Derived from stake, payout_percent and result; may be overridden.",
    )

    # Evidence links (optional)
    screenshot = models.ForeignKey(
        "chart_vision.ChartScreenshot",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_trades",
    )
    analysis = models.ForeignKey(
        "ai_assistant.AIAnalysisSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_trades",
    )
    strategy_evaluation = models.ForeignKey(
        "strategy_engine.StrategyEvaluation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_trades",
    )

    # Self-review
    notes = models.TextField(blank=True)
    emotional_state = models.CharField(max_length=16, choices=EmotionalState.choices, blank=True)
    mistakes = models.TextField(blank=True)
    lessons_learned = models.TextField(blank=True)

    class Meta:
        ordering = ["-entry_timestamp", "-created_at"]
        indexes = [
            models.Index(fields=["owner", "trade_type", "-entry_timestamp"]),
            models.Index(fields=["owner", "-entry_timestamp"]),
            models.Index(fields=["owner", "result"]),
            models.Index(fields=["owner", "strategy_family"]),
        ]

    def __str__(self) -> str:
        return f"#{self.pk} {self.instrument} {self.direction} [{self.trade_type}/{self.result}]"

    # -- Derived values ---------------------------------------------------
    @property
    def is_settled(self) -> bool:
        return self.result in SETTLED_RESULTS

    @property
    def is_real_money(self) -> bool:
        return self.trade_type == TradeType.REAL

    def compute_profit_loss(self) -> Decimal:
        """Derive P/L from the recorded inputs.

        * win  -> ``stake * payout_percent / 100``
        * loss -> ``-stake``
        * tie / pending -> ``0``
        """
        stake = _to_decimal(self.stake, Decimal("0")) or Decimal("0")
        if self.result == TradeResult.WIN:
            payout = _to_decimal(self.payout_percent, Decimal("0")) or Decimal("0")
            return (stake * payout / Decimal("100")).quantize(Decimal("0.01"))
        if self.result == TradeResult.LOSS:
            return (-stake).quantize(Decimal("0.01"))
        return Decimal("0.00")

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        # Only auto-derive when the caller has not supplied an explicit value.
        if self.profit_loss is None and self.result in SETTLED_RESULTS:
            self.profit_loss = self.compute_profit_loss()
        elif self.result == TradeResult.PENDING:
            self.profit_loss = None
        super().save(*args, **kwargs)


__all__ = ["JournalTrade"]
