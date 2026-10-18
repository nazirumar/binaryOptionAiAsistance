"""Canonical instrument registry and symbol-mapping logic.

Different brokers name instruments differently (``EURUSD``, ``EURUSDm``,
``EURUSD.pro``), and IQ Option offers *OTC* instruments that have **no**
equivalent real-market feed. This module models canonical instruments, their
OTC nature, and the compatibility checks that prevent a regular MT5 feed from
being passed off as an OTC feed (or vice versa).
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.market_data.constants import FeedCompatibility, SymbolCategory
from apps.market_data.services.exceptions import (
    OTCFeedMismatchError,
    SymbolMappingError,
)


@dataclass(frozen=True, slots=True)
class CanonicalInstrument:
    """A provider-independent instrument identity."""

    code: str
    name: str
    category: str
    is_otc: bool = False

    @property
    def base(self) -> str:
        return self.code.removesuffix("_OTC")


_REGULAR_INSTRUMENTS: tuple[tuple[str, str, str], ...] = (
    ("EURUSD", "Euro / US Dollar", SymbolCategory.FOREX),
    ("GBPUSD", "British Pound / US Dollar", SymbolCategory.FOREX),
    ("USDJPY", "US Dollar / Japanese Yen", SymbolCategory.FOREX),
    ("AUDUSD", "Australian Dollar / US Dollar", SymbolCategory.FOREX),
    ("USDCAD", "US Dollar / Canadian Dollar", SymbolCategory.FOREX),
    ("USDCHF", "US Dollar / Swiss Franc", SymbolCategory.FOREX),
    ("NZDUSD", "New Zealand Dollar / US Dollar", SymbolCategory.FOREX),
    ("EURGBP", "Euro / British Pound", SymbolCategory.FOREX),
    ("EURJPY", "Euro / Japanese Yen", SymbolCategory.FOREX),
    ("GBPJPY", "British Pound / Japanese Yen", SymbolCategory.FOREX),
    ("XAUUSD", "Gold / US Dollar", SymbolCategory.METAL),
    ("XAGUSD", "Silver / US Dollar", SymbolCategory.METAL),
    ("BTCUSD", "Bitcoin / US Dollar", SymbolCategory.CRYPTO),
    ("ETHUSD", "Ethereum / US Dollar", SymbolCategory.CRYPTO),
)

#: Categories for which IQ Option also lists an OTC variant.
_OTC_CATEGORIES = {SymbolCategory.FOREX, SymbolCategory.METAL}


def _build_registry() -> dict[str, CanonicalInstrument]:
    registry: dict[str, CanonicalInstrument] = {}
    for code, name, category in _REGULAR_INSTRUMENTS:
        registry[code] = CanonicalInstrument(code=code, name=name, category=category)
        if category in _OTC_CATEGORIES:
            otc_code = f"{code}_OTC"
            registry[otc_code] = CanonicalInstrument(
                code=otc_code,
                name=f"{name} (OTC)",
                category=category,
                is_otc=True,
            )
    return registry


INSTRUMENT_REGISTRY: dict[str, CanonicalInstrument] = _build_registry()


def normalise_code(code: str) -> str:
    """Normalise user/broker input into a canonical code shape."""
    return code.strip().upper().replace(" ", "").replace("/", "")


def get_instrument(code: str) -> CanonicalInstrument:
    """Return the canonical instrument or raise :class:`SymbolMappingError`."""
    normalised = normalise_code(code)
    try:
        return INSTRUMENT_REGISTRY[normalised]
    except KeyError as exc:
        raise SymbolMappingError(f"Unknown canonical instrument: {code!r}") from exc


def list_instruments(*, include_otc: bool = True) -> list[CanonicalInstrument]:
    instruments = list(INSTRUMENT_REGISTRY.values())
    if not include_otc:
        instruments = [i for i in instruments if not i.is_otc]
    return sorted(instruments, key=lambda i: (i.category, i.code))


def check_feed_type_compatibility(
    canonical_code: str,
    *,
    broker_is_otc: bool,
) -> str:
    """Compare the OTC nature of a canonical instrument with a broker feed.

    Returns a :class:`FeedCompatibility` value. An OTC canonical instrument may
    **never** be satisfied by a regular broker feed (and vice versa).
    """
    instrument = get_instrument(canonical_code)
    if instrument.is_otc != broker_is_otc:
        return FeedCompatibility.OTC_MISMATCH
    return FeedCompatibility.VERIFIED


def assert_comparable(canonical_code: str, *, broker_is_otc: bool) -> str:
    """Like :func:`check_feed_type_compatibility` but raises on OTC mismatch."""
    compatibility = check_feed_type_compatibility(canonical_code, broker_is_otc=broker_is_otc)
    if compatibility == FeedCompatibility.OTC_MISMATCH:
        instrument = get_instrument(canonical_code)
        raise OTCFeedMismatchError(
            f"Cannot compare canonical instrument {instrument.code!r} "
            f"(otc={instrument.is_otc}) with a broker feed of otc={broker_is_otc}. "
            "OTC and regular feeds are not interchangeable."
        )
    return compatibility


class SymbolMapper:
    """Resolves and validates canonical <-> broker symbol mappings."""

    @staticmethod
    def resolve(canonical_code: str, profile=None):
        """Return the active :class:`MarketSymbol` for a canonical code.

        A profile-specific mapping wins over a global mapping (``profile=None``).
        Raises :class:`SymbolMappingError` when nothing matches.
        """
        from apps.market_data.models import MarketSymbol

        instrument = get_instrument(canonical_code)
        queryset = MarketSymbol.objects.filter(canonical=instrument.code, is_active=True)
        if profile is not None:
            scoped = queryset.filter(profile=profile).first()
            if scoped is not None:
                return scoped
        global_match = queryset.filter(profile__isnull=True).first()
        if global_match is None:
            raise SymbolMappingError(
                f"No MT5 symbol mapping configured for canonical {instrument.code!r}."
            )
        return global_match

    @staticmethod
    def validate(market_symbol) -> list[str]:
        """Return a list of human-readable problems with a mapping."""
        problems: list[str] = []
        if not market_symbol.broker_symbol:
            problems.append("Broker symbol is empty.")
        try:
            instrument = get_instrument(market_symbol.canonical)
        except SymbolMappingError as exc:
            problems.append(str(exc))
            return problems
        if instrument.is_otc != bool(market_symbol.is_otc):
            problems.append(
                f"OTC flag mismatch: canonical otc={instrument.is_otc} "
                f"but mapping otc={market_symbol.is_otc}."
            )
        return problems
