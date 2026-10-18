"""Instrument identification between a screenshot and MT5 symbols (Step 3).

The matcher deliberately refuses to *guess* equivalence from a similar-looking
name. It resolves a mapping only when:

* the screenshot symbol normalises to a known canonical instrument **and** an
  explicit :class:`~apps.market_data.models.MarketSymbol` mapping exists, or
* an explicit broker-symbol mapping matches the screenshot symbol exactly
  (this is how broker prefixes/suffixes such as ``EURUSDm`` or ``GBPUSD.pro``
  are supported — through data, never through string trimming).

Ambiguous (multiple distinct) mappings are rejected rather than resolved by
order.
"""

from __future__ import annotations

import re

from apps.market_data.constants import MappingStatus
from apps.market_data.models import MarketSymbol
from apps.market_data.services.exceptions import SymbolMappingError
from apps.market_data.services.symbol_mapper import (
    SymbolMapper,
    get_instrument,
)
from apps.market_sync.constants import MappingSource
from apps.market_sync.services.dto import InstrumentMatch

#: Tokens that mean "not readable".
_MISSING_TOKENS = {"", "UNKNOWN", "UNREADABLE", "N/A", "NA", "-", "NONE", "NULL"}

_UNUSABLE_MAPPING_STATUS = {MappingStatus.INVALID, MappingStatus.MISMATCH}


def _tokenize(raw: str) -> list[str]:
    return [token for token in re.split(r"[^A-Za-z0-9]+", (raw or "").upper()) if token]


def has_otc_token(raw: str) -> bool:
    """Return True when the raw symbol carries an explicit OTC marker."""
    return any(token == "OTC" or token.endswith("OTC") for token in _tokenize(raw))


def _base_symbol(raw: str) -> str:
    """Normalised symbol with OTC markers and separators removed."""
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper().replace("OTC", ""))


def _profile_broker(profile, mapping: MarketSymbol | None) -> str:
    if profile is not None:
        return getattr(profile, "broker", "") or ""
    if mapping is not None and mapping.profile_id is not None:
        return getattr(mapping.profile, "broker", "") or ""
    return ""


