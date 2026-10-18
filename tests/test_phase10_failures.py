"""Phase 10: critical failure-scenario tests (fail-closed behaviour).

Every test documents that when a dependency breaks or an input cannot be
trusted, the system surfaces a typed error or produces an explicit NO TRADE
decision — it never fabricates a prediction, price, probability or explanation.

All tests are hermetic: MT5, vision/reasoning LLMs, Redis and Celery workers are
faked or mocked; the database is the in-memory SQLite test database.
"""

from __future__ import annotations

import email.message
import urllib.error
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.db import OperationalError
from django.test import Client, override_settings
from django.urls import reverse

from apps.ai_assistant.services.analysis_orchestrator import AnalysisOrchestrator
from apps.ai_assistant.services.assistant_service import AssistantService
from apps.ai_assistant.services.conversation_manager import ConversationManager
from apps.ai_assistant.services.probability_presenter import ProbabilityPresenter
from apps.ai_assistant.services.reasoning_provider import ReasoningProvider, ReasoningRequest
from apps.ai_assistant.services.response_validator import ResponseValidator
from apps.chart_vision.constants import AnalysisStatus, EventKind
from apps.chart_vision.models import ChartScreenshot, ScreenshotAnalysis
from apps.chart_vision.services.exceptions import (
    CorruptedImageError,
    SchemaValidationError,
    UnsupportedImageFormatError,
    VisionProviderUnavailableError,
    VisionRateLimitError,
    VisionTimeoutError,
)
from apps.chart_vision.services.image_validator import validate_image
from apps.chart_vision.services.screenshot_analyzer import (
    ScreenshotAnalyzer,
    get_or_create_analysis,
)
from apps.chart_vision.services.vision_provider import (
    OpenAICompatibleVisionProvider,
    ProviderConfig,
    VisionProvider,
)
from apps.dashboard.services.performance_service import ProbabilityAnalytics
from apps.market_data.services.connection_manager import ConnectionConfig, MT5ConnectionManager
from apps.market_data.services.exceptions import MT5ConnectionError
from apps.market_sync.constants import (
    FeedCompatibilityStatus,
    FreshnessStatus,
    SyncStatus,
)
from apps.market_sync.models import (
    CandleAlignment,
    FeedCompatibilityAssessment,
    MarketSyncIssue,
    MarketSyncSession,
)
from apps.market_sync.services.freshness_validator import validate_freshness
from apps.market_sync.services.synchronization_service import SynchronizationService
from apps.price_action.constants import ConflictType, Direction
from apps.price_action.services.conflict_detector import detect_conflicts
from apps.price_action.services.evidence_registry import Evidence
from apps.strategy_engine.constants import (
    EvaluationDirection,
    InvalidationReasonCode,
    ProbabilityStatus,
    TimingValidity,
)
from apps.strategy_engine.services.evaluation_service import EvaluationService
from apps.strategy_engine.services.timing_validator import TimingValidator
from apps.trading_journal.models import JournalTrade
from apps.trading_journal.services.journal_performance import INSUFFICIENT_DATA, JournalPerformance
from tests.factories import UserFactory
from tests.marketdata_fakes import FakeMT5Gateway
from tests.sync_fakes import build_aligned_scenario, make_symbol
from tests.vision_fakes import (
    StaticVisionProvider,
    full_payload,
    make_screenshot,
    png_bytes,
    uploaded_file,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Keep DRF's locmem throttle cache from leaking across tests."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _eval_candles(*, count: int = 6, final_complete: bool = True) -> list[dict]:
    candles = []
    for index in range(count):
        open_px = 1.1000 + index * 0.0002
        close_px = open_px + 0.0003
        candles.append(
            {
                "open": round(open_px, 5),
                "high": round(close_px + 0.0002, 5),
                "low": round(open_px - 0.0002, 5),
                "close": round(close_px, 5),
                "complete": True,
            }
        )
    if not final_complete:
        candles[-1]["complete"] = False
    return candles


def _eval_input(**overrides) -> dict:
    base = {
        "instrument": "EURUSD",
        "timeframe": "M1",
        "market_type": "regular",
        "sync_status": "verified_alignment",
        "candles": _eval_candles(),
        "price_action_result": {"evidence": [], "conflicts": [], "context": {}},
    }
    base.update(overrides)
    return base


def _provider_config(**overrides) -> ProviderConfig:
    values = {
        "provider": "openai",
        "model": "gpt-4o",
        "api_key": "sk-test",
        "base_url": "https://api.example.test/v1",
        "timeout_seconds": 1,
        "max_retries": 0,
        "backoff_seconds": 0.0,
        "max_tokens": 64,
        "temperature": 0.0,
    }
    values.update(overrides)
    return ProviderConfig(**values)


def _http_error(code: int, headers=None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.example.test/v1/chat/completions", code, "error", headers or {}, None
    )


def _retry_after_headers(value: str) -> email.message.Message:
    headers = email.message.Message()
    headers["Retry-After"] = value
    return headers


class _AlwaysFailingVisionProvider(VisionProvider):
    """Raises a fixed error on every call; counts calls for retry assertions."""

    name = "failing"

    def __init__(self, error: Exception, *, max_retries: int = 0) -> None:
        super().__init__(
            ProviderConfig(
                provider="failing",
                model="failing-1",
                api_key="",
                base_url="",
                timeout_seconds=1,
                max_retries=max_retries,
                backoff_seconds=0.0,
                max_tokens=64,
                temperature=0.0,
            )
        )
        self.error = error
        self.calls = 0

    def analyze(self, *, image_bytes: bytes, mime_type: str, prompt: str):
        self.calls += 1
        raise self.error


def _journal_trade(owner, **overrides) -> JournalTrade:
    values = {
        "owner": owner,
        "instrument": "EUR/USD",
        "direction": "call",
        "entry_timestamp": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        "stake": Decimal("10"),
        "payout_percent": Decimal("80"),
        "result": "win",
    }
    values.update(overrides)
    return JournalTrade.objects.create(**values)


# ---------------------------------------------------------------------------
# 1. MT5 disconnected / unavailable -> fail closed, never fabricate
# ---------------------------------------------------------------------------
class TestMt5UnavailableFailsClosed:
    def test_missing_mt5_series_is_reported_unavailable(self):
        user = UserFactory(username="phase10-mt5-missing")
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(user, make_mt5=False)
        session = SynchronizationService().verify(analysis=analysis, owner=user)
        session.refresh_from_db()

        assert session.outcome == SyncStatus.MT5_UNAVAILABLE
        assert session.is_verified is False
        assert MarketSyncIssue.objects.filter(session=session, code="mt5_no_data").exists()

    def test_connection_failure_raises_and_stays_disconnected(self):
        gateway = FakeMT5Gateway(connect=[False, False, False], error=(-1, "connection failed"))
        slept: list[float] = []
        manager = MT5ConnectionManager(
            gateway,
            ConnectionConfig(path="", login=0, password="", server="Broker-Demo", timeout_ms=1000),
            max_retries=2,
            backoff_seconds=0.5,
            backoff_max_seconds=30.0,
            sleep=slept.append,
        )
        with pytest.raises(MT5ConnectionError):
            manager.connect()
        assert manager.is_connected is False
        assert manager.health_check().connected is False

    def test_unverified_sync_produces_no_trade_not_a_prediction(self):
        result = EvaluationService().evaluate(_eval_input(sync_status="unverified"))
        assert result["direction"] == EvaluationDirection.NO_TRADE
        assert InvalidationReasonCode.INCOMPATIBLE_SYNC in result["reason_codes"]


# ---------------------------------------------------------------------------
# 2. MT5 / screenshot stale data -> freshness guard triggers
# ---------------------------------------------------------------------------
class TestStaleDataGuard:
    def test_stale_mt5_feed_triggers_freshness_guard(self):
        now = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
        assessment = validate_freshness(
            anchor=now - timedelta(seconds=30),
            mt5_latest_open=now - timedelta(minutes=30),
            timeframe="M1",
            now=now,
        )
        assert assessment.status == FreshnessStatus.STALE_MT5
        assert assessment.mt5_age_seconds is not None and assessment.mt5_age_seconds > 900
        assert any("stale" in reason.lower() for reason in assessment.reasons)

    def test_expired_entry_window_is_flagged(self):
        now = datetime(2026, 1, 5, 12, 5, tzinfo=UTC)
        assessment = validate_freshness(
            anchor=now - timedelta(seconds=180),
            mt5_latest_open=None,
            timeframe="M1",
            now=now,
        )
        assert assessment.entry_window_expired is True
        assert any("no longer be actionable" in reason for reason in assessment.reasons)

    def test_stale_screenshot_session_is_marked_stale(self):
        user = UserFactory(username="phase10-stale-shot")
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(user, shift_minutes=120)
        session = SynchronizationService().verify(analysis=analysis, owner=user)
        session.refresh_from_db()

        assert session.outcome == SyncStatus.STALE_DATA
        assert session.freshness_status == FreshnessStatus.STALE_SCREENSHOT
        assert session.is_verified is False
        assert MarketSyncIssue.objects.filter(session=session, code="stale_screenshot").exists()


# ---------------------------------------------------------------------------
# 3. OTC feed incompatibility -> refused, never substituted with regular prices
# ---------------------------------------------------------------------------
class TestOtcFeedIncompatibility:
    def test_otc_screenshot_never_verified_against_regular_feed(self):
        user = UserFactory(username="phase10-otc-refused")
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(
            user, instrument="EURUSD-OTC", otc_status="otc"
        )
        session = SynchronizationService().verify(analysis=analysis, owner=user)
        session.refresh_from_db()

        assert session.outcome == SyncStatus.INCOMPATIBLE_FEED
        assert session.feed_compatibility == FeedCompatibilityStatus.INCOMPATIBLE_FEED
        assert session.is_verified is False
        # Regular forex prices are never substituted: no candle was compared.
        assert CandleAlignment.objects.filter(session=session).count() == 0
        issue = MarketSyncIssue.objects.get(session=session, code="otc_incompatible")
        assert issue.severity == "critical"
        assessment = FeedCompatibilityAssessment.objects.get(session=session)
        assert assessment.screenshot_is_otc is True
        assert assessment.evidence.get("otc_reference_verified") is False

    def test_regular_screenshot_against_otc_mapping_is_incompatible(self):
        user = UserFactory(username="phase10-regular-vs-otc")
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(user, is_otc_mapping=True)
        session = SynchronizationService().verify(analysis=analysis, owner=user)
        session.refresh_from_db()

        assert session.outcome == SyncStatus.INCOMPATIBLE_FEED
        assert session.feed_compatibility == FeedCompatibilityStatus.INCOMPATIBLE_FEED
        assert session.is_verified is False

    def test_orchestrator_refuses_otc_without_verified_alignment(self):
        result = AnalysisOrchestrator().run(
            None, evaluation_input=_eval_input(market_type="OTC", sync_status="unverified")
        )
        assert result["direction"] == "NO TRADE"
        assert "otc_feed_incompatible" in result["warnings"]
        assert result["primary_reason_code"] == "otc_feed_incompatible"
        assert result["probability_value"] is None
        assert result["supporting_evidence"] == []


# ---------------------------------------------------------------------------
# 4. Screenshot symbol mismatch -> reported, no false alignment
# ---------------------------------------------------------------------------
class TestScreenshotSymbolMismatch:
    def test_unmapped_instrument_is_never_aligned_to_a_symbol(self):
        user = UserFactory(username="phase10-fake-symbol")
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(user, instrument="FAKESYMX")
        session = SynchronizationService().verify(analysis=analysis, owner=user)
        session.refresh_from_db()

        assert session.outcome == SyncStatus.INSUFFICIENT_INFORMATION
        assert session.is_verified is False
        assert session.mt5_broker_symbol == ""
        assert session.canonical_instrument == ""
        assert MarketSyncIssue.objects.filter(
            session=session, code="unsupported_instrument"
        ).exists()

    def test_ambiguous_mapping_is_rejected_not_guessed(self):
        user = UserFactory(username="phase10-ambiguous")
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)
        # A second active mapping with the same broker symbol makes the match ambiguous.
        make_symbol(canonical="EURGBP", broker_symbol="EURUSD")
        session = SynchronizationService().verify(analysis=analysis, owner=user)
        session.refresh_from_db()

        assert session.outcome == SyncStatus.INSUFFICIENT_INFORMATION
        assert session.is_verified is False
        assert MarketSyncIssue.objects.filter(session=session, code="ambiguous_mapping").exists()


