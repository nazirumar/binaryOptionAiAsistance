"""Timeframe interpretation and comparison (Step 5).

The screenshot timeframe is parsed from free text but is **never** assumed: a
missing or unreadable value stays :data:`None` so the caller can mark the
synchronization unverified rather than silently choosing a default.
"""

from __future__ import annotations

import re

from apps.market_data.services.timeframe_mapper import SUPPORTED_TIMEFRAMES
from apps.market_sync.services.dto import TimeframeMatch

_MISSING = {"", "UNKNOWN", "UNREADABLE", "N/A", "NA", "-", "NONE", "NULL"}

_DURATION_UNITS = {
    "M": "M",
    "MIN": "M",
    "MINUTE": "M",
    "MINUTES": "M",
    "H": "H",
    "HR": "H",
    "HOUR": "H",
    "HOURS": "H",
    "D": "D",
    "DAY": "D",
    "DAYS": "D",
}

_TRAILING = re.compile(r"^(\d+)([A-Z]+)$")
_LEADING = re.compile(r"^([A-Z])(\d+)$")


def parse_timeframe(raw: str) -> str | None:
    """Return a canonical timeframe (``M1``..``D1``) or ``None``.

    Understands ``M15``, ``15m``, ``1 min``, ``H1``, ``4h``, ``D1``, ``1 day``.
    """
    text = re.sub(r"\s+", "", (raw or "").upper())
    if text in _MISSING:
        return None
    if text in SUPPORTED_TIMEFRAMES:
        return text

    trailing = _TRAILING.match(text)
    if trailing:
        number, unit_text = trailing.groups()
        unit = _DURATION_UNITS.get(unit_text)
        if unit:
            candidate = f"{unit}{int(number)}"
            return candidate if candidate in SUPPORTED_TIMEFRAMES else None
        return None

    leading = _LEADING.match(text)
    if leading:
        unit, number = leading.groups()
        if unit in {"M", "H", "D"}:
            candidate = f"{unit}{int(number)}"
            return candidate if candidate in SUPPORTED_TIMEFRAMES else None

    return None


class TimeframeMatcher:
    """Compares the screenshot timeframe with the MT5 timeframe."""

    def match(self, screenshot_raw: str, mt5_timeframe: str | None) -> TimeframeMatch:
        raw = (screenshot_raw or "").strip()
        screenshot = parse_timeframe(raw)
        reasons: list[str] = []

        if screenshot is None:
            reasons.append("Screenshot timeframe is missing or unreadable; it is never assumed.")

        if mt5_timeframe is not None and mt5_timeframe not in SUPPORTED_TIMEFRAMES:
            reasons.append(f"MT5 timeframe {mt5_timeframe!r} is not supported.")

        mismatch = False
        if screenshot is not None and mt5_timeframe is not None:
            if screenshot != mt5_timeframe:
                mismatch = True
                reasons.append(
                    f"Timeframe mismatch: screenshot shows {screenshot} but the MT5 series "
                    f"is {mt5_timeframe}."
                )

        return TimeframeMatch(
            screenshot_timeframe=screenshot,
            screenshot_raw=raw,
            mt5_timeframe=mt5_timeframe,
            supported=screenshot is not None,
            mismatch=mismatch,
            reasons=tuple(reasons),
        )


def match_timeframe(screenshot_raw: str, mt5_timeframe: str | None) -> TimeframeMatch:
    return TimeframeMatcher().match(screenshot_raw, mt5_timeframe)


__all__ = ["TimeframeMatcher", "match_timeframe", "parse_timeframe"]
