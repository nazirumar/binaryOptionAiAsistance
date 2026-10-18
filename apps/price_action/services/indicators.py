# price_action/services/indicators.py
"""Deterministic indicator math for the book-strategy detectors (Phase 13).

Every function here is pure and *causal*: the value at index ``i`` uses only
``candles[0..i]``. No future candle can ever leak into a detection or into a
backtest signal, which is what makes chronological replay testing sound.

Indicator settings follow the Binary Options Trading Bible defaults where it
states them (Stochastic 14/3 with %K as the "green" line and %D as the "red"
line, Parabolic SAR starting at 0.02, Donchian channel period 17, EMA 5).
"""

from __future__ import annotations

from statistics import fmean
from typing import Any

#: Book default stochastic: IQ Option's default %K/%D smoothing.
STOCHASTIC_K = 14
STOCHASTIC_D = 3
#: Book-declared Parabolic SAR start value.
PSAR_START = 0.02
PSAR_STEP = 0.02
PSAR_MAX = 0.2
#: Book-declared Donchian channel period (Chapter 7, Strategy 2).
DONCHIAN_PERIOD = 17
#: Book-declared EMA period (Chapter 7, both strategies).
EMA_PERIOD = 5


def stochastic(
    candles: list[dict[str, Any]],
    *,
    k: int = STOCHASTIC_K,
    d: int = STOCHASTIC_D,
) -> tuple[list[float | None], list[float | None]]:
    """Return ``(%K, %D)`` series aligned with ``candles``.

    ``%K`` (the book's "green line") is the raw stochastic over ``k`` candles;
    ``%D`` (the "red line") is its ``d``-period simple average. Entries are
    ``None`` until enough candles exist - the caller must treat ``None`` as
    "indicator unavailable", never as a supportive value.
    """
    n = len(candles)
    percent_k: list[float | None] = [None] * n
    raw: list[float] = []
    for i in range(n):
        if i + 1 < k:
            continue
        window = candles[i + 1 - k : i + 1]
        lowest = min(float(w["low"]) for w in window)
        highest = max(float(w["high"]) for w in window)
        span = highest - lowest
        raw.append(50.0 if span <= 0 else 100.0 * (float(candles[i]["close"]) - lowest) / span)
        percent_k[i] = raw[-1]

    percent_d: list[float | None] = [None] * n
    for j in range(d - 1, len(raw)):
        # raw[j] corresponds to candle index j + k - 1.
        percent_d[j + k - 1] = fmean(raw[j + 1 - d : j + 1])
    return percent_k, percent_d


def stochastic_supported(
    candles: list[dict[str, Any]], index: int, *, direction: str
) -> bool | None:
    """Book stochastic gate at ``index``; ``None`` when the indicator is unavailable.

    Up trades need the green line above the red (``%K > %D``); down trades the
    reverse. This never guesses: with too few candles it returns ``None``.
    """
    percent_k, percent_d = stochastic(candles)
    if index >= len(candles):
        return None
    k_val, d_val = percent_k[index], percent_d[index]
    if k_val is None or d_val is None:
        return None
    if direction == "bullish":
        return k_val > d_val
    if direction == "bearish":
        return k_val < d_val
    return None


def ema(values: list[float], period: int = EMA_PERIOD) -> list[float | None]:
    """Exponential moving average seeded with an SMA; ``None`` until seeded."""
    out: list[float | None] = [None] * len(values)
    if len(values) < period or period < 1:
        return out
    seed = fmean(values[:period])
    out[period - 1] = seed
    multiplier = 2.0 / (period + 1)
    previous = seed
    for i in range(period, len(values)):
        previous = (float(values[i]) - previous) * multiplier + previous
        out[i] = previous
    return out


def parabolic_sar(
    candles: list[dict[str, Any]],
    *,
    af_start: float = PSAR_START,
    af_step: float = PSAR_STEP,
    af_max: float = PSAR_MAX,
) -> list[float | None]:
    """Parabolic SAR using the book's default 0.02 start (standard algorithm).

    The first trend direction is taken from the first two closes. Values are
    ``None`` until the second candle. A SAR *below* the candle supports bullish
    trades; above supports bearish trades.
    """
    n = len(candles)
    out: list[float | None] = [None] * n
    if n < 2:
        return out

    rising = float(candles[1]["close"]) >= float(candles[0]["close"])
    sar = float(candles[0]["low"]) if rising else float(candles[0]["high"])
    extreme = float(candles[0]["high"]) if rising else float(candles[0]["low"])
    acceleration = af_start
    out[1] = sar

    for i in range(1, n):
        row = candles[i]
        previous = candles[i - 1]
        sar = sar + acceleration * (extreme - sar)
        if rising:
            floor = float(previous["low"])
            if i >= 2:
                floor = min(floor, float(candles[i - 2]["low"]))
            sar = min(sar, floor)
            if float(row["low"]) < sar:
                # Flip to a downtrend: the old extreme becomes the new SAR.
                rising = False
                sar = extreme
                extreme = float(row["low"])
                acceleration = af_start
            elif float(row["high"]) > extreme:
                extreme = float(row["high"])
                acceleration = min(acceleration + af_step, af_max)
        else:
            ceiling = float(previous["high"])
            if i >= 2:
                ceiling = max(ceiling, float(candles[i - 2]["high"]))
            sar = max(sar, ceiling)
            if float(row["high"]) > sar:
                rising = True
                sar = extreme
                extreme = float(row["high"])
                acceleration = af_start
            elif float(row["low"]) < extreme:
                extreme = float(row["low"])
                acceleration = min(acceleration + af_step, af_max)
        out[i] = sar
    return out


def donchian(
    candles: list[dict[str, Any]], period: int = DONCHIAN_PERIOD
) -> list[dict[str, float] | None]:
    """Trailing Donchian channel (upper/lower/mid) ending at each index.

    Uses only the trailing ``period`` candles up to and including index ``i``.
    """
    out: list[dict[str, float] | None] = [None] * len(candles)
    for i in range(len(candles)):
        if i + 1 < period:
            continue
        window = candles[i + 1 - period : i + 1]
        upper = max(float(w["high"]) for w in window)
        lower = min(float(w["low"]) for w in window)
        out[i] = {"upper": upper, "lower": lower, "mid": (upper + lower) / 2.0}
    return out
