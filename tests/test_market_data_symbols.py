"""Symbol mapping and OTC-compatibility tests."""

from __future__ import annotations

import pytest

from apps.market_data.constants import FeedCompatibility
from apps.market_data.services.exceptions import (
    OTCFeedMismatchError,
    SymbolMappingError,
)
from apps.market_data.services.symbol_mapper import (
    SymbolMapper,
    assert_comparable,
    check_feed_type_compatibility,
    get_instrument,
    list_instruments,
    normalise_code,
)
from tests.marketdata_fakes import make_symbol


def test_normalise_code():
    assert normalise_code(" eur/usd ") == "EURUSD"


def test_get_instrument():
    instrument = get_instrument("eurusd")
    assert instrument.code == "EURUSD"
    assert instrument.category == "forex"
    assert instrument.is_otc is False


def test_otc_instruments_exist_for_forex_and_metals_but_not_crypto():
    codes = {i.code for i in list_instruments()}
    assert "EURUSD_OTC" in codes
    assert "XAUUSD_OTC" in codes
    assert "BTCUSD_OTC" not in codes


def test_unknown_instrument_raises():
    with pytest.raises(SymbolMappingError):
        get_instrument("NOTREAL")


def test_otc_regular_incompatibility():
    assert (
        check_feed_type_compatibility("EURUSD_OTC", broker_is_otc=False)
        == FeedCompatibility.OTC_MISMATCH
    )
    assert (
        check_feed_type_compatibility("EURUSD_OTC", broker_is_otc=True)
        == FeedCompatibility.VERIFIED
    )
    assert (
        check_feed_type_compatibility("EURUSD", broker_is_otc=False) == FeedCompatibility.VERIFIED
    )


def test_assert_comparable_raises_for_otc_mismatch():
    with pytest.raises(OTCFeedMismatchError):
        assert_comparable("EURUSD_OTC", broker_is_otc=False)


@pytest.mark.django_db
def test_resolve_prefers_profile_specific_mapping():
    from apps.market_data.models import MT5ConnectionProfile

    profile = MT5ConnectionProfile.objects.create(name="p1", server="Broker-Demo")
    global_symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    profile_symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSDm", profile=profile)
    assert SymbolMapper.resolve("EURUSD", profile).pk == profile_symbol.pk
    assert SymbolMapper.resolve("EURUSD", None).pk == global_symbol.pk


@pytest.mark.django_db
def test_resolve_returns_global_mapping():
    symbol = make_symbol(canonical="XAUUSD", broker_symbol="XAUUSDm")
    assert SymbolMapper.resolve("XAUUSD", None).pk == symbol.pk


@pytest.mark.django_db
def test_resolve_raises_when_missing():
    with pytest.raises(SymbolMappingError):
        SymbolMapper.resolve("GBPUSD", None)


@pytest.mark.django_db
def test_validate_flags_otc_flag_mismatch():
    symbol = make_symbol(canonical="EURUSD_OTC", broker_symbol="EURUSD", is_otc=False)
    problems = SymbolMapper.validate(symbol)
    assert any("OTC flag mismatch" in p for p in problems)


@pytest.mark.django_db
def test_validate_clean_mapping():
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD", is_otc=False)
    assert SymbolMapper.validate(symbol) == []
