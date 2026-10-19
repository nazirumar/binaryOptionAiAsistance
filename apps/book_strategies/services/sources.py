# book_strategies/services/sources.py
"""Candle sources shared by book-strategy management commands.

Two honest sources, never mixed:

* **MT5 rows** - complete candles with ``quality_status="ok"`` (suspect rows
  are excluded, never silently repaired);
* **Imported historical datasets** - rows written by
  ``DatasetBuilder.import_ohlc`` with recorded provenance.

Every dict carries ``open_time`` and ``complete`` so downstream services can
do freshness/outcome-window checks instead of trusting the caller.
"""

from __future__ import annotations

from typing import Any

from apps.research.models import HistoricalCandle, HistoricalDataset


def mt5_candle_groups(
    *, symbol: str = "", timeframe: str = ""
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Group complete, quality-ok MT5 candles by (canonical symbol, timeframe)."""
    from apps.market_data.models import MarketCandle

    qs = MarketCandle.objects.filter(is_complete=True, quality_status="ok")
    if symbol:
        qs = qs.filter(symbol__canonical=symbol)
    if timeframe:
        qs = qs.filter(timeframe=timeframe)

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in qs.order_by("symbol__canonical", "timeframe", "open_time"):
        key = (row.symbol.canonical, row.timeframe)
        groups.setdefault(key, []).append(
            {
                "open_time": row.open_time,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "complete": bool(row.is_complete),
            }
        )
    return groups


def dataset_candles(dataset_id: int) -> tuple[HistoricalDataset, list[dict[str, Any]]]:
    """Load one imported historical dataset as ordered candle dicts."""
    dataset = HistoricalDataset.objects.filter(pk=dataset_id).first()
    if dataset is None:
        raise ValueError(f"historical dataset {dataset_id} not found")
    rows = list(HistoricalCandle.objects.filter(dataset=dataset).order_by("open_time"))
    if not rows:
        raise ValueError(f"historical dataset {dataset_id} contains no candles")
    return dataset, [
        {
            "open_time": row.open_time,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "complete": bool(row.is_complete),
        }
        for row in rows
    ]


def require_groups(groups: dict[tuple[str, str], list[dict[str, Any]]]) -> None:
    """Raise when no candles matched - nothing is fabricated when data is absent."""
    if not groups:
        raise ValueError(
            "no complete candles matched the filter - this command needs a "
            "real dataset (nothing is fabricated when data is absent)"
        )


__all__ = ["dataset_candles", "mt5_candle_groups", "require_groups"]
