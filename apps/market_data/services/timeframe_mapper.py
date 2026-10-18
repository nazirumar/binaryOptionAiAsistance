"""Timeframe normalisation between the project, MT5 constants and durations."""

from __future__ import annotations

from datetime import timedelta

from apps.market_data.constants import Timeframe
from apps.market_data.services.exceptions import (
    MT5UnavailableError,
    UnsupportedTimeframeError,
)

#: Canonical timeframe -> duration in seconds.
TIMEFRAME_SECONDS: dict[str, int] = {
    "M1": 60,
    "M2": 120,
    "M3": 180,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

SUPPORTED_TIMEFRAMES: tuple[str, ...] = tuple(TIMEFRAME_SECONDS)
MT5_TIMEFRAME_MAP: dict[str, str] = {name: f"TIMEFRAME_{name}" for name in SUPPORTED_TIMEFRAMES}


def is_supported(timeframe: str) -> bool:
    return timeframe in TIMEFRAME_SECONDS


def duration_seconds(timeframe: str) -> int:
    """Return the timeframe duration in seconds.

    Raises:
        UnsupportedTimeframeError: if the timeframe is not supported.
    """
    try:
        return TIMEFRAME_SECONDS[timeframe]
    except KeyError as exc:
        raise UnsupportedTimeframeError(
            f"Unsupported timeframe {timeframe!r}. Supported: {', '.join(SUPPORTED_TIMEFRAMES)}"
        ) from exc


def duration(timeframe: str) -> timedelta:
    return timedelta(seconds=duration_seconds(timeframe))


def to_mt5(timeframe: str) -> int:
    """Map a canonical timeframe to the MetaTrader5 ``TIMEFRAME_*`` constant.

    Raises:
        UnsupportedTimeframeError: if the timeframe is unsupported.
        MT5UnavailableError: if the MetaTrader5 package cannot be imported.
    """
    if timeframe not in MT5_TIMEFRAME_MAP:
        raise UnsupportedTimeframeError(f"Unsupported timeframe {timeframe!r}")
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise MT5UnavailableError(
            "The MetaTrader5 package is not installed. It is Windows-only."
        ) from exc
    return int(getattr(mt5, MT5_TIMEFRAME_MAP[timeframe]))


def from_mt5(value: int) -> str:
    """Reverse-map an MT5 timeframe constant to the canonical name.

    Raises:
        UnsupportedTimeframeError: if the constant does not map to a supported timeframe.
    """
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise MT5UnavailableError("The MetaTrader5 package is not installed.") from exc
    for name in SUPPORTED_TIMEFRAMES:
        if int(getattr(mt5, MT5_TIMEFRAME_MAP[name])) == int(value):
            return name
    raise UnsupportedTimeframeError(f"Unknown MT5 timeframe constant: {value}")


__all__ = [
    "MT5_TIMEFRAME_MAP",
    "SUPPORTED_TIMEFRAMES",
    "TIMEFRAME_SECONDS",
    "Timeframe",
    "duration",
    "duration_seconds",
    "from_mt5",
    "is_supported",
    "to_mt5",
]
