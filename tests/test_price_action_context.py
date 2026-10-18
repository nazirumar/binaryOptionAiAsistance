"""Tests for the market-context engine (Step 19)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.price_action.constants import MarketRegime, NewsStatus, TradingSession, VolatilityState
from apps.price_action.services.market_context import (
    build_context,
    classify_regime,
    classify_session,
    classify_volatility,
    freshness_status,
    news_status,
    session_overlap,
)
from tests.pa_fakes import CONFIG, candle, flat, uptrend


def test_classify_session_utc_bands():
    assert classify_session(datetime(2026, 1, 5, 3, tzinfo=UTC)) == TradingSession.ASIAN
    assert classify_session(datetime(2026, 1, 5, 9, tzinfo=UTC)) == TradingSession.LONDON
    assert (
        classify_session(datetime(2026, 1, 5, 14, tzinfo=UTC)) == TradingSession.LONDON_NY_OVERLAP
    )
    assert classify_session(datetime(2026, 1, 5, 18, tzinfo=UTC)) == TradingSession.NEW_YORK
    assert classify_session(datetime(2026, 1, 5, 22, tzinfo=UTC)) == TradingSession.OFF_HOURS


def test_classify_session_requires_timezone():
    with pytest.raises(ValueError):
        classify_session(datetime(2026, 1, 5, 9))


def test_session_overlap():
    assert session_overlap(datetime(2026, 1, 5, 14, tzinfo=UTC)) == (
        TradingSession.LONDON_NY_OVERLAP
    )
    assert session_overlap(datetime(2026, 1, 5, 3, tzinfo=UTC)) is None


def test_classify_regime_trending_and_ranging():
    assert classify_regime(uptrend(12), config=CONFIG) in (
        MarketRegime.TRENDING,
        MarketRegime.CHOPPY,
        MarketRegime.UNKNOWN,
    )
    assert classify_regime(flat(8), config=CONFIG) == MarketRegime.RANGING


def test_classify_volatility_high():
    series = flat(6)
    series.append(candle(1.0, 1.05, 0.95, 1.02))
    assert classify_volatility(series, config=CONFIG) == VolatilityState.HIGH


def test_news_status_unknown_without_provider():
    assert news_status(datetime(2026, 1, 5, 9, tzinfo=UTC)) == NewsStatus.UNKNOWN


def test_news_status_with_provider():
    class Provider:
        def is_event_nearby(self, when):
            return True

    assert news_status(datetime(2026, 1, 5, 9, tzinfo=UTC), Provider()) == NewsStatus.EVENT_NEARBY


def test_freshness_status():
    now = datetime(2026, 1, 5, 9, tzinfo=UTC)
    assert freshness_status(now, now=now) == "fresh"
    assert freshness_status(now - timedelta(hours=2), now=now) == "stale"
    assert freshness_status(None, now=now) == "unknown"


def test_build_context_requires_aware_now():
    with pytest.raises(ValueError):
        build_context(uptrend(10), now=datetime(2026, 1, 5, 9))


def test_build_context_shape():
    ctx = build_context(uptrend(10), now=datetime(2026, 1, 5, 9, tzinfo=UTC), config=CONFIG)
    assert {"session", "regime", "volatility", "news_status", "freshness"} <= set(ctx)
    assert ctx["news_status"] == NewsStatus.UNKNOWN
