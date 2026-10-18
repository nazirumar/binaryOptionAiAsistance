"""Market data API views.

Read endpoints serve **stored** market data (safe for the web tier, which does
not run an MT5 terminal). Live collection is performed by the Windows worker or
by enqueuing a Celery sync task via ``POST /api/market/sync/``.
"""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.market_data import serializers
from apps.market_data.constants import (
    ConnectionState,
    FeedCompatibility,
    HealthKind,
    Severity,
    WorkerStatus,
)
from apps.market_data.models import (
    MarketCandle,
    MarketDataHealthEvent,
    MarketDataSyncLog,
    MarketSymbol,
    MarketTick,
    MT5ConnectionProfile,
    WorkerHeartbeat,
)
from apps.market_data.permissions import IsWorkerToken, accessible_profiles
from apps.market_data.services.candle_service import persist_candles
from apps.market_data.services.dto import Candle, Tick
from apps.market_data.services.exceptions import MarketDataError, SymbolMappingError
from apps.market_data.services.health import upsert_heartbeat
from apps.market_data.services.symbol_mapper import get_instrument
from apps.market_data.services.tick_service import persist_ticks


class MarketReadMixin:
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "market_read"


def _visible_symbols(user):
    profiles = accessible_profiles(user)
    from django.db.models import Q

    return MarketSymbol.objects.filter(Q(profile__isnull=True) | Q(profile__in=profiles))


def _get_symbol(user, token: str) -> MarketSymbol:
    """Resolve a canonical code or broker symbol to a visible MarketSymbol."""
    symbol = (
        _visible_symbols(user).filter(canonical__iexact=token).order_by("profile_id").first()
    ) or (_visible_symbols(user).filter(broker_symbol__iexact=token).order_by("profile_id").first())
    if symbol is None:
        raise NotFound("Symbol not found or not accessible.")
    return symbol


def _derived_connection_state(profile=None) -> str:
    query = MarketDataHealthEvent.objects.filter(
        kind__in=[HealthKind.CONNECTION, HealthKind.DISCONNECT]
    )
    if profile is not None:
        query = query.filter(profile=profile)
    event = query.order_by("-occurred_at").first()
    if event is None:
        return ConnectionState.UNKNOWN
    return (
        ConnectionState.CONNECTED if event.kind == HealthKind.CONNECTION else ConnectionState.ERROR
    )


class MarketHealthAPIView(MarketReadMixin, APIView):
    """Overall market-data health: connection, workers, last sync, recent errors."""

    serializer_class = serializers.MarketHealthSerializer

    def get(self, request) -> Response:
        ttl = int(getattr(settings, "MT5_WORKER_HEARTBEAT_TTL_SECONDS", 90))
        now = timezone.now()
        workers = []
        for heartbeat in WorkerHeartbeat.objects.all()[:20]:
            age = (now - heartbeat.last_seen).total_seconds()
            stale = age > ttl
            workers.append(
                {
                    "worker_id": heartbeat.worker_id,
                    "status": heartbeat.status,
                    "last_seen": heartbeat.last_seen,
                    "age_seconds": round(age, 1),
                    "stale": stale,
                }
            )

        state = _derived_connection_state()
        recent_errors = MarketDataHealthEvent.objects.filter(
            severity__in=[Severity.ERROR, Severity.CRITICAL]
        ).order_by("-occurred_at")[:10]
        last_sync = MarketDataSyncLog.objects.order_by("-started_at").first()

        healthy = state == ConnectionState.CONNECTED
        payload = {
            "status": "ok" if healthy else "degraded",
            "connection_state": state,
            "live_verified": healthy,
            "workers": workers,
            "last_sync": (
                serializers.MarketDataSyncLogSerializer(last_sync).data if last_sync else None
            ),
            "recent_errors": serializers.MarketDataHealthEventSerializer(
                recent_errors, many=True
            ).data,
            "note": (
                "Live MT5 connectivity is only verifiable on a Windows host running the "
                "worker and terminal."
            ),
        }
        return Response(payload)


