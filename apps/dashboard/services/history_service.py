# apps/dashboard/services/history_service.py
"""AI analysis history search and filtering (Phase 9, Step 5).

Provides a searchable, filterable view over strategy evaluations and their
associated screenshot analyses. The historical decision is read from the stored
evaluation and is never recomputed, so the original decision is preserved.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import Q, QuerySet

from apps.chart_vision.models import ScreenshotAnalysis
from apps.market_sync.constants import FeedCompatibilityStatus, SyncStatus
from apps.strategy_engine.constants import (
    EvaluationDirection,
    MarketContextState,
    StrategyFamily,
)
from apps.strategy_engine.models import StrategyEvaluation

#: Filters accepted by the history endpoint.
FILTER_FIELDS = (
    "instrument",
    "timeframe",
    "market_type",
    "strategy_family",
    "direction",
    "reason",
    "data_compatibility",
    "probability_status",
    "date_from",
    "date_to",
    "search",
)


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


class AnalysisHistoryService:
    """Query strategy evaluations with search and filters for one user."""

    def __init__(self, user) -> None:  # type: ignore[no-untyped-def]
        self.user = user

    def base_queryset(self) -> QuerySet[StrategyEvaluation]:
        return StrategyEvaluation.objects.filter(owner=self.user).select_related(
            "screenshot_analysis", "sync_session"
        )

    def filter(
        self,
        *,
        instrument: str | None = None,
        timeframe: str | None = None,
        market_type: str | None = None,
        strategy_family: str | None = None,
        direction: str | None = None,
        reason: str | None = None,
        data_compatibility: str | None = None,
        probability_status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        search: str | None = None,
    ) -> QuerySet[StrategyEvaluation]:
        queryset = self.base_queryset()
        if instrument:
            queryset = queryset.filter(instrument__iexact=instrument)
        if timeframe:
            queryset = queryset.filter(timeframe__iexact=timeframe)
        if market_type:
            queryset = queryset.filter(market_type__iexact=market_type)
        if strategy_family:
            queryset = queryset.filter(strategy_family=strategy_family)
        if direction:
            queryset = queryset.filter(direction=direction)
        if reason:
            queryset = queryset.filter(primary_reason_code=reason)
        if data_compatibility:
            queryset = queryset.filter(feed_compatibility=data_compatibility)
        if probability_status:
            queryset = queryset.filter(probability_status=probability_status)
        parsed_from = parse_date(date_from)
        if parsed_from:
            queryset = queryset.filter(created_at__date__gte=parsed_from.date())
        parsed_to = parse_date(date_to)
        if parsed_to:
            queryset = queryset.filter(created_at__date__lte=parsed_to.date())
        if search:
            queryset = queryset.filter(
                Q(instrument__icontains=search)
                | Q(evaluation_id__icontains=search)
                | Q(explanation__icontains=search)
            )
        return queryset

    def filter_analyses(
        self,
        *,
        instrument: str | None = None,
        timeframe: str | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> QuerySet[ScreenshotAnalysis]:
        queryset = ScreenshotAnalysis.objects.filter(owner=self.user).select_related("screenshot")
        if status:
            queryset = queryset.filter(status=status)
        if instrument:
            queryset = queryset.filter(chart_metadata__instrument__iexact=instrument)
        if timeframe:
            queryset = queryset.filter(chart_metadata__timeframe__iexact=timeframe)
        if search:
            queryset = queryset.filter(
                Q(chart_metadata__instrument__icontains=search) | Q(error_message__icontains=search)
            )
        return queryset

    def filter_choices(self) -> dict[str, Any]:
        """Distinct values present in the user's data, for filter dropdowns."""
        queryset = self.base_queryset()
        instrument_values = (
            queryset.exclude(instrument="")
            .values_list("instrument", flat=True)
            .distinct()
            .order_by("instrument")
        )
        timeframe_values = (
            queryset.exclude(timeframe="")
            .values_list("timeframe", flat=True)
            .distinct()
            .order_by("timeframe")
        )
        return {
            "instruments": list(instrument_values),
            "timeframes": list(timeframe_values),
            "strategies": StrategyFamily.choices,
            "directions": EvaluationDirection.choices,
            "regimes": MarketContextState.choices,
            "compatibility": FeedCompatibilityStatus.choices,
            "sync_status": SyncStatus.choices,
        }


__all__ = ["FILTER_FIELDS", "AnalysisHistoryService", "parse_date"]
