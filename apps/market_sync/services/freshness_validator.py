"""Data freshness and live-timing checks (Step 11).

Freshness is about *actionability*, not about correctness: a comparison can be
perfect yet useless if the screenshot predates the decision window. Checks are
deliberately conservative and every threshold is configurable and documented.
"""

from __future__ import annotations

from datetime import UTC, datetime

from apps.market_data.services.timeframe_mapper import duration_seconds
from apps.market_sync.constants import FreshnessStatus
from apps.market_sync.services.config import SyncConfig
from apps.market_sync.services.dto import FreshnessAssessment


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _seconds(moment: datetime | None, now: datetime) -> float | None:
    if moment is None:
        return None
    return (now - moment).total_seconds()


class FreshnessValidator:
    """Checks screenshot age, MT5 recency and the entry window."""

    def __init__(self, config: SyncConfig | None = None) -> None:
        self.config = config or SyncConfig.from_settings()

    def assess(
        self,
        *,
        anchor: datetime | None,
        mt5_latest_open: datetime | None,
        timeframe: str | None,
        now: datetime | None = None,
    ) -> FreshnessAssessment:
        cfg = self.config
        now = now or _utc_now()

        screenshot_age = _seconds(anchor, now)
        mt5_age = None
        if mt5_latest_open is not None and timeframe is not None:
            close_time = mt5_latest_open + _step(timeframe)
            mt5_age = (now - close_time).total_seconds()

        reasons: list[str] = []
        status = FreshnessStatus.FRESH

        if screenshot_age is None:
            status = FreshnessStatus.UNKNOWN
            reasons.append("Screenshot age is unknown (no trustworthy capture timestamp).")
        elif screenshot_age > cfg.screenshot_max_age_seconds:
            status = FreshnessStatus.STALE_SCREENSHOT
            reasons.append(
                f"Screenshot is {screenshot_age:.0f}s old (limit "
                f"{cfg.screenshot_max_age_seconds}s); it may no longer reflect the market."
            )

        if mt5_age is not None and mt5_age > cfg.mt5_max_candle_age_seconds:
            status = (
                FreshnessStatus.STALE_MT5
                if status in (FreshnessStatus.FRESH, FreshnessStatus.UNKNOWN)
                else status
            )
            reasons.append(
                f"Latest MT5 candle closed {mt5_age:.0f}s ago (limit "
                f"{cfg.mt5_max_candle_age_seconds}s); the feed may be stale."
            )

        entry_window_expired = False
        if timeframe is not None and screenshot_age is not None:
            entry_window_expired = screenshot_age > float(duration_seconds(timeframe))
            if entry_window_expired:
                reasons.append(
                    f"The screenshot predates the current {timeframe} candle; a next-candle "
                    "signal from it would no longer be actionable."
                )

        return FreshnessAssessment(
            status=status,
            screenshot_age_seconds=screenshot_age,
            mt5_age_seconds=mt5_age,
            entry_window_expired=entry_window_expired,
            metrics={
                "screenshot_max_age_seconds": cfg.screenshot_max_age_seconds,
                "mt5_max_candle_age_seconds": cfg.mt5_max_candle_age_seconds,
                "timeframe_seconds": duration_seconds(timeframe) if timeframe else None,
            },
            reasons=tuple(reasons),
        )


def _step(timeframe: str):
    from datetime import timedelta

    return timedelta(seconds=duration_seconds(timeframe))


def validate_freshness(
    *,
    anchor: datetime | None,
    mt5_latest_open: datetime | None,
    timeframe: str | None,
    now: datetime | None = None,
    config: SyncConfig | None = None,
) -> FreshnessAssessment:
    return FreshnessValidator(config).assess(
        anchor=anchor, mt5_latest_open=mt5_latest_open, timeframe=timeframe, now=now
    )


__all__ = ["FreshnessValidator", "validate_freshness"]
