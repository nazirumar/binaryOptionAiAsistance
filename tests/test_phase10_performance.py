# tests/test_phase10_performance.py
"""Phase 10, Step 11 — query-efficiency regression guards.

The benchmark run (``scripts/benchmark_pipeline.py``) found
``GET /api/market/candles/`` issuing **one query per candle** (64 queries for
60 candles) because ``MarketCandleSerializer`` reads ``symbol.canonical`` /
``symbol.broker_symbol`` while the queryset had no ``select_related("symbol")``.
At the maximum allowed range that would be thousands of queries.

These tests pin query counts so the pattern cannot silently return. They assert
*scaling* (constant query count as row volume grows), which is stable across
Django/SQLite versions, rather than a brittle exact number.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from tests.factories import UserFactory
from tests.sync_fakes import make_candle, make_symbol, now_floor, uptrend_prices

pytestmark = pytest.mark.django_db

CANDLES_URL = "/api/market/candles/"


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def auth_client():
    user = UserFactory(username="perf-user")
    client = APIClient()
    client.force_login(user)
    return client


def _seed_candles(count: int, canonical: str = "EURUSD"):
    """Write ``count`` completed candles for one symbol, newest first."""
    symbol = make_symbol(canonical=canonical, broker_symbol=canonical)
    prices = uptrend_prices()
    start = now_floor() - __import__("datetime").timedelta(minutes=count + 1)
    for index in range(count):
        price = prices[index % len(prices)]
        make_candle(symbol, "M1", start + __import__("datetime").timedelta(minutes=index), price)
    return symbol


def _measure_queries(client, params: dict) -> int:
    with CaptureQueriesContext(connection) as context:
        response = client.get(CANDLES_URL, params)
    assert response.status_code == 200, response.content
    return len(context.captured_queries)


def test_candles_endpoint_query_count_does_not_scale_with_rows(auth_client):
    """Query count must stay flat as the candle count grows (N+1 guard)."""
    _seed_candles(10, canonical="EURUSD")
    small = _measure_queries(auth_client, {"symbol": "EURUSD", "timeframe": "M1", "limit": 10})

    _seed_candles(40, canonical="GBPUSD")
    large = _measure_queries(auth_client, {"symbol": "GBPUSD", "timeframe": "M1", "limit": 40})

    # Before the fix: 11 queries for 10 rows, 41 for 40 rows (linear growth).
    # After: both are a small constant (auth + symbol lookup + one JOINed query).
    assert large - small <= 1, f"query count grew with row volume ({small} -> {large}); N+1 is back"
    assert large <= 10, f"unexpectedly high query count for 40 rows: {large}"


def test_candles_endpoint_returns_requested_rows(auth_client):
    """The optimisation must not change behaviour."""
    _seed_candles(15, canonical="EURUSD")

    response = auth_client.get(CANDLES_URL, {"symbol": "EURUSD", "timeframe": "M1", "limit": 15})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 15
    assert len(body["results"]) == 15
    # The optimisation must not change the response shape: `symbol` is the FK
    # id, while `canonical`/`broker_symbol` are flattened top-level fields
    # sourced from the related symbol (the very access that caused the N+1).
    row = body["results"][0]
    assert isinstance(row["symbol"], int)
    assert row["canonical"] == "EURUSD"
    assert row["broker_symbol"] == "EURUSD"


def test_candles_endpoint_still_requires_authentication(client):
    """The optimisation must not weaken access control."""
    response = client.get(CANDLES_URL, {"symbol": "EURUSD", "timeframe": "M1"})
    assert response.status_code in (401, 403)
