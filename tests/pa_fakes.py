"""Synthetic OHLC fixtures for the Phase 5 price-action engine tests.

Everything here is hand-built and deterministic: no MT5 terminal, no network and
no randomness. Candles are plain dicts so the pure detectors can consume them
directly.
"""

from __future__ import annotations

from apps.price_action.services.config import PriceActionConfig

#: A configuration with the production defaults, injected explicitly so tests do
#: not depend on the ambient Django settings.
CONFIG = PriceActionConfig()


def candle(
    o: float, h: float, lo: float, c: float, *, v: float | None = 100.0, t: str | None = None
):
    row: dict = {"open": o, "high": h, "low": lo, "close": c}
    if v is not None:
        row["volume"] = v
    if t is not None:
        row["open_time"] = t
    return row


def flat(n: int = 10, price: float = 1.0) -> list[dict]:
    return [candle(price, price + 0.001, price - 0.001, price) for _ in range(n)]


def uptrend(n: int = 12, start: float = 1.0, step: float = 0.001) -> list[dict]:
    out = []
    price = start
    for _ in range(n):
        o = price
        c = price + step
        out.append(candle(o, c + 0.0002, o - 0.0002, c))
        price = c
    return out


def downtrend(n: int = 12, start: float = 1.0, step: float = 0.001) -> list[dict]:
    out = []
    price = start
    for _ in range(n):
        o = price
        c = price - step
        out.append(candle(o, o + 0.0002, c - 0.0002, c))
        price = c
    return out


def swing_high_low_series() -> list[dict]:
    """A clean up-down-up series producing labelled swings."""
    return [
        candle(1.000, 1.002, 0.999, 1.001),
        candle(1.001, 1.006, 1.000, 1.005),  # swing high
        candle(1.005, 1.006, 1.001, 1.002),
        candle(1.002, 1.003, 0.998, 0.999),  # swing low
        candle(0.999, 1.004, 0.998, 1.003),
        candle(1.003, 1.010, 1.002, 1.009),  # higher swing high
        candle(1.009, 1.010, 1.004, 1.005),
        candle(1.005, 1.006, 1.001, 1.002),  # higher swing low
        candle(1.002, 1.008, 1.001, 1.007),
        candle(1.007, 1.013, 1.006, 1.012),  # higher swing high
        candle(1.012, 1.013, 1.008, 1.009),
        candle(1.009, 1.010, 1.005, 1.006),
    ]


def resistance_touch_series() -> list[dict]:
    """Price repeatedly rejects a resistance level near 1.010."""
    return [
        candle(1.000, 1.005, 0.999, 1.004),
        candle(1.004, 1.010, 1.003, 1.006),
        candle(1.006, 1.010, 1.002, 1.003),
        candle(1.003, 1.009, 1.002, 1.008),
        candle(1.008, 1.011, 1.007, 1.009),
        candle(1.009, 1.010, 1.004, 1.005),
        candle(1.005, 1.010, 1.004, 1.009),
        candle(1.009, 1.011, 1.008, 1.010),
        candle(1.010, 1.011, 1.006, 1.007),
    ]


def bullish_fvg_series() -> list[dict]:
    """Three candles leaving a bullish imbalance between 1.000 and 1.005."""
    return [
        candle(0.998, 1.000, 0.997, 0.999),  # left: high 1.000
        candle(0.999, 1.010, 0.999, 1.009),  # middle: strong bullish impulse
        candle(1.009, 1.012, 1.005, 1.011),  # right: low 1.005 > left high
    ]


def bearish_fvg_series() -> list[dict]:
    return [
        candle(1.012, 1.013, 1.010, 1.011),  # left: low 1.010
        candle(1.011, 1.011, 1.001, 1.002),  # middle: strong bearish impulse
        candle(1.002, 1.005, 1.000, 1.003),  # right: high 1.005 < left low
    ]


def low_sweep_series() -> list[dict]:
    """A candle wicks below a prior low and closes back inside."""
    return [
        candle(1.000, 1.003, 0.998, 1.001),
        candle(1.001, 1.002, 0.995, 0.996),
        candle(0.996, 0.999, 0.990, 0.997),  # prior low 0.990
        candle(0.997, 0.998, 0.985, 0.995),  # sweeps 0.985, closes 0.995 back inside
    ]


def high_sweep_series() -> list[dict]:
    return [
        candle(1.000, 1.003, 0.998, 1.001),
        candle(1.001, 1.008, 1.000, 1.006),
        candle(1.006, 1.012, 1.004, 1.010),  # prior high 1.012
        candle(1.010, 1.016, 1.009, 1.011),  # sweeps 1.016, closes 1.011 back inside
    ]


def volume_anomaly_series() -> list[dict]:
    """Flat-ish candles then one high-volume narrow-range candle."""
    out = [candle(1.000, 1.005, 0.995, 1.002, v=100) for _ in range(6)]
    out.append(candle(1.002, 1.003, 1.001, 1.0025, v=400))
    return out


def console_runner() -> None:  # pragma: no cover - manual helper
    from apps.price_action.services.engine import PriceActionEngine

    result = PriceActionEngine(CONFIG).run(uptrend())
    print(result["summary"])


__all__ = [
    "CONFIG",
    "bearish_fvg_series",
    "bullish_fvg_series",
    "candle",
    "console_runner",
    "downtrend",
    "flat",
    "high_sweep_series",
    "low_sweep_series",
    "resistance_touch_series",
    "swing_high_low_series",
    "uptrend",
    "volume_anomaly_series",
]
