# apps/dashboard/api_views.py
"""Dashboard & analytics API views (Phase 9, Step 16)."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.dashboard.services.analytics_service import StrategyAnalytics
from apps.dashboard.services.market_health_service import MarketHealthService
from apps.dashboard.services.overview_service import OverviewService
from apps.dashboard.services.performance_service import ProbabilityAnalytics
from apps.dashboard.services.reporting_service import ReportingService


class DashboardBaseView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "dashboard"


class OverviewAPIView(DashboardBaseView):
    """GET /api/dashboard/overview/ - real, DB-backed overview metrics."""

    def get(self, request):  # type: ignore[no-untyped-def]
        return Response(OverviewService(request.user).build())


class AnalyticsAPIView(DashboardBaseView):
    """GET /api/dashboard/analytics/ - strategy and probability analytics."""

    def get(self, request):  # type: ignore[no-untyped-def]
        return Response(
            {
                "strategy": StrategyAnalytics(request.user).build(),
                "probability": ProbabilityAnalytics(request.user).build(),
            }
        )


class MarketHealthAPIView(DashboardBaseView):
    """GET /api/dashboard/market-health/ - MT5 and feed health."""

    def get(self, request):  # type: ignore[no-untyped-def]
        from apps.market_data.permissions import accessible_profiles

        profile = accessible_profiles(request.user).order_by("-is_default", "name").first()
        return Response(MarketHealthService(request.user).build(profile))


class ReportsAPIView(DashboardBaseView):
    """GET /api/dashboard/reports/ - a secure, owner-scoped export.

    ``?kind=journal_csv|analyses_csv|performance_pdf`` selects the report.
    """

    def get(self, request):  # type: ignore[no-untyped-def]

        kind = request.query_params.get("kind", "performance_pdf")
        service = ReportingService(request.user)
        date_from = _parse_iso(request.query_params.get("date_from"))
        date_to = _parse_iso(request.query_params.get("date_to"))

        if kind == "journal_csv":
            return service.journal_csv(
                trade_type=request.query_params.get("trade_type"),
                date_from=date_from,
                date_to=date_to,
            )
        if kind == "analyses_csv":
            return service.analyses_csv()
        return service.performance_pdf()


def _parse_iso(value: str | None):  # type: ignore[no-untyped-def]
    if not value:
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


__all__ = [
    "AnalyticsAPIView",
    "MarketHealthAPIView",
    "OverviewAPIView",
    "ReportsAPIView",
]
