"""Enumerations and constant registries for the market data domain."""

from __future__ import annotations

from django.db import models


class Timeframe(models.TextChoices):
    """Supported candle timeframes (single source of truth for the project)."""

    M1 = "M1", "1 minute"
    M2 = "M2", "2 minutes"
    M3 = "M3", "3 minutes"
    M5 = "M5", "5 minutes"
    M15 = "M15", "15 minutes"
    M30 = "M30", "30 minutes"
    H1 = "H1", "1 hour"
    H4 = "H4", "4 hours"
    D1 = "D1", "1 day"


class DataSource(models.TextChoices):
    MT5 = "mt5", "MetaTrader 5"
    MANUAL = "manual", "Manual entry"
    IMPORTED = "imported", "Imported"


class QualityStatus(models.TextChoices):
    OK = "ok", "OK"
    SUSPECT = "suspect", "Suspect"
    INVALID = "invalid", "Invalid"
    INCOMPLETE = "incomplete", "Incomplete"


class SymbolCategory(models.TextChoices):
    FOREX = "forex", "Forex"
    METAL = "metal", "Metal"
    INDEX = "index", "Index"
    CRYPTO = "crypto", "Crypto"
    ENERGY = "energy", "Energy"
    OTHER = "other", "Other"


class MappingStatus(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    VALID = "valid", "Valid"
    INVALID = "invalid", "Invalid"
    MISMATCH = "mismatch", "Mismatch"


class ConnectionState(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    CONNECTED = "connected", "Connected"
    DISCONNECTED = "disconnected", "Disconnected"
    ERROR = "error", "Error"


class SyncKind(models.TextChoices):
    SYMBOLS = "symbols", "Symbols"
    CANDLES = "candles", "Candles"
    TICKS = "ticks", "Ticks"
    HEALTH = "health", "Health"


class SyncStatus(models.TextChoices):
    RUNNING = "running", "Running"
    SUCCESS = "success", "Success"
    PARTIAL = "partial", "Partial"
    FAILED = "failed", "Failed"


class HealthKind(models.TextChoices):
    CONNECTION = "connection", "Connection"
    DISCONNECT = "disconnect", "Disconnect"
    STALE_DATA = "stale_data", "Stale data"
    VALIDATION = "validation", "Validation"
    MAPPING = "mapping", "Mapping"
    WORKER = "worker", "Worker"


class Severity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"
    CRITICAL = "critical", "Critical"


class FeedCompatibility(models.TextChoices):
    """Result of comparing a canonical (e.g. IQ Option) instrument to a broker feed."""

    VERIFIED = "verified", "Verified"
    DATA_MISMATCH = "data_mismatch", "Data mismatch"
    UNVERIFIED = "unverified", "Unverified"
    OTC_MISMATCH = "otc_mismatch", "OTC mismatch"


class WorkerStatus(models.TextChoices):
    ONLINE = "online", "Online"
    DEGRADED = "degraded", "Degraded"
    OFFLINE = "offline", "Offline"
    ERROR = "error", "Error"
