"""Deterministic validation of market data.

The validator **never** fabricates, fills or interpolates data. It reports issues
that callers persist (as health events and quality statuses) so that downstream
analysis can refuse to run on unreliable input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Any

from apps.market_data.constants import FeedCompatibility, QualityStatus, Severity
from apps.market_data.services.dto import Candle, Tick
from apps.market_data.services.symbol_mapper import (
    SymbolMapper,
    check_feed_type_compatibility,
)
from apps.market_data.services.timeframe_mapper import duration

#: Cap on how many concrete examples are embedded in an issue's context.
_MAX_EXAMPLES = 20


@dataclass(slots=True, frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        return self.severity in {Severity.ERROR, Severity.CRITICAL}

    @property
    def is_warning(self) -> bool:
        return self.severity == Severity.WARNING


@dataclass(slots=True, frozen=True)
class CandleValidationResult:
    issues: list[ValidationIssue]

    @property
    def has_errors(self) -> bool:
        return any(issue.is_error for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(issue.is_warning for issue in self.issues)

    @property
    def quality_status(self) -> str:
        if self.has_errors:
            return QualityStatus.INVALID
        if self.has_warnings:
            return QualityStatus.SUSPECT
        return QualityStatus.OK


def _is_non_positive(value: Decimal | None) -> bool:
    return value is not None and value <= 0


def validate_candle_series(candles: list[Candle], timeframe: str) -> CandleValidationResult:
    """Validate an ordered-or-not series of candles for a timeframe."""
    issues: list[ValidationIssue] = []
    if not candles:
        issues.append(
            ValidationIssue(
                code="empty_series",
                severity=Severity.WARNING,
                message="No candles were supplied for validation.",
            )
        )
        return CandleValidationResult(issues=issues)

    # Duplicate timestamps.
    seen: set[datetime] = set()
    duplicates: list[str] = []
    for candle in candles:
        if candle.open_time in seen:
            if len(duplicates) < _MAX_EXAMPLES:
                duplicates.append(candle.open_time.isoformat())
        seen.add(candle.open_time)
    if duplicates:
        issues.append(
            ValidationIssue(
                code="duplicate_timestamps",
                severity=Severity.ERROR,
                message=f"Found {len(duplicates)} duplicate candle open time(s).",
                context={"examples": duplicates},
            )
        )

    # Monotonic ordering.
    ordered = sorted(candles, key=lambda c: c.open_time)
    if [c.open_time for c in candles] != [c.open_time for c in ordered]:
        issues.append(
            ValidationIssue(
                code="non_monotonic_order",
                severity=Severity.WARNING,
                message="Candles were not supplied in ascending open-time order.",
            )
        )

    # OHLC integrity and price sanity.
    invalid_ohlc: list[str] = []
    non_positive: list[str] = []
    negative_spread: list[str] = []
    for candle in candles:
        ts = candle.open_time.isoformat()
        if (
            candle.high < candle.low
            or candle.high < max(candle.open, candle.close)
            or candle.low > min(candle.open, candle.close)
        ):
            if len(invalid_ohlc) < _MAX_EXAMPLES:
                invalid_ohlc.append(ts)
        if any(_is_non_positive(v) for v in (candle.open, candle.high, candle.low, candle.close)):
            if len(non_positive) < _MAX_EXAMPLES:
                non_positive.append(ts)
        if candle.spread is not None and candle.spread < 0:
            if len(negative_spread) < _MAX_EXAMPLES:
                negative_spread.append(ts)

    if invalid_ohlc:
        issues.append(
            ValidationIssue(
                code="invalid_ohlc",
                severity=Severity.ERROR,
                message=f"{len(invalid_ohlc)} candle(s) violate OHLC relationships.",
                context={"examples": invalid_ohlc},
            )
        )
    if non_positive:
        issues.append(
            ValidationIssue(
                code="non_positive_price",
                severity=Severity.ERROR,
                message=f"{len(non_positive)} candle(s) have non-positive prices.",
                context={"examples": non_positive},
            )
        )
    if negative_spread:
        issues.append(
            ValidationIssue(
                code="negative_spread",
                severity=Severity.WARNING,
                message=f"{len(negative_spread)} candle(s) report a negative spread.",
                context={"examples": negative_spread},
            )
        )

    # Missing candles (gaps). Gaps also arise legitimately from market closure,
    # so this is a warning, never treated as an error and never back-filled.
    missing = detect_missing_candles(ordered, timeframe)
    if missing:
        issues.append(
            ValidationIssue(
                code="missing_candles",
                severity=Severity.WARNING,
                message=f"{len(missing)} expected candle(s) are missing (gaps may be market closure).",
                context={"examples": [m.isoformat() for m in missing[:_MAX_EXAMPLES]]},
            )
        )

    return CandleValidationResult(issues=issues)


def detect_missing_candles(candles: list[Candle], timeframe: str) -> list[datetime]:
    """Return expected open times absent from a sorted candle series."""
    if len(candles) < 2:
        return []
    step = duration(timeframe)
    present = {c.open_time for c in candles}
    ordered = sorted(present)
    missing: list[datetime] = []
    for previous, current in pairwise(ordered):
        expected = previous + step
        guard = 0
        while expected < current and guard < 100000:
            if expected not in present:
                missing.append(expected)
            expected += step
            guard += 1
    return missing


def validate_tick(
    tick: Tick,
    *,
    now: datetime | None = None,
    stale_seconds: int = 120,
) -> list[ValidationIssue]:
    """Validate a single tick for sanity and staleness."""
    issues: list[ValidationIssue] = []
    now = now or datetime.now(tz=UTC)

    if tick.bid is None and tick.ask is None and tick.last is None:
        issues.append(
            ValidationIssue(
                code="tick_missing_prices",
                severity=Severity.ERROR,
                message="Tick contains no bid, ask or last price.",
            )
        )
        return issues

    if _is_non_positive(tick.bid) or _is_non_positive(tick.ask):
        issues.append(
            ValidationIssue(
                code="tick_non_positive_price",
                severity=Severity.ERROR,
                message="Tick bid/ask is non-positive.",
                context={"bid": str(tick.bid), "ask": str(tick.ask)},
            )
        )

    if tick.bid is not None and tick.ask is not None and tick.bid > tick.ask:
        issues.append(
            ValidationIssue(
                code="tick_crossed_spread",
                severity=Severity.ERROR,
                message="Tick bid is greater than ask (crossed book).",
                context={"bid": str(tick.bid), "ask": str(tick.ask)},
            )
        )

    age = (now - tick.time).total_seconds()
    if age > stale_seconds:
        issues.append(
            ValidationIssue(
                code="stale_tick",
                severity=Severity.WARNING,
                message=f"Tick is stale (age {age:.1f}s > {stale_seconds}s).",
                context={"age_seconds": round(age, 3)},
            )
        )
    elif age < -stale_seconds:
        issues.append(
            ValidationIssue(
                code="future_tick",
                severity=Severity.WARNING,
                message="Tick timestamp is in the future.",
                context={"age_seconds": round(age, 3)},
            )
        )
    return issues


def validate_symbol_mapping(
    market_symbol: Any, *, now: datetime | None = None
) -> CandleValidationResult:
    """Validate a canonical <-> broker mapping, including OTC compatibility."""
    issues: list[ValidationIssue] = []
    for problem in SymbolMapper.validate(market_symbol):
        issues.append(
            ValidationIssue(
                code="invalid_mapping",
                severity=Severity.ERROR,
                message=problem,
            )
        )

    compatibility = check_feed_type_compatibility(
        market_symbol.canonical,
        broker_is_otc=bool(market_symbol.is_otc),
    )
    if compatibility == FeedCompatibility.OTC_MISMATCH:
        issues.append(
            ValidationIssue(
                code="otc_mismatch",
                severity=Severity.ERROR,
                message=(
                    "OTC/regular feed mismatch: this mapping is not comparable with "
                    "the canonical instrument and must not be treated as equivalent."
                ),
                context={"canonical": market_symbol.canonical},
            )
        )
    return CandleValidationResult(issues=issues)


def summarise_issues(issues: list[ValidationIssue]) -> str:
    """Short human-readable summary used in sync logs."""
    if not issues:
        return "ok"
    errors = sum(1 for i in issues if i.is_error)
    warnings = sum(1 for i in issues if i.is_warning)
    return f"{len(issues)} issue(s): {errors} error(s), {warnings} warning(s)"


__all__ = [
    "CandleValidationResult",
    "ValidationIssue",
    "detect_missing_candles",
    "summarise_issues",
    "validate_candle_series",
    "validate_symbol_mapping",
    "validate_tick",
]
