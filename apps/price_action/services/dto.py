"""Immutable data-transfer objects consumed by the price-action detectors.

Detectors never touch the database. They receive plain, immutable dataclasses so
they stay deterministic and trivial to unit-test with hand-built fixtures. This
mirrors the convention established by ``apps.market_sync.services.dto``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from apps.price_action.constants import (
    DataQuality,
    MarketType,
    VolumeSource,
)


@dataclass(frozen=True, slots=True)
class Candle:
    """A single OHLC candle with a stable reference.

    ``index`` is the stable reference used everywhere in evidence. ``open_time``
    is optional (synthetic fixtures may omit it). ``complete`` records whether
    the candle has closed; an incomplete final candle must never be used as if
    it were a completed observation.
    """

    index: int
    open: float
    high: float
    low: float
    close: float
    open_time: datetime | None = None
    complete: bool = True
    tick_volume: float | None = None
    real_volume: float | None = None

    @property
    def body_range_ratio(self) -> float | None:
        rng = self.high - self.low
        if rng <= 0.0:
            return None
        return abs(self.close - self.open) / rng

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def volume_source(self) -> str:
        if self.real_volume is not None:
            return VolumeSource.REAL
        if self.tick_volume is not None:
            return VolumeSource.TICK
        return VolumeSource.NONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "open_time": self.open_time.isoformat() if self.open_time else None,
            "complete": self.complete,
            "tick_volume": self.tick_volume,
            "real_volume": self.real_volume,
        }


@dataclass(frozen=True, slots=True)
class MarketInput:
    """Versioned, standardized market input handed to the engine (Step 3).

    The input deliberately carries the *provenance* of the data (screenshot
    observations, sync status, feed compatibility, warnings) so that detectors
    can degrade gracefully and so downstream phases know what to trust.
    """

    canonical_instrument: str = ""
    broker_symbol: str = ""
    timeframe: str = ""
    market_type: str = MarketType.UNKNOWN
    candles: tuple[Candle, ...] = ()
    screenshot_observations: dict[str, Any] = field(default_factory=dict)
    sync_status: str = ""
    feed_compatibility: str = ""
    data_quality: str = DataQuality.UNKNOWN
    warnings: tuple[str, ...] = ()
    schema_version: str = ""

    @property
    def candle_count(self) -> int:
        return len(self.candles)

    def completed(self) -> list[Candle]:
        """Return only the candles that have actually closed."""
        return [c for c in self.candles if c.complete]

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_instrument": self.canonical_instrument,
            "broker_symbol": self.broker_symbol,
            "timeframe": self.timeframe,
            "market_type": self.market_type,
            "candles": [c.to_dict() for c in self.candles],
            "screenshot_observations": self.screenshot_observations,
            "sync_status": self.sync_status,
            "feed_compatibility": self.feed_compatibility,
            "data_quality": self.data_quality,
            "warnings": list(self.warnings),
            "schema_version": self.schema_version,
        }


def candle_from_dict(raw: dict[str, Any], index: int) -> Candle:
    """Build a :class:`Candle` from a loose mapping.

    Missing OHLC values default to ``0.0`` and the caller reports the resulting
    data-quality warning; the engine never invents prices.
    """
    open_time = raw.get("open_time") or raw.get("time")
    if isinstance(open_time, str):
        try:
            open_time = datetime.fromisoformat(open_time)
        except ValueError:
            open_time = None
    complete = raw.get("complete", True)
    tick = raw.get("tick_volume")
    real = raw.get("real_volume")
    # A generic "volume" key is treated as tick volume; it is never assumed to
    # be real exchange volume.
    if tick is None and real is None and raw.get("volume") is not None:
        tick = raw.get("volume")
    return Candle(
        index=index,
        open=float(raw.get("open", 0.0)),
        high=float(raw.get("high", 0.0)),
        low=float(raw.get("low", 0.0)),
        close=float(raw.get("close", 0.0)),
        open_time=open_time,
        complete=bool(complete),
        tick_volume=float(tick) if tick is not None else None,
        real_volume=float(real) if real is not None else None,
    )


def candles_from_dicts(rows: list[dict[str, Any]]) -> list[Candle]:
    return [candle_from_dict(row, i) for i, row in enumerate(rows)]


def as_plain(candle: Candle) -> dict[str, float]:
    """A minimal OHLC mapping for the pure math helpers that predate ``Candle``."""
    return {
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
    }


__all__ = [
    "Candle",
    "MarketInput",
    "as_plain",
    "candle_from_dict",
    "candles_from_dicts",
]
