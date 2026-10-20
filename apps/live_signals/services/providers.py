# live_signals/services/providers.py
"""Candle-provider abstraction for the live monitor.

The monitor never talks to a data source directly: it asks a
:class:`CandleProvider` for *closed* candles. This keeps the detection engine
testable and lets other authorized feeds be added later without touching
strategy logic.

Two providers ship today:

* :class:`DatabaseCandleProvider` (default) — reads candles the existing MT5
  sync / HTTP ingest already persisted to ``MarketCandle``. It makes **no**
  assumption that a live MT5 terminal is present; it simply reports what is
  stored, and the monitor treats missing data as ``UNAVAILABLE``.
* :class:`MT5GatewayCandleProvider` — optional; fetches directly through the
  existing ``MetaTrader5Client``/``CandleService`` at monitor time. Only usable
  on a host with a connected terminal; otherwise it degrades to unavailable.

Neither provider invents candles, interpolates gaps, or relabels a forming bar
as complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from apps.market_data.services.candle_service import is_candle_complete
from apps.market_data.services.timeframe_mapper import duration, is_supported


@dataclass(slots=True, frozen=True)
class ProviderCandle:
    """A closed candle plus its provenance, decoupled from any driver."""

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    is_complete: bool = True
    source: str = "db"

    def as_detector_dict(self) -> dict[str, Any]:
        """Shape consumed by the deterministic detectors."""
        return {
            "open_time": self.open_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "complete": self.is_complete,
        }


@dataclass(slots=True, frozen=True)
class ProviderResult:
    """Outcome of one provider fetch."""

    candles: list[ProviderCandle]
    available: bool
    state: str  # FeedState value
    message: str = ""


@runtime_checkable
class CandleProvider(Protocol):
    """Interface every candle source must satisfy."""

    name: str

    def fetch_closed(
        self,
        *,
        broker_symbol: str,
        canonical_instrument: str,
        timeframe: str,
        count: int,
        now: datetime | None = None,
    ) -> ProviderResult:
        """Return the most recent ``count`` *closed* candles (oldest first)."""
        ...


def _finalise(candles: list[ProviderCandle], timeframe: str, count: int, now: datetime) -> list[ProviderCandle]:
    """Sort, drop forming bars, dedupe by open time, and keep the newest ``count``.

    Completeness is *re-derived* here from the candle metadata + timeframe, so a
    provider that wrongly reports ``is_complete=True`` on a forming bar cannot
    slip a forming candle past the monitor.
    """
    by_open: dict[datetime, ProviderCandle] = {}
    for candle in candles:
        by_open[candle.open_time] = candle
    ordered = [by_open[k] for k in sorted(by_open)]
    closed: list[ProviderCandle] = []
    for candle in ordered:
        if not candle.is_complete:
            continue
        if not is_candle_complete(candle.open_time, timeframe, now=now):
            continue
        closed.append(candle)
    return closed[-count:] if count > 0 else closed


class DatabaseCandleProvider:
    """Reads already-persisted ``MarketCandle`` rows for a mapped symbol."""

    name = "db"

    def fetch_closed(
        self,
        *,
        broker_symbol: str,
        canonical_instrument: str,
        timeframe: str,
        count: int,
        now: datetime | None = None,
    ) -> ProviderResult:
        from apps.live_signals.constants import FeedState
        from apps.market_data.models import MarketCandle, MarketSymbol

        if not is_supported(timeframe):
            return ProviderResult(
                candles=[],
                available=False,
                state=FeedState.UNAVAILABLE,
                message=f"Unsupported timeframe {timeframe!r}",
            )

        symbol = (
            MarketSymbol.objects.filter(broker_symbol=broker_symbol, is_active=True).first()
            if broker_symbol
            else None
        )
        if symbol is None:
            symbol = (
                MarketSymbol.objects.filter(canonical=canonical_instrument, is_active=True)
                .order_by("pk")
                .first()
            )
        if symbol is None:
            return ProviderResult(
                candles=[],
                available=False,
                state=FeedState.UNAVAILABLE,
                message=f"No stored symbol for {canonical_instrument!r}/{broker_symbol!r}",
            )

        rows = list(
            MarketCandle.objects.filter(
                symbol=symbol, timeframe=timeframe, is_complete=True
            ).order_by("-open_time")[: max(count, 1) * 2]
        )
        if not rows:
            return ProviderResult(
                candles=[],
                available=False,
                state=FeedState.UNAVAILABLE,
                message="No stored closed candles yet",
            )

        now = now or datetime.now(tz=UTC)
        candles = [
            ProviderCandle(
                open_time=row.open_time,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                is_complete=row.is_complete,
                source=row.source,
            )
            for row in rows
        ]
        final = _finalise(candles, timeframe, count, now)
        if not final:
            return ProviderResult(
                candles=[],
                available=False,
                state=FeedState.UNAVAILABLE,
                message="Stored candles are not closed yet",
            )
        return ProviderResult(candles=final, available=True, state=FeedState.OK, message="ok")


class MT5GatewayCandleProvider:
    """Optional provider that fetches through the existing MT5 gateway.

    Only usable on a Windows host with a connected terminal and the
    ``MetaTrader5`` package. Any failure is reported as unavailable — never
    faked.
    """

    name = "mt5"

    def __init__(self, client=None) -> None:  # client injectable for tests
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        from apps.market_data.services.mt5_client import MetaTrader5Client

        return MetaTrader5Client()

    def fetch_closed(
        self,
        *,
        broker_symbol: str,
        canonical_instrument: str,
        timeframe: str,
        count: int,
        now: datetime | None = None,
    ) -> ProviderResult:
        from apps.live_signals.constants import FeedState

        if not is_supported(timeframe):
            return ProviderResult(
                candles=[],
                available=False,
                state=FeedState.UNAVAILABLE,
                message=f"Unsupported timeframe {timeframe!r}",
            )
        now = now or datetime.now(tz=UTC)
        try:
            client = self._get_client()
            raw = client.copy_rates_from_pos(
                broker_symbol, timeframe, count=max(count, 1) * 2, start=0
            )
        except Exception as exc:  # pragma: no cover - depends on live terminal
            return ProviderResult(
                candles=[],
                available=False,
                state=FeedState.UNAVAILABLE,
                message=f"MT5 fetch failed: {exc}",
            )

        candles = [
            ProviderCandle(
                open_time=c.open_time,
                open=float(c.open),
                high=float(c.high),
                low=float(c.low),
                close=float(c.close),
                is_complete=True,
                source="mt5",
            )
            for c in raw
        ]
        final = _finalise(candles, timeframe, count, now)
        if not final:
            return ProviderResult(
                candles=[],
                available=False,
                state=FeedState.UNAVAILABLE,
                message="No closed MT5 candles returned",
            )
        return ProviderResult(candles=final, available=True, state=FeedState.OK, message="ok")


#: Provider registry — extend here to add authorized feeds later.
PROVIDERS: dict[str, type] = {
    "db": DatabaseCandleProvider,
    "mt5": MT5GatewayCandleProvider,
}


def get_provider(name: str = "db") -> CandleProvider:
    """Return a provider instance by name (defaults to the DB provider)."""
    cls = PROVIDERS.get(name, DatabaseCandleProvider)
    return cls()


def timeframe_candle_seconds(timeframe: str) -> int:
    """Closed-candle duration in seconds (raises for unsupported timeframes)."""
    return int(duration(timeframe).total_seconds())


__all__ = [
    "PROVIDERS",
    "CandleProvider",
    "DatabaseCandleProvider",
    "MT5GatewayCandleProvider",
    "ProviderCandle",
    "ProviderResult",
    "get_provider",
    "timeframe_candle_seconds",
]
