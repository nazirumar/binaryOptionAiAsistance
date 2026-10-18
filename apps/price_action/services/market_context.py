"""Market-context engine (Step 19).

Pure classification helpers for trading session, market regime, volatility,
session overlap, consolidation and data freshness. The news interface is an
*optional* injected source: when no reliable calendar is connected it returns
:attr:`NewsStatus.UNKNOWN` and never fabricates an event. All datetimes are
required to be timezone-aware.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from apps.price_action.constants import (
    MarketRegime,
    NewsStatus,
    TradingSession,
    VolatilityState,
)
from apps.price_action.services.candle_math import average_range, candle_range
from apps.price_action.services.config import PriceActionConfig
from apps.price_action.services.market_structure import detect_consolidation, infer_trend


class NewsProvider(Protocol):
    """Optional economic-calendar proximity interface."""

    def is_event_nearby(self, when: datetime) -> bool | None:  # pragma: no cover - protocol
        ...


def classify_session(when: datetime) -> str:
    """Classify the UTC hour into a coarse trading session."""
    if when.tzinfo is None:
        raise ValueError("classify_session requires a timezone-aware datetime")
    hour = when.astimezone(UTC).hour
    # Coarse, deliberately conservative boundaries (UTC).
    if 13 <= hour < 16:
        return TradingSession.LONDON_NY_OVERLAP
    if 7 <= hour < 13:
        return TradingSession.LONDON
    if 16 <= hour < 21:
        return TradingSession.NEW_YORK
    if 0 <= hour < 7:
        return TradingSession.ASIAN
    return TradingSession.OFF_HOURS


def session_overlap(when: datetime) -> str | None:
    """Name the overlap if the moment falls inside a known one."""
    session = classify_session(when)
    if session in (TradingSession.LONDON_NY_OVERLAP, TradingSession.ASIAN_LONDON_OVERLAP):
        return str(session)
    return None


def classify_regime(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> str:
    config = config or PriceActionConfig.from_settings()
    if detect_consolidation(candles, config=config) is not None:
        return MarketRegime.RANGING
    trend = infer_trend(candles, config.swing_lookback, config=config)
    if trend in ("uptrend", "downtrend"):
        return MarketRegime.TRENDING
    ranges = [candle_range(c) for c in candles[-config.volume_lookback :]]
    usable = [r for r in ranges if r > 0]
    if len(usable) >= 3:
        mean = sum(usable) / len(usable)
        variance = sum((r - mean) ** 2 for r in usable) / len(usable)
        if mean > 0 and (variance**0.5) / mean > 0.75:
            return MarketRegime.CHOPPY
    return MarketRegime.UNKNOWN


def classify_volatility(
    candles: list[dict[str, Any]], *, config: PriceActionConfig | None = None
) -> str:
    config = config or PriceActionConfig.from_settings()
    if not candles:
        return VolatilityState.UNKNOWN
    avg = average_range(candles[:-1], config.volume_lookback)
    last = candle_range(candles[-1])
    if avg is None or avg <= 0:
        return VolatilityState.UNKNOWN
    rel = last / avg
    if rel >= config.high_volatility_multiple:
        return VolatilityState.HIGH
    if rel <= config.low_volatility_multiple:
        return VolatilityState.LOW
    return VolatilityState.NORMAL


def news_status(when: datetime, provider: NewsProvider | None = None) -> str:
    """Return the news proximity status; UNKNOWN when no source is connected."""
    if provider is None:
        return NewsStatus.UNKNOWN
    try:
        result = provider.is_event_nearby(when)
    except Exception:  # pragma: no cover - defensive against third-party sources
        return NewsStatus.UNKNOWN
    if result is None:
        return NewsStatus.UNKNOWN
    return NewsStatus.EVENT_NEARBY if result else NewsStatus.NO_EVENT_NEARBY


def freshness_status(
    last_candle_time: datetime | None, *, now: datetime | None = None, max_age_seconds: int = 900
) -> str:
    if last_candle_time is None:
        return "unknown"
    now = now or datetime.now(UTC)
    age = (now - last_candle_time).total_seconds()
    return "fresh" if age <= max_age_seconds else "stale"


def build_context(
    candles: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    news_provider: NewsProvider | None = None,
    config: PriceActionConfig | None = None,
) -> dict[str, Any]:
    config = config or PriceActionConfig.from_settings()
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("build_context requires a timezone-aware 'now'")
    last_time = None
    if candles:
        raw = candles[-1].get("open_time")
        if isinstance(raw, str):
            try:
                last_time = datetime.fromisoformat(raw)
            except ValueError:
                last_time = None
    return {
        "session": str(classify_session(now)),
        "session_overlap": session_overlap(now),
        "regime": str(classify_regime(candles, config=config)),
        "volatility": str(classify_volatility(candles, config=config)),
        "consolidation": detect_consolidation(candles, config=config),
        "news_status": str(news_status(now, news_provider)),
        "freshness": freshness_status(last_time, now=now),
    }


__all__ = [
    "NewsProvider",
    "build_context",
    "classify_regime",
    "classify_session",
    "classify_volatility",
    "freshness_status",
    "news_status",
    "session_overlap",
]
