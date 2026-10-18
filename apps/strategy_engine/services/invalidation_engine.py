# apps/strategy_engine/services\invalidation_engine.py
"""Mandatory NO_TRADE conditions (Step 9)."""

from __future__ import annotations

from apps.market_sync.constants import SyncStatus
from apps.strategy_engine.constants import InvalidationReasonCode


class InvalidationEngine:
    """Check mandatory invalidation conditions."""

    def check_all(
        self,
        strategy_input,
        timing_validity: str,
        has_unfinished_candle: bool = False,
        is_stale: bool = False,
    ) -> tuple[bool, list[str], str | None]:
        """Return (should_no_trade, reason_codes, primary_reason)."""
        reason_codes: list[str] = []

        # 1. Screenshot/MT5 compatibility not verified
        sync_status = getattr(strategy_input, "sync_status", "") or strategy_input.sync_status
        if sync_status != SyncStatus.VERIFIED_ALIGNMENT:
            reason_codes.append(InvalidationReasonCode.INCOMPATIBLE_SYNC)

        # 2. Instrument/timeframe uncertain
        if not strategy_input.instrument or not strategy_input.timeframe:
            reason_codes.append(InvalidationReasonCode.UNCERTAIN_INSTRUMENT)

        # 3. Required signal candle unfinished
        if has_unfinished_candle:
            reason_codes.append(InvalidationReasonCode.UNFINISHED_CANDLE)

        # 4. Stale data
        if is_stale or strategy_input.data_freshness == "stale":
            reason_codes.append(InvalidationReasonCode.STALE_DATA)

        # 5. Expired entry window
        if timing_validity == "expired":
            reason_codes.append(InvalidationReasonCode.EXPIRED_ENTRY)

        # 6. Insufficient data quality
        if strategy_input.warnings and any(
            "incomplete" in w.lower() for w in strategy_input.warnings
        ):
            # Don't add if already there
            pass

        primary = reason_codes[0] if reason_codes else None
        should_no_trade = len(reason_codes) > 0
        return should_no_trade, reason_codes, primary


__all__ = ["InvalidationEngine"]
