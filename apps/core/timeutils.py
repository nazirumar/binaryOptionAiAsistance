# apps/core/timeutils.py
"""Timezone-aware datetime parsing shared across engines (Phase 11 CP5).

Rules (enforced, not advisory):

* An **offset-aware** input (``Z``, ``+01:00``, ``-05:30``, or a tz-aware
  ``datetime``) is converted to UTC and returned.
* A **naive** input is accepted **only** when its source timezone is explicitly
  supplied by the caller (``source_tz``) — e.g. a documented broker-server
  timezone. It is then localised with that zone and converted to UTC.
* A naive input *without* a defined source timezone is **rejected** (returns
  ``None``). Silently assuming UTC (or local time) is exactly the class of bug
  this module exists to prevent: an ambiguous timestamp must never be shifted
  to a plausible-looking instant.
* Unparseable input is rejected (``None``).

The project runs with ``USE_TZ=True`` / ``TIME_ZONE="UTC"``; every datetime
that reaches a model field or a timing comparison must be UTC-aware.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any


def parse_iso_datetime(
    value: Any,
    *,
    source_tz: tzinfo | None = None,
    field: str = "",
) -> datetime | None:
    """Parse ``value`` into a UTC-aware datetime, or ``None`` when ambiguous.

    ``field`` is an optional label used by callers for error reporting; this
    function itself never raises for bad data.
    """
    if value is None or value == "":
        return None

    parsed: datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            # Python 3.11+ fromisoformat understands ``Z`` and numeric offsets.
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None

    return ensure_utc(parsed, source_tz=source_tz, field=field)


def ensure_utc(
    value: datetime,
    *,
    source_tz: tzinfo | None = None,
    field: str = "",
) -> datetime | None:
    """Return ``value`` as a UTC-aware datetime, or ``None`` when ambiguous."""
    del field  # reserved for future error plumbing
    if value.tzinfo is None:
        if source_tz is None:
            # Ambiguous: no offset and no declared source timezone.
            return None
        value = value.replace(tzinfo=source_tz)
    return value.astimezone(UTC)


def utc_iso(value: datetime | None) -> str | None:
    """ISO-8601 UTC rendering with ``Z`` (for JSON payloads)."""
    if value is None:
        return None
    aware = ensure_utc(value)
    if aware is None:  # pragma: no cover - naive without source_tz
        return None
    return aware.isoformat().replace("+00:00", "Z")


def is_aware(value: datetime | None) -> bool:
    return value is not None and value.tzinfo is not None


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def add_seconds(value: datetime, seconds: float) -> datetime:
    return value + timedelta(seconds=seconds)


__all__ = [
    "add_seconds",
    "ensure_utc",
    "is_aware",
    "parse_iso_datetime",
    "utc_iso",
    "utc_now",
]
