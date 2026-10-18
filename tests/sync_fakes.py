"""Fakes, fixtures and factories for market-synchronization tests.

Everything is deterministic and DB-only: no MT5 terminal and no live vision
provider are required. Screenshot candle observations are derived from the MT5
fixtures using the *same* qualitative band formulas, which is exactly the
behaviour under test for the "full alignment" scenarios; disagreement scenarios
flip the screenshot side explicitly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from apps.chart_vision.constants import AnalysisStatus, UploadStatus
from apps.chart_vision.models import ChartScreenshot, ScreenshotAnalysis
from apps.market_data.constants import MappingStatus, QualityStatus, SymbolCategory
from apps.market_data.models import MarketCandle, MarketSymbol
from apps.market_sync.services.candle_comparator import (
    body_ratio,
    lower_wick_ratio,
    mt5_direction,
    size_band,
    upper_wick_ratio,
)
from apps.market_sync.services.config import SyncConfig

CONFIG = SyncConfig()


@dataclass(frozen=True, slots=True)
class Price:
    open: float
    high: float
    low: float
    close: float


# ---------------------------------------------------------------------------
# Instruments / candles
# ---------------------------------------------------------------------------
def make_symbol(
    *,
    canonical: str = "EURUSD",
    broker_symbol: str = "EURUSD",
    profile=None,
    is_otc: bool = False,
    mapping_status: str = MappingStatus.VALID,
    category: str = SymbolCategory.FOREX,
) -> MarketSymbol:
    return MarketSymbol.objects.create(
        profile=profile,
        canonical=canonical,
        broker_symbol=broker_symbol,
        category=category,
        is_otc=is_otc,
        is_active=True,
        mapping_status=mapping_status,
    )


def make_candle(
    symbol: MarketSymbol,
    timeframe: str,
    open_time: datetime,
    price: Price,
    *,
    is_complete: bool = True,
) -> MarketCandle:
    return MarketCandle.objects.create(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        open=price.open,
        high=price.high,
        low=price.low,
        close=price.close,
        is_complete=is_complete,
        quality_status=QualityStatus.OK,
    )


def minute_floor(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def now_floor() -> datetime:
    return minute_floor(datetime.now(tz=UTC))


# ---------------------------------------------------------------------------
# Price series
# ---------------------------------------------------------------------------
def uptrend_prices() -> list[Price]:
    """A 12-candle zigzag uptrend (HH/HL confirmed with lookback=2).

    Closes form peaks at w2/w6 and troughs at w4/w8 so that swing detection
    yields two swing highs (higher) and two swing lows (higher) -> uptrend.
    """
    closes = [
        1.0010,
        1.0030,
        1.0050,
        1.0030,
        1.0000,
        1.0025,
        1.0060,
        1.0040,
        1.0015,
        1.0035,
        1.0055,
        1.0070,
    ]
    opens = [1.0000, *closes[:-1]]
    highs = [
        1.0015,
        1.0035,
        1.0055,
        1.0045,
        1.0035,
        1.0030,
        1.0065,
        1.0060,
        1.0045,
        1.0040,
        1.0060,
        1.0075,
    ]
    lows = [
        0.9995,
        1.0005,
        1.0025,
        1.0015,
        0.9990,
        0.9995,
        1.0020,
        1.0030,
        1.0010,
        1.0015,
        1.0035,
        1.0050,
    ]
    return [
        Price(open=o, high=h, low=low, close=c)
        for o, h, low, c in zip(opens, highs, lows, closes, strict=True)
    ]


def flat_prices(count: int = 6, base: float = 1.0000) -> list[Price]:
    """A tight range of small candles (used for 'ranging' scenarios)."""
    prices = []
    for index in range(count):
        o = base + (index % 2) * 0.0001
        c = o + (0.0001 if index % 2 == 0 else -0.0001)
        prices.append(Price(open=o, high=max(o, c) + 0.00005, low=min(o, c) - 0.00005, close=c))
    return prices


# ---------------------------------------------------------------------------
# Screenshot candle observations derived from the MT5 fixtures
# ---------------------------------------------------------------------------
def _px(price: float) -> int:
    # Higher price -> smaller pixel Y (chart prices increase upward).
    return round((2.0 - price) * 1_000_000)


def _shot_candle(index: int, price: Price, config: SyncConfig = CONFIG) -> dict:
    direction = mt5_direction(price, doji_body_ratio_max=config.doji_body_ratio_max)
    body = size_band(
        body_ratio(price),
        small_max=config.body_band_small_max,
        medium_max=config.body_band_medium_max,
    )
    upper = size_band(
        upper_wick_ratio(price),
        small_max=config.wick_band_small_max,
        medium_max=config.wick_band_medium_max,
    )
    lower = size_band(
        lower_wick_ratio(price),
        small_max=config.wick_band_small_max,
        medium_max=config.wick_band_medium_max,
    )
    return {
        "index": index,
        "position": "middle",
        "classification": direction,
        "body_size": body,
        "upper_wick": upper,
        "lower_wick": lower,
        "high_px": _px(price.high),
        "low_px": _px(price.low),
        "body_top_px": _px(max(price.open, price.close)),
        "body_bottom_px": _px(min(price.open, price.close)),
        "appears_complete": True,
        "confidence": 0.8,
        "ambiguity": None,
    }


def screenshot_candles(
    prices: list[Price],
    *,
    config: SyncConfig = CONFIG,
    flip_direction: bool = False,
) -> list[dict]:
    """Build matching screenshot candles plus a rightmost incomplete candle."""
    candles = []
    for index, price in enumerate(prices):
        candle = _shot_candle(index, price, config)
        if flip_direction:
            if candle["classification"] == "bullish":
                candle["classification"] = "bearish"
            elif candle["classification"] == "bearish":
                candle["classification"] = "bullish"
        candles.append(candle)
    # Rightmost candle is always potentially incomplete and excluded upstream.
    rightmost = dict(
        candles[-1],
        index=len(prices),
        position="right",
        appears_complete=False,
        confidence=0.3,
    )
    candles.append(rightmost)
    return candles


def uptrend_structure() -> dict:
    return {
        "trend": "uptrend",
        "higher_highs": True,
        "higher_lows": True,
        "lower_highs": False,
        "lower_lows": False,
        "swing_highs": [],
        "swing_lows": [],
        "breakouts": [],
        "failed_breakouts": [],
        "consolidation": False,
    }


# ---------------------------------------------------------------------------
# Analysis fixtures
# ---------------------------------------------------------------------------
def make_analysis(
    owner,
    screenshot: ChartScreenshot | None = None,
    *,
    instrument: str = "EURUSD",
    timeframe: str = "M1",
    otc_status: str = "regular",
    screenshot_timestamp: str | None = None,
    candles: list[dict] | None = None,
    structure: dict | None = None,
    visible_price_labels: list[str] | None = None,
    status: str = AnalysisStatus.COMPLETED,
) -> ScreenshotAnalysis:
    if screenshot is None:
        screenshot = ChartScreenshot.objects.create(
            owner=owner,
            image="screenshots/test.png",
            original_filename="test.png",
            content_type="image/png",
            image_format="png",
            status=UploadStatus.ACCEPTED,
        )
    metadata = {
        "platform": "IQ Option",
        "instrument": instrument,
        "otc_status": otc_status,
        "timeframe": timeframe,
        "screenshot_timestamp": screenshot_timestamp,
        "visible_price_labels": visible_price_labels or [],
        "candle_colors": {"bullish": "green", "bearish": "red"},
        "orientation": "standard",
        "confidence": 0.8,
    }
    result = {
        "schema_version": "1.0",
        "analysis_status": "completed",
        "screenshot_quality": {"rating": "high", "issues": [], "notes": ""},
        "chart_metadata": metadata,
        "candles": candles or [],
        "market_structure": structure or uptrend_structure(),
        "support_resistance": [],
        "patterns": [],
        "sequence_observations": [],
        "market_cycle": {},
        "liquidity": [],
        "volume": {},
        "missing_information": [],
        "warnings": [],
        "observation_confidence": {"overall": 0.7},
    }
    return ScreenshotAnalysis.objects.create(
        screenshot=screenshot,
        owner=owner,
        status=status,
        idempotency_key=f"test:{uuid.uuid4().hex}",
        provider="mock",
        model_name="test",
        prompt_version="v1",
        schema_version="1.0",
        result=result,
        chart_metadata=metadata,
        candle_count=len(candles or []),
        observation_confidence=0.7,
    )


def build_aligned_scenario(
    owner,
    *,
    screenshot: ChartScreenshot | None = None,
    timeframe: str = "M1",
    instrument: str = "EURUSD",
    otc_status: str = "regular",
    broker_symbol: str = "EURUSD",
    mapping_status: str = MappingStatus.VALID,
    flip_direction: bool = False,
    structure: dict | None = None,
    is_otc_mapping: bool = False,
    canonical: str = "EURUSD",
    make_mt5: bool = True,
    with_timestamp: bool = True,
    shift_minutes: int = 0,
):
    """Create a symbol, an aligned MT5 series and a matching analysis.

    Returns ``(symbol, prices, analysis, anchor)``. The aligned window is the
    full 12-candle series; the anchor is the open of the next candle. Set
    ``shift_minutes`` to move the whole scenario into the past (staleness
    scenarios).
    """
    symbol = make_symbol(
        canonical=canonical,
        broker_symbol=broker_symbol,
        is_otc=is_otc_mapping,
        mapping_status=mapping_status,
    )
    prices = uptrend_prices()
    start = now_floor() - timedelta(minutes=len(prices) + 1) - timedelta(minutes=shift_minutes)
    if make_mt5:
        for index, price in enumerate(prices):
            make_candle(symbol, timeframe, start + timedelta(minutes=index), price)

    anchor = start + timedelta(minutes=len(prices))
    timestamp = anchor.isoformat().replace("+00:00", "Z") if with_timestamp else None
    analysis = make_analysis(
        owner,
        screenshot,
        instrument=instrument,
        timeframe=timeframe,
        otc_status=otc_status,
        screenshot_timestamp=timestamp,
        candles=screenshot_candles(prices, flip_direction=flip_direction),
        structure=structure if structure is not None else uptrend_structure(),
        visible_price_labels=["0.9990", "1.0075"],
    )
    return symbol, prices, analysis, anchor


__all__ = [
    "CONFIG",
    "Price",
    "build_aligned_scenario",
    "flat_prices",
    "make_analysis",
    "make_candle",
    "make_symbol",
    "minute_floor",
    "now_floor",
    "screenshot_candles",
    "uptrend_prices",
    "uptrend_structure",
]