# ---------------------------------------------------------------------------
# 5. Screenshot timeframe mismatch -> reported, not silently reconciled
# ---------------------------------------------------------------------------
class TestScreenshotTimeframeMismatch:
    def test_mismatched_timeframe_is_reported_not_aligned(self):
        user = UserFactory(username="phase10-tf-mismatch")
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)
        session = SynchronizationService().verify(analysis=analysis, owner=user, timeframe="M5")
        session.refresh_from_db()

        assert session.outcome == SyncStatus.INSUFFICIENT_INFORMATION
        assert session.is_verified is False
        assert session.screenshot_timeframe == "M1"
        assert session.mt5_timeframe == "M5"
        assert MarketSyncIssue.objects.filter(session=session, code="timeframe_mismatch").exists()

    def test_unreadable_timeframe_is_not_guessed(self):
        user = UserFactory(username="phase10-tf-unknown")
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(
            user, timeframe="UNKNOWN", make_mt5=False
        )
        session = SynchronizationService().verify(analysis=analysis, owner=user)
        assert session.outcome == SyncStatus.INSUFFICIENT_INFORMATION
        assert MarketSyncIssue.objects.filter(session=session, code="missing_timeframe").exists()


# ---------------------------------------------------------------------------
# 6. Unreadable / corrupt screenshot -> rejected cleanly
# ---------------------------------------------------------------------------
class TestUnreadableScreenshotRejected:
    def test_truncated_png_is_rejected(self):
        with pytest.raises(CorruptedImageError):
            validate_image(png_bytes()[:32])

    def test_empty_upload_is_rejected(self):
        with pytest.raises(CorruptedImageError):
            validate_image(b"")

    def test_non_image_bytes_are_rejected(self):
        with pytest.raises(UnsupportedImageFormatError):
            validate_image(b"%PDF-1.4 this is not an image")

    def test_upload_endpoint_rejects_corrupt_file_without_persisting(self):
        user = UserFactory(username="phase10-corrupt-upload")
        client = Client()
        client.force_login(user)
        response = client.post(
            reverse("chart_vision:screenshots"),
            {"image": uploaded_file(png_bytes()[:32])},
            format="multipart",
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == "image_corrupted"
        # Nothing was persisted: no screenshot row, no analysis row.
        assert ChartScreenshot.objects.count() == 0
        assert ScreenshotAnalysis.objects.count() == 0


# ---------------------------------------------------------------------------
# 7. Incomplete rightmost candle -> handled explicitly
# ---------------------------------------------------------------------------
class TestIncompleteRightmostCandle:
    def test_rightmost_candle_is_downgraded_even_when_provider_claims_complete(self):
        payload = full_payload()
        assert payload["candles"][-1]["appears_complete"] is True
        user = UserFactory(username="phase10-rightmost")
        screenshot = make_screenshot(user)
        analysis, _created = get_or_create_analysis(screenshot)
        ScreenshotAnalyzer(provider=StaticVisionProvider(payload=payload)).analyze(
            screenshot, analysis
        )
        analysis.refresh_from_db()

        last = analysis.result["candles"][-1]
        assert last["appears_complete"] is False
        assert last["provider_claimed_complete"] is True
        assert any("incomplete" in warning.lower() for warning in analysis.warnings)

    def test_incomplete_rightmost_candle_is_never_compared_to_mt5(self):
        user = UserFactory(username="phase10-rightmost-sync")
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)
        session = SynchronizationService().verify(analysis=analysis, owner=user)

        # 13 screenshot candles, but only the 12 completed ones are compared.
        assert session.screenshot_candle_count == 13
        assert session.completed_candle_count == 12
        assert not CandleAlignment.objects.filter(session=session, screenshot_index=12).exists()

    def test_unfinished_signal_candle_forces_no_trade(self):
        result = EvaluationService().evaluate(
            _eval_input(candles=_eval_candles(final_complete=False))
        )
        assert result["direction"] == EvaluationDirection.NO_TRADE
        assert InvalidationReasonCode.UNFINISHED_CANDLE in result["reason_codes"]

    def test_timing_validator_flags_unfinished_candle(self):
        validator = TimingValidator()
        assert validator.is_candle_unfinished({"complete": False}) is True
        assert validator.is_candle_unfinished({"complete": True}) is False


