"""Serializers for the market data API and worker ingest endpoints."""

from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

from apps.market_data.constants import DataSource, SymbolCategory, Timeframe
from apps.market_data.models import (
    MarketCandle,
    MarketDataHealthEvent,
    MarketDataSyncLog,
    MarketSymbol,
    MarketTick,
    MT5ConnectionProfile,
    WorkerHeartbeat,
)
from apps.market_data.services.timeframe_mapper import is_supported


class MT5ConnectionProfileSerializer(serializers.ModelSerializer):
    """Read-only, secret-free connection profile representation."""

    masked_login = serializers.CharField(read_only=True)

    class Meta:
        model = MT5ConnectionProfile
        fields = (
            "id",
            "name",
            "broker",
            "server",
            "masked_login",
            "terminal_path",
            "is_active",
            "is_default",
            "state",
            "last_connected_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class MarketSymbolSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketSymbol
        fields = (
            "id",
            "profile",
            "canonical",
            "broker_symbol",
            "description",
            "category",
            "is_otc",
            "digits",
            "point",
            "tick_size",
            "contract_size",
            "currency_base",
            "currency_profit",
            "is_active",
            "mapping_status",
            "last_validated_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class MarketCandleSerializer(serializers.ModelSerializer):
    canonical = serializers.CharField(source="symbol.canonical", read_only=True)
    broker_symbol = serializers.CharField(source="symbol.broker_symbol", read_only=True)

    class Meta:
        model = MarketCandle
        fields = (
            "id",
            "symbol",
            "canonical",
            "broker_symbol",
            "timeframe",
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "tick_volume",
            "real_volume",
            "spread",
            "source",
            "is_complete",
            "quality_status",
            "collected_at",
        )
        read_only_fields = fields


class MarketTickSerializer(serializers.ModelSerializer):
    canonical = serializers.CharField(source="symbol.canonical", read_only=True)
    broker_symbol = serializers.CharField(source="symbol.broker_symbol", read_only=True)
    spread = serializers.DecimalField(max_digits=20, decimal_places=8, read_only=True)

    class Meta:
        model = MarketTick
        fields = (
            "id",
            "symbol",
            "canonical",
            "broker_symbol",
            "time",
            "bid",
            "ask",
            "last",
            "spread",
            "volume",
            "flags",
            "source",
            "collected_at",
        )
        read_only_fields = fields


class MarketDataSyncLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketDataSyncLog
        fields = (
            "id",
            "profile",
            "symbol",
            "kind",
            "timeframe",
            "status",
            "started_at",
            "finished_at",
            "rows_fetched",
            "rows_inserted",
            "rows_updated",
            "rows_skipped",
            "error_message",
            "detail",
            "collector",
        )
        read_only_fields = fields


class MarketDataHealthEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketDataHealthEvent
        fields = (
            "id",
            "profile",
            "symbol",
            "kind",
            "severity",
            "message",
            "detail",
            "collector",
            "occurred_at",
            "resolved_at",
        )
        read_only_fields = fields


class WorkerHeartbeatSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkerHeartbeat
        fields = ("id", "worker_id", "status", "last_seen", "detail")
        read_only_fields = fields


class MarketHealthSerializer(serializers.Serializer):
    """Response shape of ``GET /api/market/health/``."""

    status = serializers.CharField()
    connection_state = serializers.CharField()
    live_verified = serializers.BooleanField()
    note = serializers.CharField()
    workers = serializers.ListField(child=serializers.DictField(), required=False)
    last_sync = serializers.DictField(required=False, allow_null=True)
    recent_errors = serializers.ListField(child=serializers.DictField(), required=False)


# ---------------------------------------------------------------------------
# Query / request validation
# ---------------------------------------------------------------------------
def _max_candle_range() -> int:
    return int(getattr(settings, "MT5_MAX_CANDLE_RANGE", 5000))


class CandleQuerySerializer(serializers.Serializer):
    """Validates ``GET /api/market/candles/`` query parameters."""

    symbol = serializers.CharField()
    timeframe = serializers.ChoiceField(choices=Timeframe.choices)
    limit = serializers.IntegerField(min_value=1, max_value=1000, required=False, default=200)
    start = serializers.DateTimeField(required=False)
    end = serializers.DateTimeField(required=False)
    include_incomplete = serializers.BooleanField(required=False, default=False)

    def validate_timeframe(self, value: str) -> str:
        if not is_supported(value):
            raise serializers.ValidationError("Unsupported timeframe.")
        return value

    def validate(self, attrs: dict) -> dict:
        start = attrs.get("start")
        end = attrs.get("end")
        if start and end and start > end:
            raise serializers.ValidationError({"detail": "`start` must be before `end`."})
        if start and end:
            span = (end - start).total_seconds()
            # Bound the requested window by the configured maximum number of candles.
            step_seconds = _timeframe_seconds(attrs["timeframe"])
            if step_seconds and span / step_seconds > _max_candle_range():
                raise serializers.ValidationError(
                    {"detail": "Requested range exceeds the maximum allowed candles."}
                )
        return attrs


class TickQuerySerializer(serializers.Serializer):
    symbol = serializers.CharField()


class SymbolQuerySerializer(serializers.Serializer):
    canonical = serializers.CharField(required=False)
    category = serializers.ChoiceField(choices=SymbolCategory.choices, required=False)
    is_otc = serializers.BooleanField(required=False)
    profile = serializers.IntegerField(required=False)


class SyncRequestSerializer(serializers.Serializer):
    symbol = serializers.CharField()
    kind = serializers.ChoiceField(choices=["candles", "ticks"], default="candles")
    timeframe = serializers.ChoiceField(choices=Timeframe.choices, required=False, default="M1")
    count = serializers.IntegerField(min_value=1, max_value=5000, required=False, default=300)
    profile = serializers.IntegerField(required=False)

    def validate_timeframe(self, value: str) -> str:
        if not is_supported(value):
            raise serializers.ValidationError("Unsupported timeframe.")
        return value


# ---------------------------------------------------------------------------
# Worker ingest
# ---------------------------------------------------------------------------
class IngestCandleRowSerializer(serializers.Serializer):
    open_time = serializers.DateTimeField()
    open = serializers.DecimalField(max_digits=20, decimal_places=8)
    high = serializers.DecimalField(max_digits=20, decimal_places=8)
    low = serializers.DecimalField(max_digits=20, decimal_places=8)
    close = serializers.DecimalField(max_digits=20, decimal_places=8)
    tick_volume = serializers.IntegerField(required=False, default=0)
    real_volume = serializers.IntegerField(required=False, allow_null=True, default=None)
    spread = serializers.IntegerField(required=False, allow_null=True, default=None)


class IngestCandlesSerializer(serializers.Serializer):
    canonical = serializers.CharField()
    broker_symbol = serializers.CharField()
    is_otc = serializers.BooleanField(required=False, default=False)
    timeframe = serializers.ChoiceField(choices=Timeframe.choices)
    source = serializers.ChoiceField(
        choices=DataSource.choices, required=False, default=DataSource.MT5
    )
    profile = serializers.IntegerField(required=False, allow_null=True, default=None)
    collector = serializers.CharField(required=False, allow_blank=True, default="")
    candles = IngestCandleRowSerializer(many=True, allow_empty=False)

    def validate_timeframe(self, value: str) -> str:
        if not is_supported(value):
            raise serializers.ValidationError("Unsupported timeframe.")
        return value


class IngestTickRowSerializer(serializers.Serializer):
    time = serializers.DateTimeField()
    bid = serializers.DecimalField(max_digits=20, decimal_places=8, required=False, allow_null=True)
    ask = serializers.DecimalField(max_digits=20, decimal_places=8, required=False, allow_null=True)
    last = serializers.DecimalField(
        max_digits=20, decimal_places=8, required=False, allow_null=True
    )
    volume = serializers.IntegerField(required=False, allow_null=True, default=None)
    flags = serializers.IntegerField(required=False, allow_null=True, default=None)


class IngestTicksSerializer(serializers.Serializer):
    canonical = serializers.CharField()
    broker_symbol = serializers.CharField()
    is_otc = serializers.BooleanField(required=False, default=False)
    source = serializers.ChoiceField(
        choices=DataSource.choices, required=False, default=DataSource.MT5
    )
    profile = serializers.IntegerField(required=False, allow_null=True, default=None)
    collector = serializers.CharField(required=False, allow_blank=True, default="")
    ticks = IngestTickRowSerializer(many=True, allow_empty=False)


class HeartbeatSerializer(serializers.Serializer):
    worker_id = serializers.CharField(max_length=120)
    status = serializers.CharField(required=False, default="online")
    detail = serializers.DictField(required=False, default=dict)


def _timeframe_seconds(timeframe: str) -> int:
    from apps.market_data.services.timeframe_mapper import TIMEFRAME_SECONDS

    return TIMEFRAME_SECONDS.get(timeframe, 0)
