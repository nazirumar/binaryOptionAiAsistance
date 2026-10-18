"""End-to-end tests for :class:`SynchronizationService` (Steps 3-13).

Deterministic and DB-only: the service reads the stored Phase 3 analysis and the
stored Phase 2 candles, so no MT5 terminal or network is involved.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.test import TestCase

from apps.chart_vision.constants import AnalysisStatus
from apps.market_data.constants import MappingStatus
from apps.market_sync.constants import (
    CandleMatch,
    FeedCompatibilityStatus,
    FreshnessStatus,
    SessionStatus,
    StructureAgreement,
    SyncStatus,
)
from apps.market_sync.models import (
    CandleAlignment,
    FeedCompatibilityAssessment,
    MarketSyncIssue,
    MarketSyncSession,
    SynchronizationAuditLog,
)
from apps.market_sync.services.synchronization_service import (
    SynchronizationService,
    verify_alignment,
)
from tests.factories import UserFactory
from tests.sync_fakes import build_aligned_scenario, uptrend_structure


class SyncServiceFixtureMixin:
    def setUp(self):
        super().setUp()
        self.user = UserFactory(username="sync-owner")
        self.service = SynchronizationService()

    def _downtrend_structure(self) -> dict:
        structure = uptrend_structure()
        structure.update(
            {
                "trend": "downtrend",
                "higher_highs": False,
                "higher_lows": False,
                "lower_highs": True,
                "lower_lows": True,
            }
        )
        return structure


class VerifiedAlignmentTests(SyncServiceFixtureMixin, TestCase):
    def test_full_alignment_is_verified(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user)

        session = self.service.verify(analysis=analysis, owner=self.user)
        session.refresh_from_db()

        assert session.status == SessionStatus.COMPLETED
        assert session.outcome == SyncStatus.VERIFIED_ALIGNMENT
        assert session.is_verified is True
        assert session.is_complete is True
        assert session.mapping_verified is True
        assert session.mt5_broker_symbol == "EURUSD"
        assert session.screenshot_timeframe == "M1"
        assert session.mt5_timeframe == "M1"
        assert session.direction_agreement == 1.0
        assert session.structure_agreement == StructureAgreement.AGREE
        assert session.feed_compatibility == FeedCompatibilityStatus.COMPATIBLE
        assert session.freshness_status == FreshnessStatus.FRESH
        assert session.aligned_candle_count == 12
        assert session.matched_candle_count == 12
        assert session.alignment_uncertain is False

    def test_derived_rows_are_persisted(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user)
        session = self.service.verify(analysis=analysis, owner=self.user)

        assert CandleAlignment.objects.filter(session=session).count() == 12
        assessment = FeedCompatibilityAssessment.objects.get(session=session)
        assert assessment.compatibility == FeedCompatibilityStatus.COMPATIBLE
        assert assessment.mapping_verified is True
        assert SynchronizationAuditLog.objects.filter(session=session).exists()
        # Rightmost (incomplete) screenshot candle must never be persisted.
        assert not CandleAlignment.objects.filter(session=session, screenshot_index=12).exists()

    def test_verified_alignment_is_only_successful_status(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user)
        session = self.service.verify(analysis=analysis, owner=self.user)
        assert session.is_verified


class MismatchTests(SyncServiceFixtureMixin, TestCase):
    def test_direction_and_structure_disagreement_is_mismatch(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(
            self.user,
            flip_direction=True,
            structure=self._downtrend_structure(),
        )
        session = self.service.verify(analysis=analysis, owner=self.user)
        session.refresh_from_db()

        assert session.outcome == SyncStatus.DATA_MISMATCH
        assert session.is_verified is False
        assert session.direction_agreement == 0.0
        assert session.structure_agreement == StructureAgreement.DISAGREE
        assert MarketSyncIssue.objects.filter(
            session=session, code="candle_direction_mismatch"
        ).exists()

    def test_direction_disagreement_only_is_partial(self):
        # Directions flipped, but the (structural) trends still agree.
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user, flip_direction=True)
        session = self.service.verify(analysis=analysis, owner=self.user)

        assert session.outcome == SyncStatus.PARTIAL_ALIGNMENT
        assert session.is_verified is False

    def test_unverified_mapping_prevents_full_verification(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(
            self.user, mapping_status=MappingStatus.UNKNOWN
        )
        session = self.service.verify(analysis=analysis, owner=self.user)

        assert session.mapping_verified is False
        assert session.outcome == SyncStatus.PARTIAL_ALIGNMENT
        assert MarketSyncIssue.objects.filter(session=session, code="mapping_unverified").exists()


class FeedCompatibilityTests(SyncServiceFixtureMixin, TestCase):
    def test_otc_screenshot_with_regular_reference_is_incompatible(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(
            self.user, instrument="EURUSD-OTC", otc_status="otc"
        )
        session = self.service.verify(analysis=analysis, owner=self.user)
        session.refresh_from_db()

        assert session.outcome == SyncStatus.INCOMPATIBLE_FEED
        assert session.feed_compatibility == FeedCompatibilityStatus.INCOMPATIBLE_FEED
        assert session.is_verified is False
        # No candle comparison is attempted for an incompatible feed.
        assert CandleAlignment.objects.filter(session=session).count() == 0
        assert MarketSyncIssue.objects.filter(session=session, code="otc_incompatible").exists()

    def test_otc_with_verified_otc_reference_is_compatible(self):
        # Explicit broker mapping EURUSD-OTC -> EURUSD_OTC (is_otc=True, VALID).
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(
            self.user,
            instrument="EURUSD-OTC",
            otc_status="otc",
            broker_symbol="EURUSD_OTC",
            canonical="EURUSD_OTC",
            is_otc_mapping=True,
        )
        session = self.service.verify(analysis=analysis, owner=self.user)

        assert session.feed_compatibility == FeedCompatibilityStatus.COMPATIBLE
        assert session.outcome == SyncStatus.VERIFIED_ALIGNMENT


class TimeframeTests(SyncServiceFixtureMixin, TestCase):
    def test_missing_timeframe_is_insufficient(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(
            self.user, timeframe="UNKNOWN", make_mt5=False
        )
        session = self.service.verify(analysis=analysis, owner=self.user)

        assert session.outcome == SyncStatus.INSUFFICIENT_INFORMATION
        assert MarketSyncIssue.objects.filter(session=session, code="missing_timeframe").exists()

    def test_explicit_timeframe_mismatch_is_insufficient(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user)
        # The screenshot says M1 but we ask for M5: not comparable.
        session = self.service.verify(analysis=analysis, owner=self.user, timeframe="M5")

        assert session.outcome == SyncStatus.INSUFFICIENT_INFORMATION
        assert MarketSyncIssue.objects.filter(session=session, code="timeframe_mismatch").exists()


class Mt5AvailabilityTests(SyncServiceFixtureMixin, TestCase):
    def test_missing_mt5_series_is_unavailable(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user, make_mt5=False)
        session = self.service.verify(analysis=analysis, owner=self.user)
        session.refresh_from_db()

        assert session.outcome == SyncStatus.MT5_UNAVAILABLE
        assert MarketSyncIssue.objects.filter(session=session, code="mt5_no_data").exists()


class StalenessTests(SyncServiceFixtureMixin, TestCase):
    def test_stale_screenshot_is_stale_data(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user, shift_minutes=120)
        session = self.service.verify(analysis=analysis, owner=self.user)

        assert session.outcome == SyncStatus.STALE_DATA
        assert session.freshness_status == FreshnessStatus.STALE_SCREENSHOT
        assert session.is_verified is False


class EvidencePreservationTests(SyncServiceFixtureMixin, TestCase):
    def test_snapshot_and_config_are_recorded(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user)
        session = self.service.verify(analysis=analysis, owner=self.user)

        assert session.config_version == self.service.config.config_version
        assert session.mt5_snapshot["broker_symbol"] == "EURUSD"
        assert session.mt5_snapshot["candle_count"] == 12
        assert session.metrics["candle"]["completed"] == 12
        assert session.reasons

    def test_analysis_result_is_never_mutated(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user)
        before = analysis.result
        self.service.verify(analysis=analysis, owner=self.user)
        analysis.refresh_from_db()
        assert analysis.result == before


class IdempotencyTests(SyncServiceFixtureMixin, TestCase):
    def test_duplicate_key_returns_existing_session(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user)
        first = self.service.verify(analysis=analysis, owner=self.user, idempotency_key="dup-key")
        second = self.service.verify(analysis=analysis, owner=self.user, idempotency_key="dup-key")

        assert first.pk == second.pk
        assert MarketSyncSession.objects.filter(idempotency_key="dup-key").count() == 1

    def test_user_provided_capture_time_is_used(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(
            self.user, with_timestamp=False, make_mt5=False
        )
        session = self.service.verify(
            analysis=analysis,
            owner=self.user,
            captured_at="2026-01-05T12:00:00Z",
        )
        assert session.alignment_source == "user_provided"
        # The alignment anchor is the last candle that had fully closed at the
        # capture time (12:00 -> the 11:59 M1 candle).
        assert session.alignment_anchor == datetime(2026, 1, 5, 11, 59, tzinfo=UTC)


class FailureTests(SyncServiceFixtureMixin, TestCase):
    def test_missing_analysis_raises(self):
        from apps.market_sync.exceptions import MissingScreenshotAnalysisError

        with pytest.raises(MissingScreenshotAnalysisError):
            self.service.verify(analysis=None, owner=self.user)

    def test_internal_error_marks_session_failed(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user)
        session = MarketSyncSession.objects.create(
            owner=self.user, analysis=analysis, screenshot=analysis.screenshot
        )

        def boom(_session):
            raise RuntimeError("kaboom")

        self.service._execute = boom  # type: ignore[assignment]
        result = self.service.run_session(session)
        result.refresh_from_db()

        assert result.status == SessionStatus.FAILED
        assert result.error_code == "internal_error"
        assert SynchronizationAuditLog.objects.filter(session=result, kind="error").exists()

    def test_reanalysis_analysis_status_not_completed_is_insufficient(self):
        _symbol, _prices, _analysis, _anchor = build_aligned_scenario(self.user, make_mt5=False)
        # Overwrite the analysis status to FAILED (not a completed state).
        _analysis.status = AnalysisStatus.FAILED
        _analysis.save(update_fields=["status"])
        session = self.service.verify(analysis=_analysis, owner=self.user)
        assert (
            MarketSyncIssue.objects.filter(session=session, code="analysis_incomplete").exists()
            or session.outcome == SyncStatus.INSUFFICIENT_INFORMATION
        )


class ConvenienceEntryTests(SyncServiceFixtureMixin, TestCase):
    def test_verify_alignment_helper(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user)
        session = verify_alignment(analysis, owner=self.user)
        assert session.outcome == SyncStatus.VERIFIED_ALIGNMENT
        assert session.config_version


class FlippedCandleMatchTests(SyncServiceFixtureMixin, TestCase):
    def test_flipped_persisted_alignment_is_mismatched(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user, flip_direction=True)
        session = self.service.verify(analysis=analysis, owner=self.user)
        record = CandleAlignment.objects.filter(session=session).first()
        assert record is not None
        assert record.match_result == CandleMatch.MISMATCHED
        assert record.direction_match is False


class DeterminismTests(SyncServiceFixtureMixin, TestCase):
    def test_repeated_runs_are_deterministic(self):
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(self.user)
        first = self.service.verify(analysis=analysis, owner=self.user)
        second = self.service.verify(analysis=analysis, owner=self.user)
        assert first.outcome == second.outcome
        assert first.direction_agreement == second.direction_agreement
