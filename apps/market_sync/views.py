"""Market-synchronization API views (Step 14).

Every endpoint is authenticated, ownership-scoped and rate-limited. Verification
runs synchronously over stored data (no MT5 terminal required on the web tier),
so a request either returns a completed session or a clear error — never a
fabricated result.
"""

from __future__ import annotations

from django.db.models import Count
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.api.pagination import StandardResultsSetPagination
from apps.chart_vision.permissions import accessible_analyses, resolve_screenshot
from apps.market_data.constants import Timeframe
from apps.market_data.models import MarketCandle
from apps.market_data.permissions import resolve_profile
from apps.market_sync import serializers
from apps.market_sync.constants import SYNC_CONFIG_VERSION, SyncStatus
from apps.market_sync.exceptions import MissingScreenshotAnalysisError
from apps.market_sync.models import MarketSyncSession
from apps.market_sync.permissions import accessible_sessions
from apps.market_sync.services.mismatch_reporter import status_message
from apps.market_sync.services.synchronization_service import SynchronizationService


class SyncReadMixin:
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sync_read"


def _scoped_idempotency_key(user, key: str) -> str:
    """Scope a client key per user so tenants can never share sessions."""
    if not key:
        return ""
    return f"u{user.pk}:{key}"


class SyncVerifyAPIView(APIView):
    """``POST /api/sync/verify/`` — compare a screenshot analysis against MT5."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sync_verify"

    def post(self, request):
        serializer = serializers.SyncVerifyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        analysis = self._resolve_analysis(request.user, data)
        if analysis is None:
            raise NotFound("No completed screenshot analysis was found for this request.")

        try:
            profile = resolve_profile(request.user, data.get("profile"))
        except LookupError as exc:
            raise ValidationError(str(exc)) from exc

        scoped_key = _scoped_idempotency_key(request.user, data.get("idempotency_key", ""))
        reused = bool(
            scoped_key and MarketSyncSession.objects.filter(idempotency_key=scoped_key).exists()
        )

        service = SynchronizationService()
        try:
            session = service.verify(
                analysis=analysis,
                profile=profile,
                timeframe=data.get("timeframe") or None,
                captured_at=data.get("captured_at"),
                tz_offset_minutes=data.get("tz_offset_minutes"),
                idempotency_key=scoped_key or None,
                owner=request.user,
            )
        except MissingScreenshotAnalysisError as exc:
            raise ValidationError(str(exc)) from exc

        output = serializers.MarketSyncSessionDetailSerializer(session).data
        output["status_message"] = status_message(session.outcome)
        code = status.HTTP_200_OK if reused else status.HTTP_201_CREATED
        return Response(output, status=code)

    @staticmethod
    def _resolve_analysis(user, data):
        if data.get("analysis_id"):
            return accessible_analyses(user).filter(pk=data["analysis_id"]).first()
        screenshot = resolve_screenshot(user, data.get("screenshot_id"))
        if screenshot is None:
            return None
        return (
            accessible_analyses(user).filter(screenshot=screenshot).order_by("-created_at").first()
        )


class SyncResultAPIView(SyncReadMixin, APIView):
    """``GET /api/sync/results/{id}/`` — full result for one session."""

    def get(self, request, pk: int):
        session = accessible_sessions(request.user).filter(pk=pk).first()
        if session is None:
            raise NotFound("Synchronization session not found.")
        output = serializers.MarketSyncSessionDetailSerializer(session).data
        output["status_message"] = status_message(session.outcome)
        return Response(output)


class SyncHistoryAPIView(SyncReadMixin, APIView):
    """``GET /api/sync/history/`` — paginated session history."""

    def get(self, request):
        queryset = (
            accessible_sessions(request.user)
            .select_related("screenshot", "reference_symbol")
            .order_by("-created_at")
        )
        outcome = request.query_params.get("outcome")
        if outcome:
            if outcome not in SyncStatus.values:
                raise ValidationError({"outcome": "Unknown synchronization outcome."})
            queryset = queryset.filter(outcome=outcome)
        timeframe = request.query_params.get("timeframe")
        if timeframe:
            if timeframe not in Timeframe.values:
                raise ValidationError({"timeframe": "Unknown timeframe."})
            queryset = queryset.filter(mt5_timeframe=timeframe)

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = serializers.MarketSyncSessionSummarySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class SyncHealthAPIView(SyncReadMixin, APIView):
    """``GET /api/sync/health/`` — reference-data availability and config."""

    def get(self, request):
        candle_qs = MarketCandle.objects.all()
        latest_candle = candle_qs.order_by("-open_time").first()
        latest_collected = candle_qs.order_by("-collected_at").first()
        symbols = (
            candle_qs.values("symbol__broker_symbol", "timeframe")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )

        sessions = accessible_sessions(request.user)
        by_outcome = {
            row["outcome"] or "unknown": row["count"]
            for row in sessions.values("outcome").annotate(count=Count("id"))
        }

        return Response(
            {
                "config_version": SYNC_CONFIG_VERSION,
                "mt5_reference_available": latest_candle is not None,
                "mt5_candle_count": candle_qs.count(),
                "mt5_latest_candle_open_time": (latest_candle.open_time if latest_candle else None),
                "mt5_last_collected_at": (
                    latest_collected.collected_at if latest_collected else None
                ),
                "mt5_reference_series": list(symbols),
                "server_time": timezone.now(),
                "sessions_by_outcome": by_outcome,
                "recent_session_count": sessions.count(),
            }
        )


__all__ = [
    "SyncHealthAPIView",
    "SyncHistoryAPIView",
    "SyncResultAPIView",
    "SyncVerifyAPIView",
]