# ---------------------------------------------------------------------------
# 8. Vision provider timeout -> typed failure, nothing fabricated
# ---------------------------------------------------------------------------
class TestVisionTimeoutFailsClosed:
    def test_timeout_marks_analysis_failed_without_observations(self):
        user = UserFactory(username="phase10-vision-timeout")
        screenshot = make_screenshot(user)
        analysis, _created = get_or_create_analysis(screenshot)
        provider = StaticVisionProvider(error=VisionTimeoutError("provider timed out"))

        with pytest.raises(VisionTimeoutError):
            ScreenshotAnalyzer(provider=provider).analyze(screenshot, analysis)

        analysis.refresh_from_db()
        assert analysis.status == AnalysisStatus.FAILED
        assert analysis.error_code == "provider_timeout"
        assert analysis.result == {}
        assert analysis.chart_metadata == {}
        assert analysis.observations.count() == 0
        assert analysis.patterns.count() == 0
        assert analysis.events.filter(kind=EventKind.PROVIDER_RESPONSE, severity="error").exists()

    def test_http_timeout_maps_to_typed_vision_timeout(self):
        provider = OpenAICompatibleVisionProvider(_provider_config())
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with pytest.raises(VisionTimeoutError):
                provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")


# ---------------------------------------------------------------------------
# 9. Vision provider unavailable / rate-limited -> typed failure, retry policy
# ---------------------------------------------------------------------------
class TestVisionProviderUnavailableAndRateLimited:
    def test_rate_limit_is_retried_bounded_then_fails(self):
        user = UserFactory(username="phase10-rate-limit")
        screenshot = make_screenshot(user)
        analysis, _created = get_or_create_analysis(screenshot)
        provider = _AlwaysFailingVisionProvider(
            VisionRateLimitError("rate limited", retry_after=1.5), max_retries=2
        )
        slept: list[float] = []
        analyzer = ScreenshotAnalyzer(provider=provider, sleep=slept.append)

        with pytest.raises(VisionRateLimitError):
            analyzer.analyze(screenshot, analysis)

        analysis.refresh_from_db()
        assert analysis.status == AnalysisStatus.FAILED
        assert analysis.error_code == "provider_rate_limited"
        assert analysis.result == {}
        assert analysis.observations.count() == 0
        # One initial attempt + two bounded retries; retry_after is honoured.
        assert provider.calls == 3
        assert slept == [1.5, 1.5]

    def test_non_retryable_provider_error_fails_immediately(self):
        user = UserFactory(username="phase10-no-retry")
        screenshot = make_screenshot(user)
        analysis, _created = get_or_create_analysis(screenshot)
        provider = _AlwaysFailingVisionProvider(
            VisionProviderUnavailableError("bad credentials", retryable=False), max_retries=2
        )
        slept: list[float] = []
        analyzer = ScreenshotAnalyzer(provider=provider, sleep=slept.append)

        with pytest.raises(VisionProviderUnavailableError):
            analyzer.analyze(screenshot, analysis)

        analysis.refresh_from_db()
        assert analysis.status == AnalysisStatus.FAILED
        assert analysis.error_code == "provider_unavailable"
        assert provider.calls == 1
        assert slept == []

    def test_http_429_maps_to_rate_limit_with_retry_after(self):
        provider = OpenAICompatibleVisionProvider(_provider_config())
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=_http_error(429, _retry_after_headers("3")),
        ):
            with pytest.raises(VisionRateLimitError) as excinfo:
                provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")
        assert excinfo.value.retry_after == 3.0

    def test_http_401_maps_to_non_retryable_unavailable(self):
        provider = OpenAICompatibleVisionProvider(_provider_config())
        with mock.patch("urllib.request.urlopen", side_effect=_http_error(401)):
            with pytest.raises(VisionProviderUnavailableError) as excinfo:
                provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")
        assert excinfo.value.retryable is False

    def test_http_5xx_maps_to_retryable_unavailable(self):
        provider = OpenAICompatibleVisionProvider(_provider_config())
        with mock.patch("urllib.request.urlopen", side_effect=_http_error(503)):
            with pytest.raises(VisionProviderUnavailableError) as excinfo:
                provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")
        assert excinfo.value.retryable is True


