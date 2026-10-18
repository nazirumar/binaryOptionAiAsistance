# apps/dashboard/services/analytics_service.py
"""Strategy analytics (Phase 9, Step 6).

Analytics are computed over *strategy evaluations* (one row per assessed
setup), never over individual evidence items. Counts of overlapping evidence
are therefore not double-counted as independent trades. Directional accuracy is
only reported when labelled outcomes exist.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.strategy_engine.constants import (
    CandidateStatus,
    EvaluationDirection,
    StrategyFamily,
)
from apps.strategy_engine.models import (
    EvaluationEvidence,
    StrategyEvaluation,
)
from apps.trading_journal.constants import TradeResult
from apps.trading_journal.models import JournalTrade

INSUFFICIENT_DATA = "Insufficient validated data."

#: Course concepts surfaced as strategy families in the analytics view.
FAMILY_LABELS = dict(StrategyFamily.choices)


class StrategyAnalytics:
    """Aggregate strategy-evaluation analytics for one user."""

    def __init__(self, user) -> None:  # type: ignore[no-untyped-def]
        self.user = user

    def build(self) -> dict[str, Any]:
        evaluations = StrategyEvaluation.objects.filter(owner=self.user)
        return {
            "totals": self._totals(evaluations),
            "by_family": self._by_family(evaluations),
            "by_timeframe": self._by_field(evaluations, "timeframe"),
            "by_instrument": self._by_field(evaluations, "instrument"),
            "by_regime": self._by_field(evaluations, "market_context"),
            "evidence_summary": self._evidence_summary(evaluations),
            "verified_outcomes": self._verified_outcomes(),
        }

    def _totals(self, evaluations) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        aggregated = evaluations.aggregate(
            total=Count("id"),
            up=Count("id", filter=Q(direction=EvaluationDirection.UP)),
            down=Count("id", filter=Q(direction=EvaluationDirection.DOWN)),
            no_trade=Count("id", filter=Q(direction=EvaluationDirection.NO_TRADE)),
            accepted=Count(
                "id",
                filter=Q(
                    direction__in=[EvaluationDirection.UP, EvaluationDirection.DOWN],
                    status__in=[CandidateStatus.VALID, CandidateStatus.WEAK],
                ),
            ),
            rejected=Count("id", filter=Q(status=CandidateStatus.REJECTED)),
        )
        return {
            "total_evaluations": aggregated["total"] or 0,
            "up": aggregated["up"] or 0,
            "down": aggregated["down"] or 0,
            "no_trade": aggregated["no_trade"] or 0,
            "accepted": aggregated["accepted"] or 0,
            "rejected": aggregated["rejected"] or 0,
        }

    def _by_family(self, evaluations) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
        rows = (
            evaluations.values("strategy_family")
            .annotate(
                total=Count("id"),
                up=Count("id", filter=Q(direction=EvaluationDirection.UP)),
                down=Count("id", filter=Q(direction=EvaluationDirection.DOWN)),
                no_trade=Count("id", filter=Q(direction=EvaluationDirection.NO_TRADE)),
            )
            .order_by("-total")
        )
        return [
            {
                "family": row["strategy_family"],
                "label": FAMILY_LABELS.get(row["strategy_family"], row["strategy_family"]),
                "total": row["total"],
                "up": row["up"],
                "down": row["down"],
                "no_trade": row["no_trade"],
            }
            for row in rows
        ]

    def _by_field(self, evaluations, field: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
        rows = (
            evaluations.exclude(**{f"{field}": ""})
            .values(field)
            .annotate(total=Count("id"))
            .order_by("-total")[:20]
        )
        return [{"key": row[field] or "unspecified", "total": row["total"]} for row in rows]

    def _evidence_summary(self, evaluations) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        evidence = EvaluationEvidence.objects.filter(evaluation__owner=self.user)
        return {
            "supporting": evidence.filter(is_supporting=True).count(),
            "contradictory": evidence.filter(is_contradictory=True).count(),
            "note": (
                "Evidence rows may overlap across evaluations; they are never "
                "counted as independent trades."
            ),
        }

    def _verified_outcomes(self) -> dict[str, Any]:
        """Directional accuracy from settled journal trades, per family.

        Only settled real/demo trades that link to a strategy evaluation are
        considered; otherwise no accuracy figure is produced.
        """
        trades = JournalTrade.objects.filter(
            owner=self.user,
            result__in=[TradeResult.WIN, TradeResult.LOSS],
            strategy_evaluation__isnull=False,
        ).select_related("strategy_evaluation")
        total = trades.count()
        if total == 0:
            return {"available": False, "message": INSUFFICIENT_DATA, "by_family": []}
        buckets: dict[str, dict[str, int]] = {}
        for trade in trades:
            family = trade.strategy_evaluation.strategy_family or "unknown"
            bucket = buckets.setdefault(family, {"wins": 0, "losses": 0})
            if trade.result == TradeResult.WIN:
                bucket["wins"] += 1
            else:
                bucket["losses"] += 1
        by_family = []
        for family, counts in buckets.items():
            decided = counts["wins"] + counts["losses"]
            by_family.append(
                {
                    "family": family,
                    "label": FAMILY_LABELS.get(family, family),
                    "wins": counts["wins"],
                    "losses": counts["losses"],
                    "accuracy": round(counts["wins"] / decided, 4) if decided else None,
                }
            )
        return {"available": True, "message": None, "by_family": by_family}


def daily_decision_series(user, days: int = 30) -> list[dict[str, Any]]:
    """Daily UP/DOWN/NO_TRADE counts for inline sparkline charts."""
    since = timezone.now() - timedelta(days=days)
    rows = (
        StrategyEvaluation.objects.filter(owner=user, created_at__gte=since)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(
            up=Count("id", filter=Q(direction=EvaluationDirection.UP)),
            down=Count("id", filter=Q(direction=EvaluationDirection.DOWN)),
            no_trade=Count("id", filter=Q(direction=EvaluationDirection.NO_TRADE)),
        )
        .order_by("day")
    )
    return [
        {
            "day": row["day"].isoformat() if row["day"] else None,
            "up": row["up"],
            "down": row["down"],
            "no_trade": row["no_trade"],
        }
        for row in rows
    ]


# Re-exported for convenience/tests.
__all__ = ["INSUFFICIENT_DATA", "StrategyAnalytics", "daily_decision_series"]
