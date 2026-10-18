# apps/trading_journal/services/journal_performance.py
"""Journal performance calculations (Phase 9, Step 9).

All metrics are computed from **recorded** journal data only. Nothing is
fabricated and real/demo/backtest/hypothetical records are never blended: the
caller must either request a single ``trade_type`` or receive an explicitly
segmented breakdown.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet

from apps.trading_journal.constants import SETTLED_RESULTS, TradeResult
from apps.trading_journal.models import JournalTrade

#: Shown wherever a metric cannot be computed from the recorded data.
INSUFFICIENT_DATA = "Insufficient validated data."


@dataclass
class BucketStats:
    """Win/loss/P&L aggregates for a group of settled trades."""

    key: str
    total: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    net_profit_loss: Decimal = Decimal("0.00")
    stakes: Decimal = Decimal("0.00")

    @property
    def decided(self) -> int:
        """Trades with a win/loss outcome (ties excluded from win-rate)."""
        return self.wins + self.losses

    @property
    def win_rate(self) -> float | None:
        if self.decided == 0:
            return None
        return round(self.wins / self.decided, 4)

    @property
    def average_stake(self) -> Decimal | None:
        if self.total == 0:
            return None
        return (self.stakes / Decimal(self.total)).quantize(Decimal("0.01"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "total": self.total,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "decided": self.decided,
            "win_rate": self.win_rate,
            "net_profit_loss": str(self.net_profit_loss),
            "average_stake": str(self.average_stake) if self.average_stake is not None else None,
        }


@dataclass
class PerformanceSummary:
    """Full performance summary for one provenance segment."""

    total_recorded: int = 0
    settled: int = 0
    pending: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    net_profit_loss: Decimal = Decimal("0.00")
    total_staked: Decimal = Decimal("0.00")
    average_payout: Decimal | None = None
    max_drawdown: Decimal = Decimal("0.00")
    max_winning_streak: int = 0
    max_losing_streak: int = 0
    by_strategy: list[BucketStats] = field(default_factory=list)
    by_instrument: list[BucketStats] = field(default_factory=list)
    by_session: list[BucketStats] = field(default_factory=list)

    @property
    def decided(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float | None:
        if self.decided == 0:
            return None
        return round(self.wins / self.decided, 4)

    @property
    def has_settled_data(self) -> bool:
        return self.settled > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_recorded": self.total_recorded,
            "settled": self.settled,
            "pending": self.pending,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "decided": self.decided,
            "win_rate": self.win_rate if self.has_settled_data else None,
            "win_rate_display": (
                f"{round(self.win_rate * 100, 1)}%"
                if self.win_rate is not None
                else INSUFFICIENT_DATA
            ),
            "net_profit_loss": str(self.net_profit_loss),
            "total_staked": str(self.total_staked),
            "average_payout": (
                str(self.average_payout) if self.average_payout is not None else None
            ),
            "max_drawdown": str(self.max_drawdown),
            "max_winning_streak": self.max_winning_streak,
            "max_losing_streak": self.max_losing_streak,
            "by_strategy": [b.to_dict() for b in self.by_strategy],
            "by_instrument": [b.to_dict() for b in self.by_instrument],
            "by_session": [b.to_dict() for b in self.by_session],
            "insufficient_data": not self.has_settled_data,
        }


def _session_of(trade: JournalTrade) -> str:
    """Classify a trade into a coarse trading session (UTC)."""
    ts = trade.entry_timestamp
    if isinstance(ts, str):
        try:
            from datetime import datetime

            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return "Unknown"
    try:
        hour = ts.hour
    except Exception:
        return "Unknown"
    if 0 <= hour < 7:
        return "Asia"
    if 7 <= hour < 12:
        return "London"
    if 12 <= hour < 17:
        return "London/NY overlap"
    if 17 <= hour < 22:
        return "New York"
    return "Sydney"


class JournalPerformance:
    """Compute performance for a queryset of journal trades.

    The queryset must already be scoped to a single owner by the caller.
    """

    def __init__(self, trades: Iterable[JournalTrade]) -> None:
        self.trades = list(trades)

    # -- Public API -------------------------------------------------------
    def summary(self, trade_type: str | None = None) -> PerformanceSummary:
        trades = self._filter(trade_type)
        summary = PerformanceSummary(total_recorded=len(trades))
        settled_trades: list[JournalTrade] = []
        for trade in trades:
            if trade.result == TradeResult.PENDING:
                summary.pending += 1
                continue
            if trade.result not in SETTLED_RESULTS:
                continue
            settled_trades.append(trade)
            summary.settled += 1
            if trade.result == TradeResult.WIN:
                summary.wins += 1
            elif trade.result == TradeResult.LOSS:
                summary.losses += 1
            else:
                summary.ties += 1
            if trade.profit_loss is not None:
                summary.net_profit_loss += trade.profit_loss
            if trade.stake is not None:
                summary.total_staked += trade.stake
            if trade.payout_percent is not None:
                # Average over recorded payouts (simple mean).
                summary.average_payout = (
                    trade.payout_percent
                    if summary.average_payout is None
                    else (summary.average_payout + trade.payout_percent) / 2
                )

        if summary.average_payout is not None:
            summary.average_payout = summary.average_payout.quantize(Decimal("0.01"))
        summary.net_profit_loss = summary.net_profit_loss.quantize(Decimal("0.01"))
        summary.total_staked = summary.total_staked.quantize(Decimal("0.01"))

        ordered = sorted(settled_trades, key=lambda t: (t.entry_timestamp, t.pk or 0))
        summary.max_drawdown = self._max_drawdown(ordered)
        streak_win, streak_loss = self._streaks(ordered)
        summary.max_winning_streak = streak_win
        summary.max_losing_streak = streak_loss

        summary.by_strategy = self._group(
            settled_trades, lambda t: t.strategy_family or "unspecified"
        )
        summary.by_instrument = self._group(settled_trades, lambda t: t.instrument or "unspecified")
        summary.by_session = self._group(settled_trades, _session_of)
        return summary

    def segmented_summary(self) -> dict[str, PerformanceSummary]:
        """One summary per ``trade_type`` (never combined)."""
        from apps.trading_journal.constants import TradeType

        return {trade_type.value: self.summary(trade_type.value) for trade_type in TradeType}

    # -- Internals --------------------------------------------------------
    def _filter(self, trade_type: str | None) -> list[JournalTrade]:
        if trade_type is None:
            return list(self.trades)
        return [t for t in self.trades if t.trade_type == trade_type]

    @staticmethod
    def _max_drawdown(ordered: list[JournalTrade]) -> Decimal:
        peak = Decimal("0.00")
        equity = Decimal("0.00")
        worst = Decimal("0.00")
        for trade in ordered:
            equity += trade.profit_loss or Decimal("0.00")
            if equity > peak:
                peak = equity
            drawdown = peak - equity
            if drawdown > worst:
                worst = drawdown
        return worst.quantize(Decimal("0.01"))

    @staticmethod
    def _streaks(ordered: list[JournalTrade]) -> tuple[int, int]:
        max_win = max_loss = cur_win = cur_loss = 0
        for trade in ordered:
            if trade.result == TradeResult.WIN:
                cur_win += 1
                cur_loss = 0
            elif trade.result == TradeResult.LOSS:
                cur_loss += 1
                cur_win = 0
            else:  # tie breaks no streak but does not extend one
                cur_win = 0
                cur_loss = 0
            max_win = max(max_win, cur_win)
            max_loss = max(max_loss, cur_loss)
        return max_win, max_loss

    @staticmethod
    def _group(trades: list[JournalTrade], key_fn) -> list[BucketStats]:  # type: ignore[no-untyped-def]
        buckets: dict[str, BucketStats] = {}
        for trade in trades:
            key = key_fn(trade)
            bucket = buckets.setdefault(key, BucketStats(key=key))
            bucket.total += 1
            if trade.result == TradeResult.WIN:
                bucket.wins += 1
            elif trade.result == TradeResult.LOSS:
                bucket.losses += 1
            else:
                bucket.ties += 1
            bucket.net_profit_loss += trade.profit_loss or Decimal("0.00")
            bucket.stakes += trade.stake or Decimal("0.00")
        for bucket in buckets.values():
            bucket.net_profit_loss = bucket.net_profit_loss.quantize(Decimal("0.01"))
            bucket.stakes = bucket.stakes.quantize(Decimal("0.01"))
        return sorted(buckets.values(), key=lambda b: (-b.total, b.key))


def performance_for_queryset(queryset: QuerySet[JournalTrade]) -> dict[str, Any]:
    """Convenience helper returning segmented performance for a queryset."""
    return {
        segment: summary.to_dict()
        for segment, summary in JournalPerformance(queryset).segmented_summary().items()
    }


__all__ = [
    "INSUFFICIENT_DATA",
    "BucketStats",
    "JournalPerformance",
    "PerformanceSummary",
    "performance_for_queryset",
]
