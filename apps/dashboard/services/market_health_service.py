# apps/dashboard/services/market_health_service.py
"""Market-data health monitoring (Phase 9, Step 10).

Surfaces the same MT5 health information as the existing market-data card, plus
symbol mapping, timeframe support, feed compatibility and OTC warnings. When
MT5 is not configured or reachable, meaningful troubleshooting guidance is
returned instead of an empty page.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.market_data.constants import (
    ConnectionState,
    FeedCompatibility,
    MappingStatus,
    Timeframe,
)
from apps.market_data.dashboard import dashboard_context, derived_connection_state
from apps.market_data.models import (
    MarketDataHealthEvent,
    MarketSymbol,
    MT5ConnectionProfile,
)

TROUBLESHOOTING = {
    ConnectionState.UNKNOWN: [
        "No MT5 worker heartbeats have been received yet.",
        "Verify the MT5 bridge worker is running and pointed at the correct profile.",
    ],
    ConnectionState.DISCONNECTED: [
        "The MT5 terminal is not currently connected.",
        "Confirm the MetaTrader 5 terminal is running and logged in.",
        "Check the configured server and account credentials reference.",
    ],
    ConnectionState.ERROR: [
        "The last connection attempt reported an error.",
        "Review the recent health events below for the failure reason.",
        "Confirm the broker server name and that algorithmic trading is permitted.",
    ],
    ConnectionState.CONNECTED: [],
}


class MarketHealthService:
    """Assemble the market-data health page for one user."""

    def __init__(self, user) -> None:  # type: ignore[no-untyped-def]
        self.user = user

    def build(self, profile=None) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        context = dashboard_context(profile)
        state = context.get("connection_state") or derived_connection_state(profile)
        return {
            **context,
            "connection_state": state,
            "troubleshooting": TROUBLESHOOTING.get(state, []),
            "profiles": self._profiles(),
            "symbols": self._symbols(profile),
            "timeframes": [tf.value for tf in Timeframe],
            "feed_compatibility": self._feed_compatibility(profile),
            "otc_warnings": self._otc_warnings(profile),
            "recent_errors": self._recent_errors(profile),
            "checked_at": timezone.now(),
        }

    def _profiles(self) -> list[dict[str, Any]]:
        profiles = MT5ConnectionProfile.objects.filter(owner__in=[self.user, None])
        return [
            {
                "id": profile.pk,
                "name": profile.name,
                "server": profile.server or getattr(settings, "MT5_SERVER", "") or "—",
                "masked_login": getattr(profile, "masked_login", "") or "—",
                "is_active": profile.is_active,
                "state": profile.state,
            }
            for profile in profiles
        ]

    def _symbols(self, profile) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
        symbols = MarketSymbol.objects.filter(is_active=True)
        if profile is not None:
            symbols = symbols.filter(profile=profile)
        symbols = symbols.order_by("canonical")[:100]
        return [
            {
                "canonical": symbol.canonical,
                "broker_symbol": symbol.broker_symbol,
                "category": symbol.category,
                "is_otc": symbol.is_otc,
                "mapping_status": symbol.mapping_status,
                "digits": symbol.digits,
            }
            for symbol in symbols
        ]

    def _feed_compatibility(self, profile) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        symbols = MarketSymbol.objects.filter(is_active=True)
        if profile is not None:
            symbols = symbols.filter(profile=profile)
        verified = symbols.filter(mapping_status=MappingStatus.VALID).count()
        total = symbols.count()
        if total == 0:
            status = FeedCompatibility.UNVERIFIED
        elif verified == total:
            status = FeedCompatibility.VERIFIED
        else:
            status = FeedCompatibility.DATA_MISMATCH
        return {
            "status": status,
            "verified_symbols": verified,
            "total_symbols": total,
        }

    def _otc_warnings(self, profile) -> list[str]:  # type: ignore[no-untyped-def]
        otc = MarketSymbol.objects.filter(is_active=True, is_otc=True)
        if profile is not None:
            otc = otc.filter(profile=profile)
        if not otc.exists():
            return []
        return [
            (
                "OTC instruments have no real-market equivalent; MT5 cannot "
                "reproduce IQ Option OTC settlement prices."
            ),
            f"{otc.count()} OTC symbol(s) are configured.",
        ]

    def _recent_errors(self, profile) -> list[MarketDataHealthEvent]:  # type: ignore[no-untyped-def]
        events = MarketDataHealthEvent.objects.order_by("-occurred_at")
        if profile is not None:
            events = events.filter(profile=profile)
        return list(events.filter(severity__in=["error", "critical", "warning"])[:15])


__all__ = ["TROUBLESHOOTING", "MarketHealthService"]