# ---------------------------------------------------------------------------
# 10. Reasoning provider failure -> safe, non-fabricated fallback
# ---------------------------------------------------------------------------
class TestReasoningProviderFailureIsSafe:
    def test_unconfigured_external_provider_falls_back_without_inventing(self):
        provider = ReasoningProvider(provider="external", model="x")
        provider.api_key = ""
        response = provider.complete(ReasoningRequest(messages=(), context={"direction": "UP"}))
        assert response.success is False
        assert response.error == "provider_not_configured"
        assert response.content == "Explanation unavailable from reasoning provider."
        # A broken provider must not assert any direction on its own.
        assert "UP" not in response.content

    def test_follow_up_with_broken_provider_uses_only_stored_evidence(self):
        user = UserFactory(username="phase10-broken-reasoning")
        service = AssistantService()
        service.provider = ReasoningProvider(provider="external", model="x")
        service.provider.api_key = ""
        conversation = ConversationManager().create_conversation(user)

        reply = service.handle_follow_up(user, conversation.pk, "why up?")

        assert "error" not in reply
        assert reply["evidence"]["available"] is False
        assert (
            reply["message"].content
            == "No stored analysis evidence is available for this conversation."
        )

    def test_probability_follow_up_states_unavailable_not_a_number(self):
        user = UserFactory(username="phase10-prob-followup")
        service = AssistantService()
        result = service.analyze_screenshot(user, evaluation_input=_eval_input())
        conversation = result["conversation"]

        reply = service.handle_follow_up(user, conversation.pk, "Is the probability calibrated?")

        assert reply["message"].content == "Probability unavailable — model not calibrated."


