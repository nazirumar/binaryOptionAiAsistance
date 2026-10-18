"""PostgreSQL-specific integration checks for market-data constraints.

These tests are skipped on the default SQLite test database. To run them,
point ``DATABASE_URL`` at a throwaway PostgreSQL database and override the test
settings, for example::

    $env:DATABASE_URL = "postgres://user:pass@localhost:5432/nazbeen_test"
    python -m pytest tests/test_market_data_postgres_integration.py -m integration

They assert that the partial unique index enforcing a single default connection
profile per owner behaves correctly on PostgreSQL (where SQLite semantics can
differ for partial/NULL keys).
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, connection, transaction

from apps.market_data.models import MT5ConnectionProfile
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_single_default_profile_per_owner_on_postgres():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL-specific constraint semantics.")

    user = UserFactory(username="pg-owner")
    MT5ConnectionProfile.objects.create(name="primary", owner=user, is_default=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        MT5ConnectionProfile.objects.create(name="secondary", owner=user, is_default=True)


def test_market_candle_unique_on_postgres():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL-specific constraint semantics.")

    from apps.market_data.models import MarketCandle
    from tests.marketdata_fakes import BASE_TIME, make_candle, make_symbol

    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    candle = make_candle(BASE_TIME)
    fields = {
        "symbol": symbol,
        "timeframe": "M1",
        "open_time": candle.open_time,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
    }
    MarketCandle.objects.create(**fields)
    with pytest.raises(IntegrityError), transaction.atomic():
        MarketCandle.objects.create(**fields)
