"""Market data models: connection profiles, symbols, candles, ticks, logs, health."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.market_data.constants import (
    ConnectionState,
    DataSource,
    HealthKind,
    MappingStatus,
    QualityStatus,
    Severity,
    SymbolCategory,
    SyncKind,
    SyncStatus,
    Timeframe,
    WorkerStatus,
)


class MT5ConnectionProfile(TimeStampedModel):
    """Non-secret MT5 connection metadata.

    The account password is **never** stored here. ``credential_ref`` names an
    environment variable / secret entry that holds the password at runtime.
    """

    name = models.CharField(max_length=100)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="mt5_profiles",
        help_text="Null for a shared/system profile.",
    )
    broker = models.CharField(max_length=120, blank=True)
    server = models.CharField(max_length=120, blank=True)
    login = models.BigIntegerField(
        null=True, blank=True, help_text="Account number (masked in APIs)."
    )
    terminal_path = models.CharField(max_length=255, blank=True)
    credential_ref = models.CharField(
        max_length=120,
        blank=True,
        help_text="Name of the environment variable holding the password (never the password itself).",
    )
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    state = models.CharField(
        max_length=16, choices=ConnectionState.choices, default=ConnectionState.UNKNOWN
    )
    last_connected_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_profile_name_per_owner"),
            models.UniqueConstraint(
                fields=["owner"],
                condition=Q(is_default=True),
                name="uniq_default_profile_per_owner",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.server or 'no server'})"

    @property
    def masked_login(self) -> str:
        if not self.login:
            return ""
        text = str(self.login)
        if len(text) <= 3:
            return "*" * len(text)
        return "*" * (len(text) - 2) + text[-2:]


class MarketSymbol(TimeStampedModel):
    """A mapping between a canonical instrument and a broker's symbol name."""

    profile = models.ForeignKey(
        MT5ConnectionProfile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="symbols",
        help_text="Null for a global canonical mapping.",
    )
    canonical = models.CharField(max_length=24, db_index=True)
    broker_symbol = models.CharField(max_length=64)
    description = models.CharField(max_length=200, blank=True)
    category = models.CharField(
        max_length=16, choices=SymbolCategory.choices, default=SymbolCategory.OTHER
    )
    is_otc = models.BooleanField(
        default=False,
        help_text="True for OTC instruments that have no equivalent real-market feed.",
    )
    digits = models.PositiveSmallIntegerField(null=True, blank=True)
    point = models.DecimalField(max_digits=18, decimal_places=10, null=True, blank=True)
    tick_size = models.DecimalField(max_digits=18, decimal_places=10, null=True, blank=True)
    contract_size = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    currency_base = models.CharField(max_length=12, blank=True)
    currency_profit = models.CharField(max_length=12, blank=True)
    is_active = models.BooleanField(default=True)
    mapping_status = models.CharField(
        max_length=16, choices=MappingStatus.choices, default=MappingStatus.UNKNOWN
    )
    last_validated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["canonical", "broker_symbol"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "broker_symbol"], name="uniq_broker_symbol_per_profile"
            ),
        ]
        indexes = [
            models.Index(fields=["canonical", "is_otc"]),
            models.Index(fields=["profile", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.canonical} -> {self.broker_symbol}"


class MarketCandle(TimeStampedModel):
    """A stored OHLC candle. ``open_time`` is always UTC."""

    symbol = models.ForeignKey(MarketSymbol, on_delete=models.CASCADE, related_name="candles")
    timeframe = models.CharField(max_length=4, choices=Timeframe.choices)
    open_time = models.DateTimeField()
    open = models.DecimalField(max_digits=20, decimal_places=8)
    high = models.DecimalField(max_digits=20, decimal_places=8)
    low = models.DecimalField(max_digits=20, decimal_places=8)
    close = models.DecimalField(max_digits=20, decimal_places=8)
    tick_volume = models.BigIntegerField(default=0)
    real_volume = models.BigIntegerField(null=True, blank=True)
    spread = models.IntegerField(null=True, blank=True, help_text="Spread in points, as reported.")
    source = models.CharField(max_length=16, choices=DataSource.choices, default=DataSource.MT5)
    is_complete = models.BooleanField(default=True)
    quality_status = models.CharField(
        max_length=16, choices=QualityStatus.choices, default=QualityStatus.OK
    )
    collected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-open_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["symbol", "timeframe", "open_time"],
                name="uniq_candle_symbol_timeframe_opentime",
            ),
        ]
        indexes = [
            models.Index(fields=["symbol", "timeframe", "-open_time"]),
            models.Index(fields=["open_time"]),
            models.Index(fields=["quality_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.symbol_id}/{self.timeframe}@{self.open_time.isoformat()}"


class MarketTick(TimeStampedModel):
    """A bounded-storage market tick. Retained only for a configured window."""

    symbol = models.ForeignKey(MarketSymbol, on_delete=models.CASCADE, related_name="ticks")
    time = models.DateTimeField()
    bid = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    ask = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    last = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    volume = models.BigIntegerField(null=True, blank=True)
    flags = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=16, choices=DataSource.choices, default=DataSource.MT5)
    collected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-time"]
        constraints = [
            models.UniqueConstraint(
                fields=["symbol", "time", "source"], name="uniq_tick_symbol_time_source"
            ),
        ]
        indexes = [
            models.Index(fields=["symbol", "-time"]),
            models.Index(fields=["time"]),
        ]

    def __str__(self) -> str:
        return f"{self.symbol_id}@{self.time.isoformat()}"

    @property
    def spread(self):
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid


class MarketDataSyncLog(TimeStampedModel):
    """One sync operation (symbols, candles, ticks or health) and its outcome."""

    profile = models.ForeignKey(
        MT5ConnectionProfile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_logs",
    )
    symbol = models.ForeignKey(
        MarketSymbol, null=True, blank=True, on_delete=models.SET_NULL, related_name="sync_logs"
    )
    kind = models.CharField(max_length=16, choices=SyncKind.choices)
    timeframe = models.CharField(max_length=4, blank=True)
    status = models.CharField(max_length=16, choices=SyncStatus.choices, default=SyncStatus.RUNNING)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    rows_fetched = models.PositiveIntegerField(default=0)
    rows_inserted = models.PositiveIntegerField(default=0)
    rows_updated = models.PositiveIntegerField(default=0)
    rows_skipped = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    detail = models.JSONField(default=dict, blank=True)
    collector = models.CharField(max_length=120, blank=True, help_text="Worker identifier.")

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["-started_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["kind", "-started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind}/{self.timeframe or '-'} [{self.status}]"


class MarketDataHealthEvent(TimeStampedModel):
    """A connection/validation/staleness/worker event worth surfacing."""

    profile = models.ForeignKey(
        MT5ConnectionProfile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="health_events",
    )
    symbol = models.ForeignKey(
        MarketSymbol, null=True, blank=True, on_delete=models.SET_NULL, related_name="health_events"
    )
    kind = models.CharField(max_length=16, choices=HealthKind.choices)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.INFO)
    message = models.CharField(max_length=255)
    detail = models.JSONField(default=dict, blank=True)
    collector = models.CharField(max_length=120, blank=True)
    occurred_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["-occurred_at"]),
            models.Index(fields=["severity"]),
            models.Index(fields=["kind", "-occurred_at"]),
        ]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.kind}: {self.message}"


class WorkerHeartbeat(TimeStampedModel):
    """Liveness record for an MT5 worker process."""

    worker_id = models.CharField(max_length=120, unique=True)
    status = models.CharField(
        max_length=16, choices=WorkerStatus.choices, default=WorkerStatus.ONLINE
    )
    last_seen = models.DateTimeField(db_index=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-last_seen"]

    def __str__(self) -> str:
        return f"{self.worker_id} [{self.status}]"
