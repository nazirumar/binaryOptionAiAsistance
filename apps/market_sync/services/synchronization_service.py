"""Orchestration of a screenshot-vs-MT5 verification run (Steps 3-13).

The service is synchronous and DB-only: it compares the *stored* Phase 3
analysis payload against *stored* Phase 2 candles, so it is deterministic and
runs on the web tier without an MT5 terminal. Optional Celery execution wraps
:meth:`SynchronizationService.run_session`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from django.utils import timezone

from apps.chart_vision.constants import AnalysisStatus, ScreenshotQuality
from apps.market_data.models import MarketCandle
from apps.market_sync.constants import (
    AlignmentSource,
    AuditKind,
    CandleMatch,
    ComparisonMethod,
    FeedCompatibilityStatus,
    FreshnessStatus,
    PriceComparisonMethod,
    SessionStatus,
    Severity,
    StructureAgreement,
    SyncStatus,
)
from apps.market_sync.exceptions import MissingScreenshotAnalysisError
from apps.market_sync.models import (
    CandleAlignment,
    FeedCompatibilityAssessment,
    MarketSyncIssue,
    MarketSyncSession,
    SynchronizationAuditLog,
)
from apps.market_sync.services import mismatch_reporter as reporter
from apps.market_sync.services.candle_comparator import CandleComparator
from apps.market_sync.services.config import SyncConfig
from apps.market_sync.services.dto import (
    CandleComparison,
    FeedAssessment,
    InstrumentMatch,
    SyncIssue,
)
from apps.market_sync.services.feed_compatibility import FeedCompatibilityAssessor
from apps.market_sync.services.freshness_validator import FreshnessValidator
from apps.market_sync.services.instrument_matcher import resolve_instrument
from apps.market_sync.services.price_level_comparator import PriceLevelComparator
from apps.market_sync.services.structure_comparator import StructureComparator
from apps.market_sync.services.timeframe_matcher import match_timeframe
from apps.market_sync.services.timestamp_aligner import (
    TimestampAligner,
    last_completed_open,
)

logger = logging.getLogger(__name__)

_COMPLETED_ANALYSIS_STATES = {
    AnalysisStatus.COMPLETED,
    AnalysisStatus.PARTIAL,
    AnalysisStatus.INSUFFICIENT,
}


def _now() -> datetime:
    return timezone.now()


class SynchronizationService:
    """Creates and runs market-synchronization sessions."""

    def __init__(self, *, config: SyncConfig | None = None) -> None:
        self.config = config or SyncConfig.from_settings()
        self.aligner = TimestampAligner()
        self.candle_comparator = CandleComparator(self.config)
        self.structure_comparator = StructureComparator(self.config)
        self.price_comparator = PriceLevelComparator()
        self.feed_assessor = FeedCompatibilityAssessor()
        self.freshness_validator = FreshnessValidator(self.config)

    # -- public API ------------------------------------------------------

    def verify(
        self,
        *,
        analysis,
        profile=None,
        timeframe: str | None = None,
        captured_at: datetime | str | None = None,
        tz_offset_minutes: int | None = None,
        idempotency_key: str | None = None,
        owner=None,
    ) -> MarketSyncSession:
        """Create (or reuse) a session, run the comparison and return it."""
        if analysis is None:
            raise MissingScreenshotAnalysisError("A screenshot analysis is required.")

        if idempotency_key:
            existing = MarketSyncSession.objects.filter(idempotency_key=idempotency_key).first()
            if existing is not None:
                return existing

        session = MarketSyncSession.objects.create(
            owner=owner if owner is not None else getattr(analysis, "owner", None),
            analysis=analysis,
            screenshot=getattr(analysis, "screenshot", None),
            profile=profile,
            config_version=self.config.config_version,
            comparison_method=ComparisonMethod.QUALITATIVE_RELATIVE,
            mt5_timeframe=timeframe or "",
            status=SessionStatus.PENDING,
            idempotency_key=idempotency_key or None,
        )
        session._captured_at_override = captured_at  # type: ignore[attr-defined]
        session._tz_offset_minutes = tz_offset_minutes  # type: ignore[attr-defined]
        return self.run_session(session)

    def run_session(self, session: MarketSyncSession) -> MarketSyncSession:
        """Execute comparison for an already-persisted session."""
        session.status = SessionStatus.RUNNING
        session.started_at = _now()
        session.save(update_fields=["status", "started_at", "updated_at"])
        self._audit(session, AuditKind.STARTED, "Verification started.")

        try:
            self._execute(session)
            session.status = SessionStatus.COMPLETED
        except MissingScreenshotAnalysisError:
            raise
        except Exception as exc:
            logger.exception("Market synchronization failed for session %s", session.pk)
            session.status = SessionStatus.FAILED
            session.error_code = "internal_error"
            session.error_message = str(exc)
            self._audit(
                session,
                AuditKind.ERROR,
                f"Verification failed: {exc}",
                severity=Severity.ERROR,
            )

        session.finished_at = _now()
        session.save(
            update_fields=["status", "error_code", "error_message", "finished_at", "updated_at"]
        )
        return session

    def run_session_by_id(self, session_id: int) -> MarketSyncSession:
        session = MarketSyncSession.objects.get(pk=session_id)
        return self.run_session(session)

    # -- execution -------------------------------------------------------

    def _execute(self, session: MarketSyncSession) -> None:
        analysis = session.analysis
        if analysis is None:
            raise MissingScreenshotAnalysisError("Session has no linked analysis.")

        metadata: dict[str, Any] = analysis.chart_metadata or {}
        result: dict[str, Any] = analysis.result or {}

        issues: list[SyncIssue] = []
        reasons: list[str] = []
        insufficient = False

        # 1) Instrument --------------------------------------------------
        match = resolve_instrument(metadata.get("instrument", ""), profile=session.profile)
        self._apply_instrument(session, match)
        issues.extend(self._instrument_issues(match))
        if not match.supported:
            insufficient = True

        # 2) Timeframe ---------------------------------------------------
        mt5_tf = session.mt5_timeframe or None
        tf_match = match_timeframe(metadata.get("timeframe", ""), mt5_tf)
        effective_tf = mt5_tf or tf_match.screenshot_timeframe
        session.screenshot_timeframe = tf_match.screenshot_timeframe or ""
        if not session.mt5_timeframe and effective_tf:
            session.mt5_timeframe = effective_tf
        self._audit(
            session,
            AuditKind.TIMEFRAME,
            f"Screenshot timeframe={tf_match.screenshot_timeframe}, MT5 timeframe={effective_tf}.",
        )
        reasons.extend(tf_match.reasons)
        issues.extend(self._timeframe_issues(tf_match))
        if tf_match.screenshot_timeframe is None or effective_tf is None or tf_match.mismatch:
            insufficient = True

        # 3) Feed compatibility (OTC protection) -------------------------
        feed = self.feed_assessor.assess(match, metadata_otc_status=metadata.get("otc_status"))
        self._apply_feed(session, feed)
        reasons.extend(feed.reasons)
        issues.extend(self._feed_issues(feed))

        # 4) Screenshot candles ------------------------------------------
        all_candles = [c for c in (result.get("candles") or []) if isinstance(c, dict)]
        completed = [c for c in all_candles if c.get("appears_complete") is not False]
        session.screenshot_candle_count = len(all_candles)
        session.completed_candle_count = len(completed)
        if analysis.status not in _COMPLETED_ANALYSIS_STATES:
            issues.append(
                reporter.issue(
                    reporter.ANALYSIS_INCOMPLETE,
                    Severity.WARNING,
                    "The screenshot analysis has not completed successfully.",
                )
            )
            insufficient = True
        quality = analysis.quality
        if quality == ScreenshotQuality.UNUSABLE:
            issues.append(
                reporter.issue(
                    reporter.SCREENSHOT_UNUSABLE,
                    Severity.ERROR,
                    "The screenshot was marked unusable; comparisons are unreliable.",
                )
            )
            insufficient = True

        if feed.compatibility == FeedCompatibilityStatus.INCOMPATIBLE_FEED:
            # OTC / incompatible: store evidence, but never attempt to verify.
            session.outcome = SyncStatus.INCOMPATIBLE_FEED
            self._finalise(
                session,
                feed=feed,
                candle=None,
                structure=None,
                freshness=None,
                issues=issues,
                reasons=reasons,
                mt5_snapshot={},
                insufficient=True,
                mt5_available=False,
                alignment_uncertain=True,
            )
            self._audit(
                session,
                AuditKind.STATUS,
                "Feed is incompatible; the screenshot remains unverified.",
                severity=Severity.WARNING,
            )
            return

        # 5) MT5 reference series ----------------------------------------
        reference = session.reference_symbol
        mt5_available = False
        latest_open: datetime | None = None
        window: list[MarketCandle] = []
        if reference is not None and effective_tf:
            base_qs = MarketCandle.objects.filter(
                symbol=reference, timeframe=effective_tf, is_complete=True
            )
            latest = base_qs.order_by("-open_time").first()
            mt5_available = latest is not None
            latest_open = latest.open_time if latest is not None else None

        # 6) Anchor + alignment ------------------------------------------
        completed_indices = [int(c.get("index", i)) for i, c in enumerate(completed)]
        anchor, source, confidence, anchor_reasons = self.aligner.resolve_anchor(
            visible_timestamp=metadata.get("screenshot_timestamp"),
            captured_at=getattr(session, "_captured_at_override", None),
            capture_metadata_time=(session.screenshot.metadata or {}).get("captured_at")
            if session.screenshot
            else None,
            tz_offset_minutes=getattr(session, "_tz_offset_minutes", None)
            if getattr(session, "_tz_offset_minutes", None) is not None
            else self.config.default_tz_offset_minutes,
        )
        reasons.extend(anchor_reasons)
        for reason in anchor_reasons:
            issues.append(reporter.issue(reporter.ALIGNMENT_NO_TIMESTAMP, Severity.WARNING, reason))

        alignment = None
        if effective_tf and completed_indices:
            if anchor is not None:
                last_open = last_completed_open(anchor, _step_seconds(effective_tf))
                uncertain = source == AlignmentSource.CAPTURE_METADATA
            elif latest_open is not None:
                last_open = latest_open
                source = AlignmentSource.MT5_LAST_COMPLETED
                confidence = 0.3
                uncertain = True
                note = (
                    "No trustworthy screenshot timestamp; alignment assumed from the latest "
                    "completed MT5 candle and treated as unverified."
                )
                reasons.append(note)
                issues.append(reporter.issue(reporter.ALIGNMENT_UNCERTAIN, Severity.WARNING, note))
            else:
                last_open = None

            if last_open is not None:
                alignment = self.aligner.build_alignment(
                    completed_indices=completed_indices,
                    timeframe=effective_tf,
                    last_open=last_open,
                    source=source,
                    confidence=confidence,
                    uncertain=uncertain,
                    reasons=[],
                )

        session.alignment_anchor = alignment.anchor if alignment else None
        session.alignment_source = alignment.source if alignment else AlignmentSource.NONE
        session.alignment_confidence = alignment.confidence if alignment else None
        session.alignment_uncertain = alignment.uncertain if alignment else True

        if alignment is None or not alignment.mt5_open_times:
            issues.append(
                reporter.issue(
                    reporter.INSUFFICIENT_OVERLAP,
                    Severity.ERROR,
                    "Candles could not be aligned to MT5 intervals.",
                )
            )
            insufficient = True

        # 7) Load the MT5 window -----------------------------------------
        if alignment is not None and alignment.mt5_open_times and reference is not None:
            open_times = list(alignment.mt5_open_times.values())
            window = list(
                MarketCandle.objects.filter(
                    symbol=reference,
                    timeframe=effective_tf,
                    open_time__gte=min(open_times),
                    open_time__lte=max(open_times),
                ).order_by("open_time")
            )
        mt5_by_open = {candle.open_time: candle for candle in window}

        if not mt5_available:
            issues.append(
                reporter.issue(
                    reporter.MT5_NO_DATA,
                    Severity.ERROR,
                    f"No stored MT5 candles exist for {session.mt5_broker_symbol or 'the symbol'}"
                    f"/{effective_tf or '?'}.",
                )
            )

        snapshot = {
            "symbol_id": reference.pk if reference else None,
            "broker_symbol": session.mt5_broker_symbol,
            "timeframe": effective_tf,
            "candle_count": len(window),
            "earliest_open_time": window[0].open_time.isoformat() if window else None,
            "latest_open_time": latest_open.isoformat() if latest_open else None,
            "source": "stored_mt5",
        }

        # 8) Candle + structure comparison -------------------------------
        candle_cmp: CandleComparison | None = None
        structure = None
        if alignment is not None and completed_indices:
            candle_cmp = self.candle_comparator.compare(completed, mt5_by_open, alignment)
            structure = self.structure_comparator.compare(
                result.get("market_structure"),
                window,
                overlap_candles=candle_cmp.aligned_count,
            )
            reasons.extend(candle_cmp.reasons)
            reasons.extend(structure.reasons)
            issues.extend(self._candle_issues(candle_cmp))
            issues.extend(self._structure_issues(structure))

        # 9) Price levels ------------------------------------------------
        price = self.price_comparator.compare(metadata.get("visible_price_labels"), window)
        session.price_comparison_method = price.method
        reasons.extend(price.reasons)
        if price.method == PriceComparisonMethod.NUMERIC_AXIS and price.offset is not None:
            issues.append(
                reporter.issue(
                    reporter.PRICE_OFFSET,
                    Severity.INFO,
                    f"Reported axis offset {price.offset:+.5f}; prices were not shifted.",
                    detail=price.metrics,
                )
            )

        # 10) Freshness --------------------------------------------------
        freshness = self.freshness_validator.assess(
            anchor=alignment.anchor if alignment else None,
            mt5_latest_open=latest_open,
            timeframe=effective_tf,
        )
        session.freshness_status = freshness.status
        reasons.extend(freshness.reasons)
        issues.extend(self._freshness_issues(freshness))

        # 11) Persist + decide -------------------------------------------
        self._finalise(
            session,
            feed=feed,
            candle=candle_cmp,
            structure=structure,
            freshness=freshness,
            issues=issues,
            reasons=reasons,
            mt5_snapshot=snapshot,
            insufficient=insufficient,
            mt5_available=mt5_available,
            alignment_uncertain=session.alignment_uncertain,
        )

        self._persist_alignments(session, candle_cmp)
        self._audit(
            session,
            AuditKind.STATUS,
            f"Outcome: {session.outcome}.",
            detail={"status_message": reporter.status_message(session.outcome)},
        )

    # -- persistence helpers ---------------------------------------------

    def _finalise(
        self,
        session: MarketSyncSession,
        *,
        feed: FeedAssessment,
        candle: CandleComparison | None,
        structure,
        freshness,
        issues: list[SyncIssue],
        reasons: list[str],
        mt5_snapshot: dict,
        insufficient: bool,
        mt5_available: bool,
        alignment_uncertain: bool,
    ) -> None:
        if candle is not None:
            session.aligned_candle_count = candle.aligned_count
            session.matched_candle_count = candle.matched_count
            session.mismatched_candle_count = candle.mismatched_count
            session.unaligned_candle_count = candle.unaligned_count
            session.direction_agreement = candle.direction_agreement
        if structure is not None:
            session.structure_agreement = structure.agreement
        if freshness is not None:
            session.freshness_status = freshness.status

        session.mt5_snapshot = mt5_snapshot
        session.metrics = {
            "candle": {
                "screenshot_candles": session.screenshot_candle_count,
                "completed": session.completed_candle_count,
                "aligned": session.aligned_candle_count,
                "matched": session.matched_candle_count,
                "mismatched": session.mismatched_candle_count,
                "unaligned": session.unaligned_candle_count,
                "direction_agreement": session.direction_agreement,
                "body_agreement": candle.body_agreement if candle else None,
                "wick_agreement": candle.wick_agreement if candle else None,
                "size_sequence_agreement": (
                    candle.metrics.get("size_sequence_agreement") if candle else None
                ),
            },
            "structure": structure.metrics if structure else {},
            "feed": feed.evidence,
        }
        session.reasons = _dedupe(reasons)

        if session.outcome in ("", None):
            session.outcome = reporter.decide_status(
                feed=feed,
                mt5_available=mt5_available,
                insufficient_information=insufficient,
                alignment_uncertain=alignment_uncertain,
                freshness=freshness if freshness is not None else _unknown_freshness(),
                candle=candle if candle is not None else _empty_candle_comparison(),
                structure=structure if structure is not None else _insufficient_structure(),
                config=self.config,
            )

        session.save()

        # Derived rows are recreated per run for a clean, auditable record.
        session.issues.all().delete()
        MarketSyncIssue.objects.bulk_create(
            [
                MarketSyncIssue(
                    session=session,
                    code=item.code,
                    severity=item.severity,
                    message=item.message[:400],
                    candle_index=item.candle_index,
                    detail=item.detail,
                )
                for item in issues
            ]
        )

        FeedCompatibilityAssessment.objects.update_or_create(
            session=session,
            defaults={
                "screenshot_instrument": session.screenshot_instrument,
                "canonical_instrument": session.canonical_instrument,
                "mt5_broker_symbol": session.mt5_broker_symbol,
                "broker": session.broker,
                "market_type": session.market_type,
                "mapping_source": session.mapping_source,
                "mapping_verification": session.mapping_status,
                "mapping_verified": session.mapping_verified,
                "screenshot_is_otc": feed.screenshot_is_otc,
                "reference_is_otc": feed.reference_is_otc,
                "compatibility": feed.compatibility,
                "reasons": list(feed.reasons),
                "evidence": feed.evidence,
            },
        )

    def _persist_alignments(self, session: MarketSyncSession, candle: CandleComparison | None):
        if candle is None:
            return
        session.alignments.all().delete()
        CandleAlignment.objects.bulk_create(
            [
                CandleAlignment(
                    session=session,
                    screenshot_index=record.screenshot_index,
                    screenshot_classification=record.screenshot_classification,
                    screenshot_body_size=record.screenshot_body_size,
                    screenshot_upper_wick=record.screenshot_upper_wick,
                    screenshot_lower_wick=record.screenshot_lower_wick,
                    screenshot_position=record.screenshot_position,
                    mt5_candle_id=record.mt5_candle_id,
                    mt5_open_time=record.mt5_open_time,
                    mt5_direction=record.mt5_direction or "",
                    mt5_body_ratio=record.mt5_body_ratio,
                    mt5_upper_wick_ratio=record.mt5_upper_wick_ratio,
                    mt5_lower_wick_ratio=record.mt5_lower_wick_ratio,
                    match_result=record.match_result,
                    direction_match=record.direction_match,
                    body_match=record.body_match,
                    wick_match=record.wick_match,
                    local_extreme_match=record.local_extreme_match,
                    confidence=record.confidence,
                    limitations=list(record.limitations),
                    evidence=record.evidence,
                )
                for record in candle.alignments
            ]
        )

    # -- field application -----------------------------------------------

    @staticmethod
    def _apply_instrument(session: MarketSyncSession, match: InstrumentMatch) -> None:
        session.screenshot_instrument = match.screenshot_instrument[:64]
        session.canonical_instrument = match.canonical_instrument[:24]
        session.mt5_broker_symbol = match.broker_symbol[:64]
        session.reference_symbol_id = match.reference_id
        session.broker = match.broker[:120]
        session.market_type = match.market_type[:16]
        session.mapping_source = match.mapping_source
        session.mapping_status = match.mapping_status[:16]
        session.mapping_verified = match.mapping_verified

    @staticmethod
    def _apply_feed(session: MarketSyncSession, feed: FeedAssessment) -> None:
        session.feed_compatibility = feed.compatibility

    # -- issue builders --------------------------------------------------

    @staticmethod
    def _instrument_issues(match: InstrumentMatch) -> list[SyncIssue]:
        issues: list[SyncIssue] = []
        if match.ambiguous:
            issues.append(
                reporter.issue(reporter.AMBIGUOUS_MAPPING, Severity.ERROR, "; ".join(match.reasons))
            )
            return issues
        if not match.supported:
            code = (
                reporter.MISSING_INSTRUMENT
                if match.screenshot_instrument.strip().upper() in {"", "UNKNOWN", "UNREADABLE"}
                else reporter.UNSUPPORTED_INSTRUMENT
            )
            for reason in match.reasons:
                issues.append(reporter.issue(code, Severity.ERROR, reason))
            return issues
        if not match.mapping_verified:
            for reason in match.reasons:
                issues.append(reporter.issue(reporter.MAPPING_UNVERIFIED, Severity.WARNING, reason))
        return issues

    @staticmethod
    def _timeframe_issues(tf_match) -> list[SyncIssue]:
        issues: list[SyncIssue] = []
        if tf_match.screenshot_timeframe is None:
            issues.append(
                reporter.issue(
                    reporter.MISSING_TIMEFRAME,
                    Severity.ERROR,
                    "Screenshot timeframe is missing or unreadable.",
                )
            )
        if tf_match.mismatch:
            issues.append(
                reporter.issue(
                    reporter.TIMEFRAME_MISMATCH, Severity.ERROR, "; ".join(tf_match.reasons)
                )
            )
        return issues

    @staticmethod
    def _feed_issues(feed: FeedAssessment) -> list[SyncIssue]:
        issues: list[SyncIssue] = []
        if feed.compatibility == FeedCompatibilityStatus.INCOMPATIBLE_FEED:
            issues.append(
                reporter.issue(
                    reporter.OTC_INCOMPATIBLE, Severity.CRITICAL, "; ".join(feed.reasons)
                )
            )
        elif feed.compatibility == FeedCompatibilityStatus.UNKNOWN:
            issues.append(
                reporter.issue(reporter.FEED_UNKNOWN, Severity.WARNING, "; ".join(feed.reasons))
            )
        return issues

    @staticmethod
    def _candle_issues(candle: CandleComparison) -> list[SyncIssue]:
        issues: list[SyncIssue] = []
        for record in candle.alignments:
            if record.match_result == CandleMatch.MISMATCHED and record.direction_match is False:
                issues.append(
                    reporter.issue(
                        reporter.CANDLE_DIRECTION_MISMATCH,
                        Severity.WARNING,
                        "Screenshot candle direction disagrees with MT5.",
                        candle_index=record.screenshot_index,
                        detail={
                            "mt5_direction": record.mt5_direction,
                            "screenshot": record.screenshot_classification,
                        },
                    )
                )
        for reason in candle.reasons:
            issues.append(reporter.issue(reporter.COMPARISON_LIMITED, Severity.INFO, reason))
        return issues

    @staticmethod
    def _structure_issues(structure) -> list[SyncIssue]:
        if structure is None:
            return []
        if structure.agreement == StructureAgreement.DISAGREE:
            return [
                reporter.issue(
                    reporter.CANDLE_STRUCTURE_MISMATCH,
                    Severity.ERROR,
                    "; ".join(structure.reasons)
                    or "Market structure disagrees between the screenshot and MT5.",
                )
            ]
        return []

    @staticmethod
    def _freshness_issues(freshness) -> list[SyncIssue]:
        issues: list[SyncIssue] = []
        if freshness.status == FreshnessStatus.STALE_SCREENSHOT:
            issues.append(
                reporter.issue(
                    reporter.STALE_SCREENSHOT, Severity.WARNING, "; ".join(freshness.reasons)
                )
            )
        elif freshness.status == FreshnessStatus.STALE_MT5:
            issues.append(
                reporter.issue(reporter.STALE_MT5, Severity.WARNING, "; ".join(freshness.reasons))
            )
        if freshness.entry_window_expired:
            issues.append(
                reporter.issue(
                    reporter.ENTRY_WINDOW_EXPIRED,
                    Severity.WARNING,
                    "The screenshot predates the current candle; a next-candle signal would not "
                    "be actionable.",
                )
            )
        return issues

    # -- audit -----------------------------------------------------------

    @staticmethod
    def _audit(
        session: MarketSyncSession,
        kind: str,
        message: str,
        *,
        severity: str = Severity.INFO,
        detail: dict | None = None,
    ) -> None:
        SynchronizationAuditLog.objects.create(
            session=session,
            kind=kind,
            severity=severity,
            message=message[:400],
            detail=detail or {},
            occurred_at=timezone.now(),
        )


# -- module-level helpers ------------------------------------------------


def _step_seconds(timeframe: str) -> int:
    from apps.market_data.services.timeframe_mapper import duration_seconds

    return duration_seconds(timeframe)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _unknown_freshness():
    from apps.market_sync.services.dto import FreshnessAssessment

    return FreshnessAssessment(
        status=FreshnessStatus.UNKNOWN,
        screenshot_age_seconds=None,
        mt5_age_seconds=None,
        entry_window_expired=False,
    )


def _empty_candle_comparison():
    from apps.market_sync.services.dto import CandleComparison

    return CandleComparison(
        alignments=[],
        aligned_count=0,
        matched_count=0,
        mismatched_count=0,
        insufficient_count=0,
        unaligned_count=0,
        direction_agreement=None,
        body_agreement=None,
        wick_agreement=None,
    )


def _insufficient_structure():
    from apps.chart_vision.constants import Trend
    from apps.market_sync.constants import StructureAgreement
    from apps.market_sync.services.dto import StructureComparison

    return StructureComparison(
        agreement=StructureAgreement.INSUFFICIENT,
        screenshot_trend=Trend.UNCLEAR,
        mt5_trend=Trend.UNCLEAR,
        comparable_items=0,
        agreeing_items=0,
    )


def verify_alignment(analysis, **kwargs) -> MarketSyncSession:
    """Convenience entry point used by views/tasks."""
    return SynchronizationService().verify(analysis=analysis, **kwargs)


__all__ = ["SynchronizationService", "verify_alignment"]
