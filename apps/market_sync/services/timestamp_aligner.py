"""Screenshot-timestamp alignment (Step 6).

The aligner maps each *completed* screenshot candle, left to right, onto a
candle-open time on the MT5 grid. It never treats the upload time as the capture
time, and never fabricates a timestamp: when no trustworthy anchor exists the
result is explicitly flagged as uncertain (the caller may then fall back to the
latest completed MT5 candle and mark the run unverified).
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta, timezone

from apps.market_data.services.timeframe_mapper import duration_seconds
from apps.market_sync.constants import AlignmentSource
from apps.market_sync.services.dto import AlignmentResult

_NAIVE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%Y-%m-%d",
)

#: Confidence assigned by anchor source (documented, configurable behaviour).
_SOURCE_CONFIDENCE = {
    AlignmentSource.USER_PROVIDED: 0.9,
    AlignmentSource.VISIBLE_TIMESTAMP: 0.9,
    AlignmentSource.CAPTURE_METADATA: 0.6,
    AlignmentSource.MT5_LAST_COMPLETED: 0.3,
    AlignmentSource.NONE: None,
}


def parse_timestamp(value, *, tz_offset_minutes: int | None = None) -> datetime | None:
    """Parse a timestamp into an aware UTC datetime, applying a tz offset.

    Naive values are interpreted using ``tz_offset_minutes`` (the chart's UTC
    offset); aware values are converted to UTC unchanged.
    """
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).strip()
        if not text:
            return None
        moment = _parse_text(text)
        if moment is None:
            return None

    if moment.tzinfo is None:
        offset = tz_offset_minutes or 0
        moment = moment.replace(tzinfo=timezone(timedelta(minutes=offset)))
    return moment.astimezone(UTC)


def _parse_text(text: str) -> datetime | None:
    candidate = re.sub(r"[Zz]$", "+00:00", text)
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        pass
    for fmt in _NAIVE_FORMATS:
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue
    return None


def floor_to_grid(moment: datetime, step_seconds: int) -> datetime:
    """Floor a UTC timestamp down to the start of its candle interval."""
    epoch = moment.timestamp()
    floored = math.floor(epoch / step_seconds) * step_seconds
    return datetime.fromtimestamp(floored, tz=UTC)


def last_completed_open(anchor: datetime, step_seconds: int) -> datetime:
    """The open time of the last candle that has fully closed at ``anchor``."""
    return floor_to_grid(anchor - timedelta(seconds=step_seconds), step_seconds)


class TimestampAligner:
    """Resolves an anchor and maps completed candles onto the MT5 grid."""

    def resolve_anchor(
        self,
        *,
        visible_timestamp=None,
        captured_at=None,
        capture_metadata_time=None,
        tz_offset_minutes: int | None = None,
    ) -> tuple[datetime | None, str, float | None, list[str]]:
        """Return ``(anchor, source, confidence, reasons)`` in priority order."""
        reasons: list[str] = []

        if captured_at not in (None, ""):
            parsed = parse_timestamp(captured_at, tz_offset_minutes=tz_offset_minutes)
            if parsed is not None:
                return (
                    parsed,
                    AlignmentSource.USER_PROVIDED,
                    _SOURCE_CONFIDENCE[AlignmentSource.USER_PROVIDED],
                    reasons,
                )
            reasons.append("The user-provided capture time could not be parsed.")

        if visible_timestamp not in (None, ""):
            parsed = parse_timestamp(visible_timestamp, tz_offset_minutes=tz_offset_minutes)
            if parsed is not None:
                return (
                    parsed,
                    AlignmentSource.VISIBLE_TIMESTAMP,
                    _SOURCE_CONFIDENCE[AlignmentSource.VISIBLE_TIMESTAMP],
                    reasons,
                )
            reasons.append("The visible chart timestamp could not be parsed.")

        if capture_metadata_time not in (None, ""):
            parsed = parse_timestamp(capture_metadata_time, tz_offset_minutes=tz_offset_minutes)
            if parsed is not None:
                return (
                    parsed,
                    AlignmentSource.CAPTURE_METADATA,
                    _SOURCE_CONFIDENCE[AlignmentSource.CAPTURE_METADATA],
                    reasons,
                )
            reasons.append("Screenshot capture metadata did not contain a usable time.")

        reasons.append(
            "No trustworthy screenshot timestamp is available; upload time is not used as "
            "the capture time."
        )
        return None, AlignmentSource.NONE, None, reasons

    def build_alignment(
        self,
        *,
        completed_indices: list[int],
        timeframe: str,
        last_open: datetime,
        source: str,
        confidence: float | None,
        uncertain: bool,
        reasons: list[str] | None = None,
    ) -> AlignmentResult:
        """Map each completed screenshot candle to an MT5 candle-open time."""
        step = duration_seconds(timeframe)
        total = len(completed_indices)
        mapping: dict[int, datetime] = {}
        for position, index in enumerate(completed_indices):
            offset_steps = total - 1 - position
            mapping[index] = last_open - timedelta(seconds=offset_steps * step)
        return AlignmentResult(
            anchor=last_open,
            source=source,
            confidence=confidence,
            uncertain=uncertain,
            mt5_open_times=mapping,
            reasons=tuple(reasons or ()),
        )


__all__ = [
    "TimestampAligner",
    "floor_to_grid",
    "last_completed_open",
    "parse_timestamp",
]
