"""Market-structure comparison (Step 9).

MT5 structure (swing points, higher/lower highs & lows, trend, consolidation) is
derived numerically from the overlapping candles and compared with the
screenshot's own structure verdict. Agreement is only asserted when there is
enough overlapping data; otherwise the result is explicitly insufficient.
"""

from __future__ import annotations

from typing import Any, Protocol

from apps.chart_vision.constants import Trend
from apps.market_sync.constants import StructureAgreement
from apps.market_sync.services.config import SyncConfig
from apps.market_sync.services.dto import StructureComparison

_UNKNOWN_TRENDS = {"", None, Trend.UNCLEAR}


class _HasOHLC(Protocol):
    open: Any
    high: Any
    low: Any
    close: Any


def detect_swings(candles: list[_HasOHLC], lookback: int) -> tuple[list[int], list[int]]:
    """Return indices of swing highs and swing lows (strict, lookback each side)."""
    highs: list[int] = []
    lows: list[int] = []
    total = len(candles)
    for index in range(lookback, total - lookback):
        window = range(index - lookback, index + lookback + 1)
        value_high = float(candles[index].high)
        value_low = float(candles[index].low)
        if all(value_high >= float(candles[j].high) for j in window) and any(
            value_high > float(candles[j].high) for j in window if j != index
        ):
            highs.append(index)
        if all(value_low <= float(candles[j].low) for j in window) and any(
            value_low < float(candles[j].low) for j in window if j != index
        ):
            lows.append(index)
    return highs, lows


def analyse_mt5_structure(candles: list[_HasOHLC], config: SyncConfig) -> dict[str, Any]:
    """Derive speculative structure labels from MT5 OHLC (never fabricated)."""
    swing_high_idx, swing_low_idx = detect_swings(candles, config.swing_lookback)

    def _rel(idx_list: list[int], attr: str) -> tuple[bool | None, bool | None]:
        if len(idx_list) < 2:
            return None, None
        current = float(getattr(candles[idx_list[-1]], attr))
        previous = float(getattr(candles[idx_list[-2]], attr))
        return current > previous, current < previous

    hh, lh = _rel(swing_high_idx, "high")
    hl, ll = _rel(swing_low_idx, "low")

    if hh and hl:
        trend = Trend.UPTREND
    elif lh and ll:
        trend = Trend.DOWNTREND
    elif any(flag for flag in (hh, lh, hl, ll)):
        trend = Trend.UNCLEAR
    else:
        trend = Trend.RANGING

    consolidation = trend == Trend.RANGING

    return {
        "trend": trend,
        "higher_highs": hh,
        "higher_lows": hl,
        "lower_highs": lh,
        "lower_lows": ll,
        "consolidation": consolidation,
        "swing_high_count": len(swing_high_idx),
        "swing_low_count": len(swing_low_idx),
    }


class StructureComparator:
    """Compares screenshot structure with MT5-derived structure."""

    def __init__(self, config: SyncConfig | None = None) -> None:
        self.config = config or SyncConfig.from_settings()

    def compare(
        self,
        screenshot_structure: dict[str, Any] | None,
        mt5_candles: list[_HasOHLC],
        *,
        overlap_candles: int,
    ) -> StructureComparison:
        shot = screenshot_structure or {}
        shot_trend = shot.get("trend", Trend.UNCLEAR)
        mt5 = analyse_mt5_structure(mt5_candles, self.config)
        mt5_trend = mt5["trend"]

        reasons: list[str] = []
        if overlap_candles < self.config.min_structure_overlap:
            reasons.append(
                f"Only {overlap_candles} overlapping completed candle(s); at least "
                f"{self.config.min_structure_overlap} are required to compare structure."
            )
            return StructureComparison(
                agreement=StructureAgreement.INSUFFICIENT,
                screenshot_trend=shot_trend,
                mt5_trend=mt5_trend,
                comparable_items=0,
                agreeing_items=0,
                metrics={"mt5": mt5, "overlap_candles": overlap_candles},
                reasons=tuple(reasons),
            )

        comparable = 0
        agreeing = 0

        if shot_trend not in _UNKNOWN_TRENDS and mt5_trend not in _UNKNOWN_TRENDS:
            comparable += 1
            if shot_trend == mt5_trend:
                agreeing += 1
        else:
            reasons.append("Screenshot trend is unclear/unreadable; trend not compared.")

        for key in ("higher_highs", "higher_lows", "lower_highs", "lower_lows"):
            shot_value = shot.get(key)
            mt5_value = mt5.get(key)
            if isinstance(shot_value, bool) and isinstance(mt5_value, bool):
                comparable += 1
                if shot_value == mt5_value:
                    agreeing += 1

        shot_consolidation = shot.get("consolidation")
        if isinstance(shot_consolidation, bool):
            comparable += 1
            if shot_consolidation == mt5["consolidation"]:
                agreeing += 1

        if comparable == 0:
            reasons.append("No comparable structure items were available.")
            agreement = StructureAgreement.INSUFFICIENT
        else:
            ratio = agreeing / comparable
            if ratio >= self.config.structure_agree_min:
                agreement = StructureAgreement.AGREE
            elif ratio >= 0.5:
                agreement = StructureAgreement.PARTIAL
            else:
                agreement = StructureAgreement.DISAGREE
            if agreement != StructureAgreement.AGREE:
                reasons.append(f"Structure agreement is {agreeing}/{comparable} comparable items.")

        return StructureComparison(
            agreement=agreement,
            screenshot_trend=shot_trend,
            mt5_trend=mt5_trend,
            comparable_items=comparable,
            agreeing_items=agreeing,
            metrics={
                "mt5": mt5,
                "overlap_candles": overlap_candles,
                "agreement_ratio": (agreeing / comparable) if comparable else None,
            },
            reasons=tuple(reasons),
        )


def compare_structure(
    screenshot_structure: dict[str, Any] | None,
    mt5_candles: list[_HasOHLC],
    *,
    overlap_candles: int,
    config: SyncConfig | None = None,
) -> StructureComparison:
    return StructureComparator(config).compare(
        screenshot_structure, mt5_candles, overlap_candles=overlap_candles
    )


__all__ = [
    "StructureComparator",
    "analyse_mt5_structure",
    "compare_structure",
    "detect_swings",
]