# ---------------------------------------------------------------------------
# 11. Redis / cache unavailable -> graceful degradation
# ---------------------------------------------------------------------------
class TestCacheDegradation:
    def test_cache_failure_degrades_health_detail_gracefully(self):
        staff = UserFactory(username="phase10-ops", is_staff=True)
        client = Client()
        client.force_login(staff)

        with mock.patch("django.core.cache.cache") as broken_cache:
            broken_cache.set.side_effect = ConnectionError("redis down")
            broken_cache.get.side_effect = ConnectionError("redis down")
            response = client.get("/healthz/detail/")

        # The endpoint stays available (200) and reports the degraded dependency.
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["cache"]["status"] == "error"
        assert body["checks"]["database"]["status"] == "ok"


# ---------------------------------------------------------------------------
# 12. Celery worker unavailable / task failure -> visible failure
# ---------------------------------------------------------------------------
class TestCeleryFailureIsVisible:
    @override_settings(CELERY_TASK_ALWAYS_EAGER=False, REDIS_URL="redis://broker:6379/0")
    def test_health_detail_reports_missing_celery_workers(self):
        staff = UserFactory(username="phase10-celery-ops", is_staff=True)
        client = Client()
        client.force_login(staff)

        with mock.patch("celery.current_app.control.ping", return_value=[]):
            response = client.get("/healthz/detail/")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["celery"]["status"] == "error"
        assert body["checks"]["celery"]["workers"] == 0

    def test_vision_task_failure_is_recorded_not_silent(self):
        from apps.chart_vision.tasks import analyze_screenshot_task

        user = UserFactory(username="phase10-task-fail")
        screenshot = make_screenshot(user)
        analysis, _created = get_or_create_analysis(screenshot)
        provider = StaticVisionProvider(
            error=VisionProviderUnavailableError("down", retryable=False)
        )

        with mock.patch(
            "apps.chart_vision.services.screenshot_analyzer.get_vision_provider",
            return_value=provider,
        ):
            result = analyze_screenshot_task(analysis.pk)

        assert result["status"] == "failed"
        assert result["error_code"] == "provider_unavailable"
        analysis.refresh_from_db()
        assert analysis.status == AnalysisStatus.FAILED
        assert analysis.error_code == "provider_unavailable"

    def test_vision_task_reports_missing_analysis(self):
        from apps.chart_vision.tasks import analyze_screenshot_task

        assert analyze_screenshot_task(999999) == {"status": "missing", "analysis_id": 999999}


# ---------------------------------------------------------------------------
# 13. Database connection failure -> surfaced, never a wrong result
# ---------------------------------------------------------------------------
class TestDatabaseFailureIsSurfaced:
    def test_healthz_reports_database_failure_as_503(self):
        client = Client()
        with mock.patch(
            "apps.core.views.connection.cursor",
            side_effect=OperationalError("database gone"),
        ):
            response = client.get("/healthz/")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["database"]["status"] == "error"
        assert body["checks"]["database"]["error"] == "OperationalError"

    def test_health_detail_marks_system_down_when_database_fails(self):
        staff = UserFactory(username="phase10-db-ops", is_staff=True)
        client = Client()
        client.force_login(staff)

        with mock.patch(
            "apps.core.views._probe_database",
            return_value={"status": "error", "error": "OperationalError"},
        ):
            response = client.get("/healthz/detail/")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "down"
        assert body["checks"]["database"]["status"] == "error"


