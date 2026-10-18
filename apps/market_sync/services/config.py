"""Configurable thresholds and limits for the synchronization engine.

Every numeric cut-off used by the comparator lives here so it is:

* **configurable** through environment variables (``SYNC_*``), and
* **testable** — callers can inject a :class:`SyncConfig` directly.

These thresholds are *pragmatic defaults chosen for a qualitative/relative
comparison*. They are **not** scientifically validated market parameters and
should be tuned per broker/venue.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.market_sync.constants import SYNC_CONFIG_VERSION


def _get(name: str, default):
    return getattr(settings, name, default)


@dataclass(frozen=True, slots=True)
class SyncConfig:
    """Immutable snapshot of the comparison configuration for one run."""

    #: Hard bound on how many MT5 candles / screenshot candles are compared.
    max_candles: int = 200
    #: Minimum number of overlapping *completed* candles required to judge.
    min_overlap_candles: int = 3
    #: Direction agreement required (0-1) for a fully verified alignment.
    direction_match_min: float = 0.75
    #: Direction agreement required (0-1) to claim partial alignment.
    direction_partial_min: float = 0.5
    #: Body-to-range ratio at or below which an MT5 candle is a doji.
    doji_body_ratio_max: float = 0.12
    #: Body/range ratio upper bounds for the "small"/"medium" size bands.
    body_band_small_max: float = 0.25
    body_band_medium_max: float = 0.60
    #: Wick/range ratio upper bounds for the "small"/"medium" size bands.
    wick_band_small_max: float = 0.20
    wick_band_medium_max: float = 0.45
    #: Absolute tolerance applied when comparing relative size ratios.
    body_ratio_tolerance: float = 0.30
    wick_ratio_tolerance: float = 0.35
    #: A screenshot older than this (seconds) is stale for verification.
    screenshot_max_age_seconds: int = 3600
    #: MT5 data whose last completed candle is older than this is stale.
    mt5_max_candle_age_seconds: int = 900
    #: Tolerance (seconds) when snapping a timestamp onto a candle grid.
    timestamp_tolerance_seconds: int = 5
    #: Minimum overlapping candles required to compare market structure.
    min_structure_overlap: int = 5
    #: Fraction of comparable structure items that must agree.
    structure_agree_min: float = 0.70
    #: Swing lookback (candles each side) for swing-point detection.
    swing_lookback: int = 2
    #: Default timezone offset (minutes) applied to naive screenshot times.
    default_tz_offset_minutes: int = 0
    #: Recorded on every session for auditability.
    config_version: str = SYNC_CONFIG_VERSION

    @classmethod
    def from_settings(cls) -> SyncConfig:
        return cls(
            max_candles=int(_get("SYNC_MAX_CANDLES", cls.max_candles)),
            min_overlap_candles=int(_get("SYNC_MIN_OVERLAP_CANDLES", cls.min_overlap_candles)),
            direction_match_min=float(_get("SYNC_DIRECTION_MATCH_MIN", cls.direction_match_min)),
            direction_partial_min=float(
                _get("SYNC_DIRECTION_PARTIAL_MIN", cls.direction_partial_min)
            ),
            doji_body_ratio_max=float(_get("SYNC_DOJI_BODY_RATIO_MAX", cls.doji_body_ratio_max)),
            body_band_small_max=float(_get("SYNC_BODY_BAND_SMALL_MAX", cls.body_band_small_max)),
            body_band_medium_max=float(_get("SYNC_BODY_BAND_MEDIUM_MAX", cls.body_band_medium_max)),
            wick_band_small_max=float(_get("SYNC_WICK_BAND_SMALL_MAX", cls.wick_band_small_max)),
            wick_band_medium_max=float(_get("SYNC_WICK_BAND_MEDIUM_MAX", cls.wick_band_medium_max)),
            body_ratio_tolerance=float(_get("SYNC_BODY_RATIO_TOLERANCE", cls.body_ratio_tolerance)),
            wick_ratio_tolerance=float(_get("SYNC_WICK_RATIO_TOLERANCE", cls.wick_ratio_tolerance)),
            screenshot_max_age_seconds=int(
                _get("SYNC_SCREENSHOT_MAX_AGE_SECONDS", cls.screenshot_max_age_seconds)
            ),
            mt5_max_candle_age_seconds=int(
                _get("SYNC_MT5_MAX_CANDLE_AGE_SECONDS", cls.mt5_max_candle_age_seconds)
            ),
            timestamp_tolerance_seconds=int(
                _get("SYNC_TIMESTAMP_TOLERANCE_SECONDS", cls.timestamp_tolerance_seconds)
            ),
            min_structure_overlap=int(
                _get("SYNC_MIN_STRUCTURE_OVERLAP", cls.min_structure_overlap)
            ),
            structure_agree_min=float(_get("SYNC_STRUCTURE_AGREE_MIN", cls.structure_agree_min)),
            swing_lookback=int(_get("SYNC_SWING_LOOKBACK", cls.swing_lookback)),
            default_tz_offset_minutes=int(
                _get("SYNC_DEFAULT_TZ_OFFSET_MINUTES", cls.default_tz_offset_minutes)
            ),
            config_version=str(_get("SYNC_CONFIG_VERSION", cls.config_version)),
        )


__all__ = ["SyncConfig"]