class InstrumentMatcher:
    """Resolves and validates a screenshot instrument against MT5 mappings."""

    def match(self, raw: str, *, profile=None) -> InstrumentMatch:
        raw_text = (raw or "").strip()
        if raw_text.upper() in _MISSING_TOKENS:
            return InstrumentMatch(
                screenshot_instrument=raw_text,
                supported=False,
                ambiguous=False,
                screenshot_is_otc=None,
                reasons=("Instrument/symbol is missing or unreadable on the screenshot.",),
            )

        screenshot_is_otc = has_otc_token(raw_text)
        raw_base = _base_symbol(raw_text)

        try:
            canonical_code = get_instrument(raw_base).code
        except SymbolMappingError:
            canonical_code = ""

        pool = self._candidate_pool(profile)
        exact = [item for item in pool if _base_symbol(item.broker_symbol) == raw_base]

        mapping: MarketSymbol | None = None
        mapping_source = MappingSource.NONE
        reasons: list[str] = []

        if exact:
            preferred = self._prefer(exact, profile)
            if len(preferred) > 1:
                return self._ambiguous(raw_text, screenshot_is_otc, preferred)
            mapping = preferred[0]
            mapping_source = MappingSource.BROKER_SYMBOL_EXACT
        elif canonical_code:
            canonical_matches = [item for item in pool if item.canonical == canonical_code]
            preferred = self._prefer(canonical_matches, profile)
            if len(preferred) > 1:
                return self._ambiguous(raw_text, screenshot_is_otc, preferred)
            if preferred:
                mapping = preferred[0]
                mapping_source = MappingSource.CANONICAL

        if mapping is None:
            detail = (
                f"No MT5 symbol mapping is configured for {raw_text!r}. "
                "Equivalence is never inferred from a similar name."
            )
            return InstrumentMatch(
                screenshot_instrument=raw_text,
                supported=False,
                ambiguous=False,
                canonical_instrument=canonical_code,
                screenshot_is_otc=screenshot_is_otc,
                reasons=(detail,),
            )

        canonical_code = mapping.canonical or canonical_code
        try:
            instrument = get_instrument(canonical_code)
        except SymbolMappingError:
            return InstrumentMatch(
                screenshot_instrument=raw_text,
                supported=False,
                ambiguous=False,
                canonical_instrument=canonical_code,
                screenshot_is_otc=screenshot_is_otc,
                reasons=(f"Mapping points at an unknown canonical instrument {canonical_code!r}.",),
            )

        problems = SymbolMapper.validate(mapping)
        unusable = mapping.mapping_status in _UNUSABLE_MAPPING_STATUS
        if unusable:
            return InstrumentMatch(
                screenshot_instrument=raw_text,
                supported=False,
                ambiguous=False,
                canonical_instrument=instrument.code,
                broker_symbol=mapping.broker_symbol,
                broker=_profile_broker(profile, mapping),
                market_type=mapping.category or instrument.category,
                mapping_source=mapping_source,
                mapping_status=mapping.mapping_status,
                screenshot_is_otc=screenshot_is_otc,
                reference_is_otc=bool(mapping.is_otc),
                reference_id=mapping.pk,
                reasons=(
                    f"MT5 mapping {mapping.broker_symbol!r} is marked "
                    f"{mapping.get_mapping_status_display().lower()} and cannot be trusted.",
                ),
            )

        mapping_verified = mapping.mapping_status == MappingStatus.VALID and not problems
        if mapping.mapping_status != MappingStatus.VALID:
            reasons.append(
                f"MT5 mapping {mapping.broker_symbol!r} has not been validated against the broker."
            )
        reasons.extend(problems)

        return InstrumentMatch(
            screenshot_instrument=raw_text,
            supported=True,
            ambiguous=False,
            canonical_instrument=instrument.code,
            broker_symbol=mapping.broker_symbol,
            broker=_profile_broker(profile, mapping),
            market_type=mapping.category or instrument.category,
            mapping_source=mapping_source,
            mapping_status=mapping.mapping_status,
            mapping_verified=mapping_verified,
            screenshot_is_otc=screenshot_is_otc,
            reference_is_otc=bool(mapping.is_otc),
            reference_id=mapping.pk,
            reasons=tuple(reasons),
        )

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _candidate_pool(profile) -> list[MarketSymbol]:
        from django.db.models import Q

        queryset = MarketSymbol.objects.filter(is_active=True).select_related("profile")
        if profile is not None:
            queryset = queryset.filter(Q(profile=profile) | Q(profile__isnull=True))
        else:
            queryset = queryset.filter(profile__isnull=True)
        return list(queryset)

    @staticmethod
    def _prefer(items: list[MarketSymbol], profile) -> list[MarketSymbol]:
        """Apply the same precedence as ``SymbolMapper``: profile beats global."""
        if profile is not None:
            scoped = [item for item in items if item.profile_id == profile.pk]
            if scoped:
                return scoped
        return [item for item in items if item.profile_id is None] or items

    @staticmethod
    def _ambiguous(raw: str, is_otc: bool, items) -> InstrumentMatch:
        symbols = ", ".join(sorted({item.broker_symbol for item in items}))
        return InstrumentMatch(
            screenshot_instrument=raw,
            supported=False,
            ambiguous=True,
            screenshot_is_otc=is_otc,
            reasons=(f"Multiple MT5 mappings match {raw!r} ({symbols}); refusing to guess.",),
        )


def resolve_instrument(raw: str, *, profile=None) -> InstrumentMatch:
    """Convenience wrapper around :class:`InstrumentMatcher`."""
    return InstrumentMatcher().match(raw, profile=profile)


__all__ = ["InstrumentMatcher", "has_otc_token", "resolve_instrument"]