# ---------------------------------------------------------------------------
# 14. Invalid model output -> rejected; engine decision cannot be overridden
# ---------------------------------------------------------------------------
class TestInvalidModelOutputCannotOverrideDecision:
    def test_engine_no_trade_is_never_overridden(self):
        result = ResponseValidator().validate(
            {"direction": "UP", "probability_value": None}, engine_direction="NO TRADE"
        )
        assert result["direction"] == "NO TRADE"
        assert "engine_no_trade_violation" in result["errors"]

    def test_invalid_direction_string_is_coerced_to_no_trade(self):
        result = ResponseValidator().validate({"direction": "MAYBE", "probability_value": None})
        assert result["direction"] == "NO TRADE"
        assert "invalid_direction" in result["errors"]

    def test_probability_without_type_and_calibration_is_rejected(self):
        result = ResponseValidator().validate(
            {
                "direction": "UP",
                "probability_value": 0.9,
                "probability_type": None,
                "calibration_status": None,
            },
            engine_direction="UP",
        )
        assert "probability_type_missing" in result["errors"]
        assert "calibration_status_missing" in result["errors"]

    def test_fabricated_probability_in_vision_output_fails_schema_validation(self):
        payload = full_payload()
        payload["win_rate"] = 0.93
        user = UserFactory(username="phase10-fake-prob")
        screenshot = make_screenshot(user)
        analysis, _created = get_or_create_analysis(screenshot)

        with pytest.raises(SchemaValidationError):
            ScreenshotAnalyzer(provider=StaticVisionProvider(payload=payload)).analyze(
                screenshot, analysis
            )

        analysis.refresh_from_db()
        assert analysis.status == AnalysisStatus.FAILED
        assert analysis.error_code == "schema_invalid"
        assert analysis.result == {}
        assert analysis.observations.count() == 0
        assert analysis.patterns.count() == 0


# ---------------------------------------------------------------------------
# 15. Uncalibrated probability model -> probability withheld
# ---------------------------------------------------------------------------
class TestUncalibratedProbabilityWithheld:
    def test_uncalibrated_model_is_withheld(self):
        result = ProbabilityPresenter().present({"is_approved": False, "version": "1"})
        assert result["available"] is False
        assert "not calibrated" in result["message"]

    def test_confluence_score_is_never_presented_as_probability(self):
        result = ProbabilityPresenter().from_confluence_score(0.9)
        assert result["available"] is False
        assert result["reason"] == "confluence_score_is_not_a_probability"

    def test_orchestrator_reports_uncalibrated_status(self):
        result = AnalysisOrchestrator().run(None, evaluation_input=_eval_input())
        assert result["probability_value"] is None
        assert result["probability_type"] is None
        assert result["calibration_status"] == "uncalibrated"

    def test_engine_marks_probability_status_unavailable(self):
        result = EvaluationService().evaluate(_eval_input())
        assert (
            result["statistical_probability_status"] == ProbabilityStatus.UNAVAILABLE_UNCALIBRATED
        )

    def test_insufficient_validated_data_sentinel_without_calibrated_model(self):
        analytics = ProbabilityAnalytics(UserFactory(username="phase10-nocal")).build()
        assert analytics["calibration_status"]["status"] == "unavailable_uncalibrated"
        assert analytics["calibration_status"]["message"] == "Insufficient validated data."
        assert analytics["probabilities"]["confluence_score"]["is_probability"] is False

    def test_journal_win_rate_withheld_without_settled_trades(self):
        summary = JournalPerformance(JournalTrade.objects.none()).summary().to_dict()
        assert summary["win_rate"] is None
        assert summary["win_rate_display"] == INSUFFICIENT_DATA
        assert summary["insufficient_data"] is True


# ---------------------------------------------------------------------------
# 16. Expired next-candle timing window -> signal refused
# ---------------------------------------------------------------------------
class TestExpiredNextCandleWindow:
    # Phase 11 CP5: candle timestamps are offset-aware (``Z``); the timing
    # validator rejects naive/ambiguous timestamps instead of stripping them.
    _SIGNAL_CANDLES = [
        {
            "open_time": "2026-01-05T12:00:00Z",
            "close_time": "2026-01-05T12:01:00Z",
            "complete": True,
        }
    ]

    def test_timing_validator_expires_missed_next_candle(self):
        # Phase 11 CP5 fixed an off-by-one: the target ("next") candle opens
        # at the signal candle's CLOSE (12:01), not one full candle later.
        validity, info = TimingValidator().validate_timing(
            self._SIGNAL_CANDLES, "M1", datetime(2026, 1, 5, 12, 3, tzinfo=UTC)
        )
        assert validity == TimingValidity.EXPIRED
        assert info["target_candle_open_time"] == datetime(2026, 1, 5, 12, 1, tzinfo=UTC)

    def test_timing_validator_allows_small_entry_tolerance(self):
        validity, _info = TimingValidator().validate_timing(
            self._SIGNAL_CANDLES, "M1", datetime(2026, 1, 5, 12, 1, 3, tzinfo=UTC)
        )
        assert validity == TimingValidity.VALID

    def test_timing_validator_rejects_naive_evaluation_clock(self):
        validity, info = TimingValidator().validate_timing(
            self._SIGNAL_CANDLES, "M1", datetime(2026, 1, 5, 12, 2, 3)
        )
        assert validity == TimingValidity.UNCERTAIN
        assert info["reason"] == "ambiguous_evaluation_timestamp"

    def test_orchestrator_expired_window_is_no_trade(self):
        result = AnalysisOrchestrator().run(
            None, evaluation_input=_eval_input(timing_validity="expired")
        )
        assert result["direction"] == "NO TRADE"
        assert "opportunity_expired" in result["warnings"]
        assert result["primary_reason_code"] == "opportunity_expired"
        assert result["probability_value"] is None

    def test_evaluation_expired_entry_forces_no_trade(self):
        # Phase 11 CP5: timestamps are timezone-aware; naive values are
        # rejected rather than silently shifted.
        candles = [
            {
                "open": 1.1,
                "high": 1.105,
                "low": 1.095,
                "close": 1.102,
                "complete": True,
                "open_time": datetime(2026, 1, 5, 12, 0, tzinfo=UTC),
                "close_time": datetime(2026, 1, 5, 12, 1, tzinfo=UTC),
            }
        ]
        result = EvaluationService().evaluate(
            _eval_input(candles=candles), now=datetime(2026, 1, 5, 12, 3, tzinfo=UTC)
        )
        assert result["direction"] == EvaluationDirection.NO_TRADE
        assert InvalidationReasonCode.EXPIRED_ENTRY in result["reason_codes"]
        assert result["timing_validity"] == TimingValidity.EXPIRED


