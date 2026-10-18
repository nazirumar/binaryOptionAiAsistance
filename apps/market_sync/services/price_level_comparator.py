"""Price-level comparison (Step 10).

Numeric price comparison is attempted **only** when reliable axis labels are
present. Even then the two platforms are never assumed to share bid/ask: any
systematic offset is *reported*, never applied to shift prices into agreement.
When scaling is unavailable the engine falls back to relative structure only.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from apps.market_sync.constants import PriceComparisonMethod
from apps.market_sync.services.dto import PriceLevelComparison


class _HasOHLC(Protocol):
    high: Any
    low: Any


def parse_price_labels(labels: list[Any] | None) -> list[float]:
    """Extract numeric price levels from free-text axis labels."""
    values: list[float] = []
    for item in labels or []:
        text = re.sub(r"[^0-9.\-]", "", str(item).replace(",", ""))
        if text.count(".") > 1 or text in {"", "-", "."}:
            continue
        try:
            values.append(float(text))
        except ValueError:
            continue
    return values


class PriceLevelComparator:
    """Compares screenshot axis labels with MT5 levels where possible."""

    def compare(
        self,
        visible_price_labels: list[Any] | None,
        mt5_candles: list[_HasOHLC],
    ) -> PriceLevelComparison:
        labels = parse_price_labels(visible_price_labels)

        if len(labels) < 2 or not mt5_candles:
            reason = (
                "No reliable numeric price-axis labels; relative structure comparison only."
                if not labels
                else "Too few readable price labels to establish scaling."
            )
            return PriceLevelComparison(
                method=PriceComparisonMethod.RELATIVE_STRUCTURE,
                matched=None,
                offset=None,
                metrics={"readable_labels": len(labels)},
                reasons=(reason,),
            )

        label_min, label_max = min(labels), max(labels)
        mt5_min = min(float(candle.low) for candle in mt5_candles)
        mt5_max = max(float(candle.high) for candle in mt5_candles)

        label_mid = (label_min + label_max) / 2
        mt5_mid = (mt5_min + mt5_max) / 2
        offset = label_mid - mt5_mid

        overlap = min(label_max, mt5_max) - max(label_min, mt5_min)
        label_span = label_max - label_min
        matched: bool | None
        if label_span <= 0:
            matched = None
        else:
            matched = overlap > 0 and (overlap / label_span) >= 0.5

        return PriceLevelComparison(
            method=PriceComparisonMethod.NUMERIC_AXIS,
            matched=matched,
            offset=offset,
            metrics={
                "label_min": label_min,
                "label_max": label_max,
                "mt5_min": mt5_min,
                "mt5_max": mt5_max,
                "readable_labels": len(labels),
            },
            reasons=(
                "Axis labels compared; the reported offset is informational and prices are "
                "never shifted to force a match.",
            ),
        )


def compare_price_levels(
    visible_price_labels: list[Any] | None,
    mt5_candles: list[_HasOHLC],
) -> PriceLevelComparison:
    return PriceLevelComparator().compare(visible_price_labels, mt5_candles)


__all__ = ["PriceLevelComparator", "compare_price_levels", "parse_price_labels"]
