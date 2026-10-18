# apps/dashboard/services/overview_service.py
"""Overview dashboard metrics (Phase 9, Step 4).

Every value is read from the database. Accuracy/profitability figures are only
ever produced when *valid labelled outcomes* exist; otherwise the sentinel
:data:`INSUFFICIENT_DATA` is returned instead of a fabricated number.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Q
from django.utils import timezone

from apps.ai_assistant.models import AIAnalysisSession, AIConversation
from apps.chart_vision.constants import AnalysisStatus
from apps.chart_vision.models import ChartScreenshot, ScreenshotAnalysis
from apps.research.models import BacktestRun, CalibratedModel
from apps.strategy_engine.constants import EvaluationDirection
from apps.strategy_engine.models import StrategyEvaluation
from apps.trading_journal.constants import SETTLED_RESULTS, TradeType
from apps.trading_journal.models import JournalTrade

INSUFFICIENT_DATA = "Insufficient validated data."


class OverviewService:
    """Assemble the overview dashboard for one user."""

    def __init__(self, user) -> None:  # type: ignore[no-untyped-def]
        self.user = user

    def build(self) -> dict[str, Any]:
        return {
            "counts": self._counts(),
            "decisions": self._decisions(),
            "recent_analyses": self._recent_analyses(),
            "market": self._market_status(),
            "processing": self._processing_status(),
            "backtests": self._backtest_status(),
            "probability": self._probability_status(),
            "performance": self._performance(),
        }

    # -- Metrics ----------------------------------------------------------
    def _counts(self) -> dict[str, int]:
        return {
            "screenshot_analyses": ScreenshotAnalysis.objects.filter(owner=self.user).count(),
            "screenshots": ChartScreenshot.objects.filter(owner=self.user).count(),
            "strategy_evaluations": StrategyEvaluation.objects.filter(owner=self.user).count(),
            "ai_conversations": AIConversation.objects.filter(owner=self.user).count(),
            "ai_sessions": AIAnalysisSession.objects.filter(conversation__owner=self.user).count(),
            "journal_trades": JournalTrade.objects.filter(owner=self.user).count(),
        }

    def _decisions(self) -> dict[str, int]:
        queryset = StrategyEvaluation.objects.filter(owner=self.user)
        aggregated = queryset.aggregate(
            up=Count("id", filter=Q(direction=EvaluationDirection.UP)),
            down=Count("id", filter=Q(direction=EvaluationDirection.DOWN)),
            no_trade=Count("id", filter=Q(direction=EvaluationDirection.NO_TRADE)),
        )
        return {
            "up": aggregated["up"] or 0,
            "down": aggregated["down"] or 0,
            "no_trade": aggregated["no_trade"] or 0,
        }

    def _recent_analyses(self, limit: int = 8) -> list[dict[str, Any]]:
        analyses = (
            ScreenshotAnalysis.objects.filter(owner=self.user)
            .select_related("screenshot")
            .order_by("-created_at")[:limit]
        )
        return [
            {
                "id": analysis.pk,
                "status": analysis.status,
                "created_at": analysis.created_at,
                "screenshot_id": analysis.screenshot_id,
                "instrument": (analysis.chart_metadata or {}).get("instrument") or "—",
                "timeframe": (analysis.chart_metadata or {}).get("timeframe") or "—",
            }
            for analysis in analyses
        ]

    def _market_status(self) -> dict[str, Any]:
        from apps.market_data.dashboard import derived_connection_state
        from apps.market_data.models import MarketDataSyncLog

        last_sync = MarketDataSyncLog.objects.order_by("-started_at").first()
        return {
            "mt5_state": derived_connection_state(),
            "last_sync_at": getattr(last_sync, "started_at", None),
            "last_sync_status": getattr(last_sync, "status", None),
        }

    def _processing_status(self) -> dict[str, int]:
        queryset = ScreenshotAnalysis.objects.filter(owner=self.user)
        aggregated = queryset.aggregate(
            queued=Count("id", filter=Q(status=AnalysisStatus.QUEUED)),
            running=Count("id", filter=Q(status=AnalysisStatus.RUNNING)),
            completed=Count("id", filter=Q(status=AnalysisStatus.COMPLETED)),
            partial=Count("id", filter=Q(status=AnalysisStatus.PARTIAL)),
            insufficient=Count("id", filter=Q(status=AnalysisStatus.INSUFFICIENT)),
            failed=Count("id", filter=Q(status=AnalysisStatus.FAILED)),
        )
        return {key: value or 0 for key, value in aggregated.items()}

    def _backtest_status(self) -> dict[str, Any]:
        run = BacktestRun.objects.filter(owner=self.user).order_by("-created_at").first()
        if run is None:
            return {"available": False, "name": None, "status": None, "created_at": None}
        return {
            "available": True,
            "name": run.name,
            "status": run.status,
            "created_at": run.created_at,
            "sample_count": run.sample_count,
        }

    def _probability_status(self) -> dict[str, Any]:
        model = (
            CalibratedModel.objects.filter(owner=self.user, is_approved=True)
            .order_by("-created_at")
            .first()
        )
        if model is None:
            return {
                "available": False,
                "approved": False,
                "name": None,
                "version": None,
            }
        return {
            "available": True,
            "approved": True,
            "name": model.name,
            "version": model.version,
        }

    def _performance(self) -> dict[str, Any]:
        """Only report P/L when settled, real-money outcomes exist."""
        real_trades = JournalTrade.objects.filter(
            owner=self.user,
            trade_type=TradeType.REAL,
            result__in=SETTLED_RESULTS,
        )
        settled = real_trades.count()
        if settled == 0:
            return {
                "has_valid_outcomes": False,
                "message": INSUFFICIENT_DATA,
                "settled_real_trades": 0,
            }
        total = sum((t.profit_loss or 0) for t in real_trades)
        wins = real_trades.filter(result="win").count()
        losses = real_trades.filter(result="loss").count()
        decided = wins + losses
        return {
            "has_valid_outcomes": True,
            "message": None,
            "settled_real_trades": settled,
            "net_profit_loss": str(total),
            "win_rate": round(wins / decided, 4) if decided else None,
            "generated_at": timezone.now(),
        }


__all__ = ["INSUFFICIENT_DATA", "OverviewService"]