# ---------------------------------------------------------------------------
# 17. Conflicting bullish/bearish evidence -> NO TRADE, never a confident claim
# ---------------------------------------------------------------------------
class TestConflictingEvidenceNeverYieldsDirection:
    def test_conflict_detector_reports_opposing_evidence(self):
        evidence = [
            Evidence(
                rule_id="pa.sr.rejection.bullish",
                detector="support_resistance",
                direction=Direction.BULLISH,
            ),
            Evidence(
                rule_id="pa.sr.rejection.bearish",
                detector="support_resistance",
                direction=Direction.BEARISH,
            ),
        ]
        conflicts = detect_conflicts(evidence)
        record = next(
            (c for c in conflicts if c.conflict_type == ConflictType.OPPOSING_EVIDENCE), None
        )
        assert record is not None
        data = record.to_dict()
        assert data["detail"]["bullish_count"] == 1
        assert data["detail"]["bearish_count"] == 1
        assert record.rule_a and record.rule_b  # both sides are preserved
        assert "probability" not in data  # no invented number

    def test_engine_turns_contradiction_into_no_trade(self):
        conflicted = {
            "evidence": [
                {"rule_id": "pa.sr.zone.support", "detector": "support_resistance"},
                {
                    "rule_id": "pa.sr.rejection.bullish",
                    "detector": "support_resistance",
                    "direction": "bullish",
                },
                {
                    "rule_id": "pa.structure.bearish",
                    "detector": "market_structure",
                    "direction": "bearish",
                },
            ],
            "conflicts": [],
            "context": {},
        }
        result = EvaluationService().evaluate(_eval_input(price_action_result=conflicted))
        assert result["direction"] == EvaluationDirection.NO_TRADE
        assert result["primary_reason_code"] == InvalidationReasonCode.STRONG_CONTRADICTION

    def test_assistant_reports_conflict_as_no_trade_not_direction(self):
        conflicted = {
            "evidence": [
                {
                    "rule_id": "pa.sr.rejection.bullish",
                    "detector": "support_resistance",
                    "direction": "bullish",
                },
                {
                    "rule_id": "pa.structure.bearish",
                    "detector": "market_structure",
                    "direction": "bearish",
                },
            ],
            "conflicts": [],
            "context": {},
        }
        result = AnalysisOrchestrator().run(
            None, evaluation_input=_eval_input(price_action_result=conflicted)
        )
        assert result["direction"] == "NO TRADE"
        assert result["supporting_evidence"] == []
        assert result["probability_value"] is None