class MarketSymbolListAPIView(MarketReadMixin, APIView):
    """List accessible (own + shared) symbol mappings."""

    serializer_class = serializers.MarketSymbolSerializer

    def get(self, request) -> Response:
        params = serializers.SymbolQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data

        symbols = _visible_symbols(request.user)
        if data.get("canonical"):
            symbols = symbols.filter(canonical__iexact=data["canonical"])
        if data.get("category"):
            symbols = symbols.filter(category=data["category"])
        if data.get("is_otc") is not None:
            symbols = symbols.filter(is_otc=data["is_otc"])
        if data.get("profile"):
            symbols = symbols.filter(profile_id=data["profile"])

        symbols = symbols.order_by("canonical", "broker_symbol")
        return Response(
            {
                "count": symbols.count(),
                "results": serializers.MarketSymbolSerializer(symbols, many=True).data,
            }
        )


class MarketCandleListAPIView(MarketReadMixin, APIView):
    """Return stored candles for a symbol/timeframe within bounded limits."""

    serializer_class = serializers.MarketCandleSerializer

    def get(self, request) -> Response:
        params = serializers.CandleQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data

        symbol = _get_symbol(request.user, data["symbol"])
        # select_related("symbol"): the serializer reads symbol.canonical /
        # broker_symbol for every row, which otherwise triggers one lazy FK
        # query per candle (measured 64 queries for 60 candles, and would be
        # ~5000 at the maximum allowed range). This collapses it to a join.
        query = MarketCandle.objects.filter(
            symbol=symbol, timeframe=data["timeframe"]
        ).select_related("symbol")
        if not data.get("include_incomplete", False):
            query = query.filter(is_complete=True)
        if data.get("start"):
            query = query.filter(open_time__gte=data["start"])
        if data.get("end"):
            query = query.filter(open_time__lte=data["end"])

        limit = min(data["limit"], int(getattr(settings, "MT5_MAX_CANDLE_RANGE", 5000)))
        candles = list(query.order_by("-open_time")[:limit])
        candles.reverse()
        return Response(
            {
                "symbol": serializers.MarketSymbolSerializer(symbol).data,
                "timeframe": data["timeframe"],
                "count": len(candles),
                "results": serializers.MarketCandleSerializer(candles, many=True).data,
            }
        )


class MarketTickAPIView(MarketReadMixin, APIView):
    """Return the latest stored tick for a symbol and whether it is stale."""

    serializer_class = serializers.MarketTickSerializer

    def get(self, request) -> Response:
        params = serializers.TickQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        symbol = _get_symbol(request.user, params.validated_data["symbol"])

        tick = MarketTick.objects.filter(symbol=symbol).order_by("-time").first()
        ttl = int(getattr(settings, "MT5_STALE_TICK_SECONDS", 120))
        if tick is None:
            return Response(
                {"symbol": symbol.canonical, "tick": None, "stale": True, "age_seconds": None}
            )
        age = (timezone.now() - tick.time).total_seconds()
        return Response(
            {
                "symbol": symbol.canonical,
                "tick": serializers.MarketTickSerializer(tick).data,
                "stale": age > ttl,
                "age_seconds": round(age, 1),
            }
        )


class MarketConnectionAPIView(MarketReadMixin, APIView):
    """List accessible connection profiles with a derived connection state."""

    serializer_class = serializers.MT5ConnectionProfileSerializer

    def get(self, request) -> Response:
        profiles = accessible_profiles(request.user)
        results = []
        for profile in profiles:
            payload = serializers.MT5ConnectionProfileSerializer(profile).data
            payload["derived_state"] = _derived_connection_state(profile)
            results.append(payload)
        return Response(
            {
                "default_state": _derived_connection_state(),
                "count": len(results),
                "results": results,
            }
        )

    def post(self, request) -> Response:
        """Enqueue a connection health check (performed by a worker/terminal host)."""
        from apps.market_data.tasks import check_connection_task

        check_connection_task.delay()
        return Response({"detail": "Connection check enqueued."}, status=status.HTTP_202_ACCEPTED)


class SyncTriggerAPIView(MarketReadMixin, APIView):
    """Enqueue a live candle/tick sync for a symbol (executed off the request cycle)."""

    serializer_class = serializers.SyncRequestSerializer

    def post(self, request) -> Response:
        body = serializers.SyncRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        symbol = _get_symbol(request.user, data["symbol"])

        from apps.market_data.tasks import sync_candles_task, sync_ticks_task

        if data["kind"] == "ticks":
            sync_ticks_task.delay(symbol.pk)
            detail = "Tick sync enqueued."
        else:
            sync_candles_task.delay(symbol.pk, data["timeframe"], data["count"])
            detail = "Candle sync enqueued."
        return Response({"detail": detail}, status=status.HTTP_202_ACCEPTED)


