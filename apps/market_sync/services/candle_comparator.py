"""Completed-candle matching and candle comparison (Steps 7 & 8).

Two hard rules govern this module:

1. Only candles that can be reliably classified as *completed* are compared;
   the rightmost screenshot candle is excluded upstream.
2. The screenshot contributes **qualitative** observations (direction, relative
   body/wick size bands, relative pixel positions) — never invented OHLC prices.
   MT5 provides the numeric reference data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from apps.chart_vision.constants import CandleClassification, SizeBand
from apps.market_sync.constants import CandleMatch
from apps.market_sync.services.config import SyncConfig
from apps.market_sync.services.dto import (
    AlignmentResult,
    CandleAlignmentRecord,
    CandleComparison,
)

#: Ordinal ranks for the size bands, used for sequence comparisons.
_BAND_RANK = {
    SizeBand.NONE: 0,
    SizeBand.SMALL: 1,
    SizeBand.MEDIUM: 2,
    SizeBand.LARGE: 3,
}

_UNKNOWN_BANDS = {"", SizeBand.UNKNOWN, None}


class _HasOHLC(Protocol):
    open: Any
    high: Any
    low: Any
    close: Any


def _ratio(part: float, whole: float) -> float | None:
    if not whole:
        return None
    return part / whole


def mt5_direction(candle: _HasOHLC, *, doji_body_ratio_max: float) -> str:
    """Classify an MT5 candle as bullish/bearish/doji using its numeric OHLC."""
    high = float(candle.high)
    low = float(candle.low)
    open_ = float(candle.open)
    close = float(candle.close)
    rng = high - low
    body = abs(close - open_)
    if rng <= 0:
        return CandleClassification.DOJI
    if _ratio(body, rng) <= doji_body_ratio_max:
        return CandleClassification.DOJI
    return CandleClassification.BULLISH if close > open_ else CandleClassification.BEARISH


def body_ratio(candle: _HasOHLC) -> float | None:
    rng = float(candle.high) - float(candle.low)
    return _ratio(abs(float(candle.close) - float(candle.open)), rng)


def upper_wick_ratio(candle: _HasOHLC) -> float | None:
    high = float(candle.high)
    low = float(candle.low)
    top = max(float(candle.open), float(candle.close))
    return _ratio(high - top, high - low)


def lower_wick_ratio(candle: _HasOHLC) -> float | None:
    high = float(candle.high)
    low = float(candle.low)
    bottom = min(float(candle.open), float(candle.close))
    return _ratio(bottom - low, high - low)


def size_band(ratio: float | None, *, small_max: float, medium_max: float) -> str:
    """Map a ratio onto a size band using configurable cut-offs."""
    if ratio is None:
        return SizeBand.UNKNOWN
    if ratio <= small_max:
        return SizeBand.SMALL
    if ratio <= medium_max:
        return SizeBand.MEDIUM
    return SizeBand.LARGE


def _band_rank(band: str) -> int | None:
    if band in _UNKNOWN_BANDS:
        return None
    return _BAND_RANK.get(band)


def _combine(*values: bool | None) -> bool | None:
    known = [value for value in values if value is not None]
    if not known:
        return None
    return all(known)


class CandleComparator:
    """Aligns completed screenshot candles to MT5 candles and compares them."""

    def __init__(self, config: SyncConfig | None = None) -> None:
        self.config = config or SyncConfig.from_settings()

    def compare(
        self,
        screenshot_candles: list[dict[str, Any]],
        mt5_candles_by_open: dict[datetime, _HasOHLC],
        alignment: AlignmentResult,
    ) -> CandleComparison:
        cfg = self.config
        records: list[CandleAlignmentRecord] = []
        previous_mt5: _HasOHLC | None = None
        previous_shot: dict[str, Any] | None = None

        for candle in screenshot_candles[: cfg.max_candles]:
            index = int(candle.get("index", len(records)))
            open_time = alignment.mt5_open_times.get(index)
            mt5_candle = mt5_candles_by_open.get(open_time) if open_time else None

            record = self._compare_one(
                candle=candle,
                index=index,
                open_time=open_time,
                mt5_candle=mt5_candle,
                previous_mt5=previous_mt5,
                previous_shot=previous_shot,
            )
            records.append(record)
            if mt5_candle is not None:
                previous_mt5 = mt5_candle
                previous_shot = candle

        return self._summarise(records)

    # -- per-candle ------------------------------------------------------

    def _compare_one(
        self,
        *,
        candle: dict[str, Any],
        index: int,
        open_time: datetime | None,
        mt5_candle: _HasOHLC | None,
        previous_mt5: _HasOHLC | None,
        previous_shot: dict[str, Any] | None,
    ) -> CandleAlignmentRecord:
        cfg = self.config
        shot_class = candle.get("classification") or CandleClassification.UNKNOWN
        shot_body = candle.get("body_size") or SizeBand.UNKNOWN
        shot_upper = candle.get("upper_wick") or SizeBand.UNKNOWN
        shot_lower = candle.get("lower_wick") or SizeBand.UNKNOWN
        position = candle.get("position") or ""

        base = {
            "screenshot_index": index,
            "screenshot_classification": shot_class,
            "screenshot_body_size": shot_body,
            "screenshot_upper_wick": shot_upper,
            "screenshot_lower_wick": shot_lower,
            "screenshot_position": position,
            "mt5_open_time": open_time,
        }

        if open_time is None or mt5_candle is None:
            limitation = (
                "No MT5 candle exists at the aligned interval."
                if open_time is not None
                else "Candle could not be aligned to an MT5 interval."
            )
            return CandleAlignmentRecord(
                **base,
                match_result=CandleMatch.UNALIGNED,
                limitations=(limitation,),
            )

        direction = mt5_direction(mt5_candle, doji_body_ratio_max=cfg.doji_body_ratio_max)
        b_ratio = body_ratio(mt5_candle)
        up_ratio = upper_wick_ratio(mt5_candle)
        low_ratio = lower_wick_ratio(mt5_candle)

        direction_match = None
        if shot_class != CandleClassification.UNKNOWN:
            direction_match = shot_class == direction

        mt5_body_band = size_band(
            b_ratio, small_max=cfg.body_band_small_max, medium_max=cfg.body_band_medium_max
        )
        body_match = None
        if shot_body not in _UNKNOWN_BANDS:
            body_match = shot_body == mt5_body_band

        mt5_upper_band = size_band(
            up_ratio, small_max=cfg.wick_band_small_max, medium_max=cfg.wick_band_medium_max
        )
        mt5_lower_band = size_band(
            low_ratio, small_max=cfg.wick_band_small_max, medium_max=cfg.wick_band_medium_max
        )
        upper_match = shot_upper == mt5_upper_band if shot_upper not in _UNKNOWN_BANDS else None
        lower_match = shot_lower == mt5_lower_band if shot_lower not in _UNKNOWN_BANDS else None
        wick_match = _combine(upper_match, lower_match)

        extremes = self._local_extremes(candle, mt5_candle, previous_shot, previous_mt5)

        comparable = [direction_match, body_match, wick_match, extremes]
        known = [value for value in comparable if value is not None]
        if not known:
            match_result = CandleMatch.INSUFFICIENT
            limitations = ("Screenshot candle lacks comparable detail.",)
        elif all(known):
            match_result = CandleMatch.MATCHED
            limitations = ()
        else:
            match_result = CandleMatch.MISMATCHED
            limitations = ("At least one compared attribute disagrees with MT5.",)

        confidence = sum(1 for value in known if value) / len(known) if known else None

        return CandleAlignmentRecord(
            **base,
            mt5_candle_id=getattr(mt5_candle, "pk", None),
            mt5_direction=direction,
            mt5_body_ratio=b_ratio,
            mt5_upper_wick_ratio=up_ratio,
            mt5_lower_wick_ratio=low_ratio,
            match_result=match_result,
            direction_match=direction_match,
            body_match=body_match,
            wick_match=wick_match,
            local_extreme_match=extremes,
            confidence=confidence,
            limitations=limitations,
            evidence={
                "screenshot_body_band": shot_body,
                "mt5_body_band": mt5_body_band,
                "screenshot_upper_wick": shot_upper,
                "mt5_upper_wick_band": mt5_upper_band,
                "screenshot_lower_wick": shot_lower,
                "mt5_lower_wick_band": mt5_lower_band,
            },
        )

    @staticmethod
    def _local_extremes(
        shot: dict[str, Any],
        mt5_candle: _HasOHLC,
        previous_shot: dict[str, Any] | None,
        previous_mt5: _HasOHLC | None,
    ) -> bool | None:
        if previous_shot is None or previous_mt5 is None:
            return None
        shot_high = shot.get("high_px")
        prev_shot_high = previous_shot.get("high_px")
        shot_low = shot.get("low_px")
        prev_shot_low = previous_shot.get("low_px")

        high_agree: bool | None = None
        if None not in (shot_high, prev_shot_high):
            # Higher price == smaller pixel Y.
            shot_higher = shot_high < prev_shot_high
            mt5_higher = float(mt5_candle.high) > float(previous_mt5.high)
            high_agree = shot_higher == mt5_higher

        low_agree: bool | None = None
        if None not in (shot_low, prev_shot_low):
            shot_lower = shot_low > prev_shot_low
            mt5_lower = float(mt5_candle.low) < float(previous_mt5.low)
            low_agree = shot_lower == mt5_lower

        return _combine(high_agree, low_agree)

    # -- aggregate -------------------------------------------------------

    def _summarise(self, records: list[CandleAlignmentRecord]) -> CandleComparison:
        matched = sum(1 for r in records if r.match_result == CandleMatch.MATCHED)
        mismatched = sum(1 for r in records if r.match_result == CandleMatch.MISMATCHED)
        insufficient = sum(1 for r in records if r.match_result == CandleMatch.INSUFFICIENT)
        unaligned = sum(1 for r in records if r.match_result == CandleMatch.UNALIGNED)

        aligned = matched + mismatched
        direction_agreement = _agreement([r.direction_match for r in records])
        body_agreement = _agreement([r.body_match for r in records])
        wick_agreement = _agreement([r.wick_match for r in records])
        sequence_agreement = self._sequence_agreement(records)

        reasons: list[str] = []
        if aligned == 0:
            reasons.append("No completed screenshot candle could be aligned to an MT5 candle.")
        if unaligned:
            reasons.append(f"{unaligned} candle(s) had no matching MT5 interval.")

        return CandleComparison(
            alignments=records,
            aligned_count=aligned,
            matched_count=matched,
            mismatched_count=mismatched,
            insufficient_count=insufficient,
            unaligned_count=unaligned,
            direction_agreement=direction_agreement,
            body_agreement=body_agreement,
            wick_agreement=wick_agreement,
            metrics={
                "size_sequence_agreement": sequence_agreement,
                "screenshot_candles": len(records),
            },
            reasons=tuple(reasons),
        )

    def _sequence_agreement(self, records: list[CandleAlignmentRecord]) -> float | None:
        cfg = self.config
        pairs = 0
        agree = 0
        previous: tuple[int, int] | None = None
        for record in records:
            shot_rank = _band_rank(record.screenshot_body_size)
            mt5_rank = _band_rank(
                size_band(
                    record.mt5_body_ratio,
                    small_max=cfg.body_band_small_max,
                    medium_max=cfg.body_band_medium_max,
                )
            )
            if shot_rank is None or mt5_rank is None:
                previous = None
                continue
            if previous is not None:
                pairs += 1
                if (shot_rank - previous[0] > 0) == (mt5_rank - previous[1] > 0):
                    agree += 1
            previous = (shot_rank, mt5_rank)
        if pairs == 0:
            return None
        return agree / pairs


def _agreement(flags: list[bool | None]) -> float | None:
    known = [flag for flag in flags if flag is not None]
    if not known:
        return None
    return sum(1 for flag in known if flag) / len(known)


def compare_candles(
    screenshot_candles: list[dict[str, Any]],
    mt5_candles_by_open: dict[datetime, _HasOHLC],
    alignment: AlignmentResult,
    config: SyncConfig | None = None,
) -> CandleComparison:
    return CandleComparator(config).compare(screenshot_candles, mt5_candles_by_open, alignment)


__all__ = [
    "CandleComparator",
    "body_ratio",
    "compare_candles",
    "lower_wick_ratio",
    "mt5_direction",
    "size_band",
    "upper_wick_ratio",
]