# ---------------------------------------------------------------------------
# 18. Unauthorized access -> user A can never read user B's data (API + pages)
# ---------------------------------------------------------------------------
class TestCrossUserIsolation:
    @pytest.fixture
    def users(self):
        attacker = UserFactory(username="phase10-attacker")
        victim = UserFactory(username="phase10-victim")
        return attacker, victim

    def test_user_a_cannot_read_users_b_screenshot_or_analysis(self, users):
        _attacker, victim = users
        screenshot = make_screenshot(victim)
        analysis, _created = get_or_create_analysis(screenshot)
        client = Client()
        client.force_login(victim)
        # Sanity: the owner can read everything.
        assert (
            client.get(reverse("chart_vision:screenshot-image", args=[screenshot.pk])).status_code
            == 200
        )
        assert (
            client.get(reverse("chart_vision:analysis-detail", args=[analysis.pk])).status_code
            == 200
        )

        attacker = UserFactory(username="phase10-attacker-2")
        client.force_login(attacker)
        assert (
            client.get(reverse("chart_vision:screenshot-image", args=[screenshot.pk])).status_code
            == 404
        )
        assert (
            client.get(reverse("chart_vision:analysis-detail", args=[analysis.pk])).status_code
            == 404
        )
        assert client.get(reverse("chart_vision:status", args=[analysis.pk])).status_code == 404

    def test_user_a_cannot_read_users_b_conversation_or_session(self, users):
        _attacker, victim = users
        service = AssistantService()
        result = service.analyze_screenshot(victim, evaluation_input=_eval_input())
        conversation = result["conversation"]
        session_pk = result["response"]["analysis_id"]
        assert session_pk is not None

        client = Client()
        client.force_login(victim)
        assert (
            client.get(
                reverse("ai_assistant:conversation-detail", args=[conversation.pk])
            ).status_code
            == 200
        )
        assert (
            client.get(reverse("ai_assistant:analysis-detail", args=[session_pk])).status_code
            == 200
        )

        attacker = UserFactory(username="phase10-attacker-3")
        client.force_login(attacker)
        assert (
            client.get(
                reverse("ai_assistant:conversation-detail", args=[conversation.pk])
            ).status_code
            == 404
        )
        assert (
            client.get(reverse("ai_assistant:analysis-detail", args=[session_pk])).status_code
            == 404
        )
        response = client.post(
            reverse("ai_assistant:conversation-messages", args=[conversation.pk]),
            {"content": "hello"},
        )
        assert response.status_code == 404

    def test_user_a_cannot_read_users_b_strategy_evaluation(self, users):
        _attacker, victim = users
        evaluation, _result = EvaluationService().evaluate_and_persist(_eval_input(), owner=victim)

        client = Client()
        client.force_login(victim)
        assert (
            client.get(
                reverse("strategy_engine:evaluation-detail", args=[evaluation.pk])
            ).status_code
            == 200
        )

        attacker = UserFactory(username="phase10-attacker-4")
        client.force_login(attacker)
        assert (
            client.get(
                reverse("strategy_engine:evaluation-detail", args=[evaluation.pk])
            ).status_code
            == 404
        )
        history = client.get(reverse("strategy_engine:history"))
        assert history.status_code == 200
        assert history.json()["count"] == 0

    def test_user_a_cannot_read_users_b_journal_trade(self, users):
        _attacker, victim = users
        trade = _journal_trade(victim)

        client = Client()
        client.force_login(victim)
        assert (
            client.get(reverse("trading_journal:trade-detail", args=[trade.pk])).status_code == 200
        )

        attacker = UserFactory(username="phase10-attacker-5")
        client.force_login(attacker)
        assert (
            client.get(reverse("trading_journal:trade-detail", args=[trade.pk])).status_code == 404
        )
        listing = client.get(reverse("trading_journal:trade-list"))
        assert listing.status_code == 200
        assert listing.json()["count"] == 0

    def test_user_a_cannot_open_users_b_dashboard_pages(self, users):
        _attacker, victim = users
        screenshot = make_screenshot(victim)
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(victim)
        session = SynchronizationService().verify(analysis=analysis, owner=victim)
        trade = _journal_trade(victim)

        client = Client()
        client.force_login(victim)
        assert (
            client.get(reverse("dashboard:vision-detail", args=[screenshot.pk])).status_code == 200
        )
        assert client.get(reverse("dashboard:sync-detail", args=[session.pk])).status_code == 200
        assert client.get(reverse("dashboard:journal-edit", args=[trade.pk])).status_code == 200

        attacker = UserFactory(username="phase10-attacker-6")
        client.force_login(attacker)
        assert (
            client.get(reverse("dashboard:vision-detail", args=[screenshot.pk])).status_code == 404
        )
        assert (
            client.get(reverse("dashboard:vision-status", args=[screenshot.pk])).status_code == 404
        )
        assert client.get(reverse("dashboard:sync-detail", args=[session.pk])).status_code == 404
        assert client.get(reverse("dashboard:journal-edit", args=[trade.pk])).status_code == 404

    def test_user_a_cannot_read_users_b_sync_session_via_api(self, users):
        _attacker, victim = users
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(victim)
        session = SynchronizationService().verify(analysis=analysis, owner=victim)

        client = Client()
        client.force_login(victim)
        assert client.get(f"/api/sync/results/{session.pk}/").status_code == 200

        attacker = UserFactory(username="phase10-attacker-7")
        client.force_login(attacker)
        assert client.get(f"/api/sync/results/{session.pk}/").status_code == 404


# ---------------------------------------------------------------------------
# 19. Duplicate analysis submission -> idempotent, no duplicate/corrupt rows
# ---------------------------------------------------------------------------
class TestDuplicateSubmissionsAreIdempotent:
    def test_duplicate_analysis_requests_reuse_single_row(self):
        user = UserFactory(username="phase10-dup-row")
        screenshot = make_screenshot(user)
        first, created_first = get_or_create_analysis(screenshot)
        second, created_second = get_or_create_analysis(screenshot)

        assert created_first is True
        assert created_second is False
        assert first.pk == second.pk
        assert ScreenshotAnalysis.objects.filter(screenshot=screenshot).count() == 1

    def test_repeated_analyze_requests_enqueue_once(self):
        user = UserFactory(username="phase10-dup-enqueue")
        screenshot = make_screenshot(user)
        client = Client()
        client.force_login(user)
        url = reverse("chart_vision:screenshot-analyze", args=[screenshot.pk])

        with mock.patch("apps.chart_vision.tasks.analyze_screenshot_task.delay") as delay:
            first = client.post(url)
            second = client.post(url)

        assert first.status_code == 202
        assert second.status_code == 202
        assert ScreenshotAnalysis.objects.filter(screenshot=screenshot).count() == 1
        assert delay.call_count == 1  # no duplicate job was enqueued

    def test_duplicate_sync_verification_is_idempotent(self):
        user = UserFactory(username="phase10-dup-sync")
        _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)
        service = SynchronizationService()

        first = service.verify(analysis=analysis, owner=user, idempotency_key="phase10-dup")
        second = service.verify(analysis=analysis, owner=user, idempotency_key="phase10-dup")

        assert first.pk == second.pk
        assert MarketSyncSession.objects.filter(idempotency_key="phase10-dup").count() == 1

    def test_rerun_replaces_derived_rows_without_duplicates(self):
        user = UserFactory(username="phase10-dup-rerun")
        screenshot = make_screenshot(user)
        analysis, _created = get_or_create_analysis(screenshot)
        analyzer = ScreenshotAnalyzer(provider=StaticVisionProvider(payload=full_payload()))
        analyzer.analyze(screenshot, analysis)
        observation_count = analysis.observations.count()
        assert analysis.patterns.count() == 2

        analyzer.analyze(screenshot, analysis)

        assert analysis.patterns.count() == 2
        assert analysis.observations.count() == observation_count