class _IngestBase(APIView):
    permission_classes = [IsWorkerToken]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "market_ingest"

    @staticmethod
    def _resolve_symbol(*, canonical: str, broker_symbol: str, is_otc: bool, profile_id):
        """Validate OTC compatibility and get-or-create the mapping."""
        instrument = get_instrument(canonical)  # raises SymbolMappingError -> handled
        from apps.market_data.services.symbol_mapper import check_feed_type_compatibility

        compatibility = check_feed_type_compatibility(canonical, broker_is_otc=is_otc)
        if compatibility == FeedCompatibility.OTC_MISMATCH:
            raise ValidationError(
                {
                    "detail": (
                        "OTC/regular feed mismatch: the canonical instrument and the "
                        "broker symbol are not equivalent."
                    )
                }
            )
        profile = None
        if profile_id:
            profile = MT5ConnectionProfile.objects.filter(pk=profile_id).first()
        symbol, _ = MarketSymbol.objects.get_or_create(
            profile=profile,
            broker_symbol=broker_symbol,
            defaults={
                "canonical": instrument.code,
                "is_otc": is_otc,
                "category": instrument.category,
            },
        )
        return symbol


class IngestCandlesAPIView(_IngestBase):
    """Worker ingest endpoint for candles (authenticated by worker token)."""

    serializer_class = serializers.IngestCandlesSerializer

    def post(self, request) -> Response:
        body = serializers.IngestCandlesSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        try:
            symbol = self._resolve_symbol(
                canonical=data["canonical"],
                broker_symbol=data["broker_symbol"],
                is_otc=data["is_otc"],
                profile_id=data.get("profile"),
            )
        except SymbolMappingError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        candles = [
            Candle(
                open_time=row["open_time"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                tick_volume=row.get("tick_volume") or 0,
                real_volume=row.get("real_volume"),
                spread=row.get("spread"),
            )
            for row in data["candles"]
        ]
        try:
            result = persist_candles(
                symbol,
                data["timeframe"],
                candles,
                source=data["source"],
                collector=data.get("collector", ""),
            )
        except MarketDataError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(
            {
                "inserted": result.inserted,
                "updated": result.updated,
                "skipped": result.skipped,
                "quality": result.quality_status,
                "validation": result.summary,
            },
            status=status.HTTP_200_OK,
        )


class IngestTicksAPIView(_IngestBase):
    """Worker ingest endpoint for ticks."""

    serializer_class = serializers.IngestTicksSerializer

    def post(self, request) -> Response:
        body = serializers.IngestTicksSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        try:
            symbol = self._resolve_symbol(
                canonical=data["canonical"],
                broker_symbol=data["broker_symbol"],
                is_otc=data["is_otc"],
                profile_id=data.get("profile"),
            )
        except SymbolMappingError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        ticks = [
            Tick(
                time=row["time"],
                bid=row.get("bid"),
                ask=row.get("ask"),
                last=row.get("last"),
                volume=row.get("volume"),
                flags=row.get("flags"),
            )
            for row in data["ticks"]
        ]
        result = persist_ticks(
            symbol, ticks, source=data["source"], collector=data.get("collector", "")
        )
        return Response(
            {"inserted": result.inserted, "skipped": result.skipped},
            status=status.HTTP_200_OK,
        )


class WorkerHeartbeatAPIView(_IngestBase):
    """Worker heartbeat / liveness endpoint."""

    serializer_class = serializers.HeartbeatSerializer

    def post(self, request) -> Response:
        body = serializers.HeartbeatSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        if data["status"] not in set(WorkerStatus.values):
            data["status"] = WorkerStatus.ONLINE
        heartbeat = upsert_heartbeat(
            worker_id=data["worker_id"], status=data["status"], detail=data["detail"]
        )
        return Response(
            {"worker_id": heartbeat.worker_id, "last_seen": heartbeat.last_seen},
            status=status.HTTP_200_OK,
        )


__all__ = [
    "IngestCandlesAPIView",
    "IngestTicksAPIView",
    "MarketCandleListAPIView",
    "MarketConnectionAPIView",
    "MarketHealthAPIView",
    "MarketSymbolListAPIView",
    "MarketTickAPIView",
    "SyncTriggerAPIView",
    "WorkerHeartbeatAPIView",
]
