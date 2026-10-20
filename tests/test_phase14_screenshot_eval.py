# tests/test_phase14_screenshot_eval.py
"""Phase 14 regression tests (Checkpoints 1-9).

Hermetic: SQLite, generated in-memory images, fake vision provider, hand-built
candles. No network, no LLM, no MT5, no real IQ Option data.

Coverage map (Checkpoint 8):
* screenshot upload + ownership
* real vision-provider integration (fake provider through the real pipeline)
* pattern recognition over screenshots
* chart annotations (reliable vs unreliable coordinates)
* incomplete-candle handling
* prediction immutability
* OTC feed compatibility (never substituted)
* outcome verification
* duplicate submissions
* no-lookahead guarantees
* missing data
* NO TRADE safeguards
* dashboard metrics (both scopes, never mixed)
* user authorization
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.book_strategies.constants import BookPatternState
from apps.chart_vision.services.screenshot_analyzer import (
    ScreenshotAnalyzer,
    get_or_create_analysis,
)
from apps.screenshot_eval.constants import (
    PREDICTION_METRIC_SCOPE,
    RECOGNITION_METRIC_SCOPE,
    AnnotationStatus,
    CaseKind,
    MarketType,
    OutcomeVerdict,
    PredictionDirection,
    PredictionStatus,
    ReviewState,
    ScreenshotQuality,
)
from apps.screenshot_eval.models import (
    ForwardPaperPrediction,
    PredictionLockedError,
    ReviewQueueItem,
    ScreenshotCase,
    ScreenshotRecognition,
    ScreenshotRecognitionRun,
)
from apps.screenshot_eval.services.annotation import AnnotationRequest, AnnotationService
from apps.screenshot_eval.services.dataset import CaseInput, ScreenshotDatasetService
from apps.screenshot_eval.services.forward import ForwardPredictionService, ForwardRecordInput
from apps.screenshot_eval.services.metrics import (
    ScreenshotMetricsService,
    assert_scope_separation,
)
from apps.screenshot_eval.services.outcome_verification import (
    OutcomeVerificationService,
    feed_is_mt5,
)
from apps.screenshot_eval.services.recognition import ScreenshotRecognitionService
from apps.screenshot_eval.services.review import ReviewQueueService
from tests.factories import UserFactory
from tests.vision_fakes import StaticVisionProvider, full_payload, make_screenshot

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _seed_catalog():
    call_command("seed_book_strategies")


@pytest.fixture
def user():
    return UserFactory(username="phase14-analyst")


@pytest.fixture
def other_user():
    return UserFactory(username="phase14-other")


def analyzed_screenshot(user, *, otc: bool = False, symbol: str = "EURUSD"):
    """A real screenshot + a completed analysis through the real pipeline."""
    screenshot = make_screenshot(user)
    payload = full_payload()
    if otc:
        payload = full_payload(
            chart_metadata={
                **full_payload()["chart_metadata"],
                "otc_status": "otc",
                "instrument": symbol,
            }
        )
    else:
        payload = full_payload(
            chart_metadata={
                **full_payload()["chart_metadata"],
                "instrument": symbol,
            }
        )
    analysis, _ = get_or_create_analysis(screenshot)
    ScreenshotAnalyzer(provider=StaticVisionProvider(payload=payload)).analyze(
        screenshot, analysis
    )
    analysis.refresh_from_db()
    return screenshot, analysis


def make_case(
    user,
    *,
    otc: bool = False,
    case_kind: str = CaseKind.POSITIVE,
    expected: list[str] | None = None,
    review: str = ReviewState.CONFIRMED,
    coordinates_reliable: bool = False,
    symbol: str = "EURUSD",
    timeframe: str = "M5",
    label: str = "case",
) -> ScreenshotCase:
    screenshot, _ = analyzed_screenshot(user, otc=otc, symbol=symbol)
    service = ScreenshotDatasetService()
    case = service.create_case(
        owner=user,
        screenshot=screenshot,
        data=CaseInput(
            label=label,
            instrument=symbol,
            timeframe=timeframe,
            market_type=MarketType.OTC if otc else MarketType.REGULAR,
            quality=ScreenshotQuality.HIGH,
            case_kind=case_kind,
            expected_strategy_keys=expected if expected is not None else [],
            coordinates_reliable=coordinates_reliable,
        ),
    )
    if review is not None:
        service.review(case=case, reviewer=user, review_state=review)
        case.refresh_from_db()
    return case


# ===========================================================================
# Checkpoint 1 - screenshot dataset & ownership
# ===========================================================================
def test_case_created_from_owned_screenshot(user):
    case = make_case(user, expected=["SS1"])
    assert case.owner_id == user.pk
    assert case.is_labelled is True
    assert case.expected_strategy_keys == ["SS1"]


def test_case_refuses_another_users_screenshot(user, other_user):
    screenshot, _ = analyzed_screenshot(other_user)
    with pytest.raises(PermissionError):
        ScreenshotDatasetService().create_case(
            owner=user, screenshot=screenshot, data=CaseInput(label="x")
        )


def test_unlabelled_case_is_not_ground_truth(user):
    case = make_case(user, review=None, expected=["SS1"])
    assert case.is_labelled is False
    assert case.review_state == ReviewState.UNREVIEWED


def test_review_correction_updates_label_only(user):
    case = make_case(user, expected=["SS1"])
    ScreenshotDatasetService().review(
        case=case,
        reviewer=user,
        review_state=ReviewState.CORRECTED,
        expected_strategy_keys=["SS2"],
    )
    case.refresh_from_db()
    assert case.review_state == ReviewState.CORRECTED
    assert case.expected_strategy_keys == ["SS2"]


def test_non_owner_non_staff_cannot_review(user, other_user):
    case = make_case(user, review=None)
    with pytest.raises(PermissionError):
        ScreenshotDatasetService().review(
            case=case, reviewer=other_user, review_state=ReviewState.CONFIRMED
        )


# ===========================================================================
# Checkpoint 2 - recognition over screenshots
# ===========================================================================
def test_recognition_without_candles_is_screenshot_only(user):
    case = make_case(user, expected=["SS1"])
    outcome = ScreenshotRecognitionService().run(case=case, owner=user)
    assert outcome.run.pk is not None
    # Vision-mapper recognition is capped at screenshot-only verification.
    for row in outcome.recognitions:
        assert row.decision == "NO_TRADE"
        assert row.probability is None


def test_recognition_produces_required_fields(user):
    case = make_case(user, expected=["SS1"])
    outcome = ScreenshotRecognitionService().run(case=case, owner=user)
    assert outcome.recognitions, "expected at least the vision-mapper candidates"
    row = outcome.recognitions[0]
    # Every candidate carries the Step-9 shape.
    assert row.strategy_id
    assert row.recognition_state
    assert isinstance(row.observed_evidence, list)
    assert isinstance(row.missing_conditions, list)
    assert isinstance(row.invalidation_evidence, list)
    assert row.data_verification


def test_recognition_matching_label_is_recorded(user):
    # A screenshot labelled bullish_engulfing maps to SS4 via the vision table.
    case = make_case(user, expected=["SS4"])
    outcome = ScreenshotRecognitionService().run(case=case, owner=user)
    ss4 = [r for r in outcome.recognitions if r.strategy_key == "SS4"]
    assert ss4, "SS4 should surface through the vision->book mapper"
    assert ss4[0].matches_label is True


def test_recognition_never_invents_ohlc_from_pixels(user):
    case = make_case(user, expected=["SS1"])
    outcome = ScreenshotRecognitionService().run(case=case, owner=user)
    # No deterministic confirmation can come from a screenshot alone.
    for row in outcome.recognitions:
        assert row.recognition_state != BookPatternState.CONFIRMED_PATTERN
        assert row.reference_level is None


# ===========================================================================
# Checkpoint 2/5 - OTC feed compatibility
# ===========================================================================
def test_otc_screenshot_with_mt5_feed_is_incompatible(user):
    case = make_case(user, otc=True, expected=["SS1"])
    candles = _flat_candles(40)
    outcome = ScreenshotRecognitionService().run(
        case=case,
        owner=user,
        candles=candles,
        data_source="mt5:EURUSD:M5",
        feed_market_type="regular",
    )
    otc_rows = [r for r in outcome.recognitions if r.strategy_key == "SS1"]
    assert otc_rows
    # SS1 has a detector, but the OTC screenshot vs regular feed is refused.
    assert otc_rows[0].data_verification == "INCOMPATIBLE_FEEDS"
    assert otc_rows[0].recognition_state == BookPatternState.INSUFFICIENT_DATA


def test_feed_is_mt5_classifier():
    assert feed_is_mt5("mt5")
    assert feed_is_mt5("mt5_candle")
    assert feed_is_mt5("MT5")
    assert not feed_is_mt5("iq_option_otc")


# ===========================================================================
# Checkpoint 3 - annotations
# ===========================================================================
def test_annotation_available_with_reliable_coordinates(user):
    case = make_case(user, coordinates_reliable=True)
    rows = AnnotationService().annotate(
        case=case,
        owner=user,
        requests=[
            AnnotationRequest(
                kind="resistance",
                label="R1",
                relative_coordinates=[0.1, 0.2, 0.9, 0.25],
            )
        ],
    )
    assert rows[0].status == AnnotationStatus.AVAILABLE
    assert rows[0].relative_coordinates == [0.1, 0.2, 0.9, 0.25]


def test_annotation_skipped_when_case_coordinates_unreliable(user):
    case = make_case(user, coordinates_reliable=False)
    rows = AnnotationService().annotate(
        case=case,
        owner=user,
        requests=[
            AnnotationRequest(
                kind="support", label="S1", relative_coordinates=[0.1, 0.2, 0.9, 0.25]
            )
        ],
    )
    assert rows[0].status == AnnotationStatus.SKIPPED
    assert rows[0].relative_coordinates is None
    assert rows[0].reason == "COORDINATES_UNRELIABLE"


def test_annotation_qualitative_when_no_coordinates_but_case_reliable(user):
    case = make_case(user, coordinates_reliable=True)
    rows = AnnotationService().annotate(
        case=case,
        owner=user,
        requests=[AnnotationRequest(kind="pattern_name", label="Magic V")],
    )
    assert rows[0].status == AnnotationStatus.QUALITATIVE
    assert rows[0].relative_coordinates is None


def test_annotation_rejects_out_of_range_coordinates(user):
    case = make_case(user, coordinates_reliable=True)
    rows = AnnotationService().annotate(
        case=case,
        owner=user,
        requests=[
            AnnotationRequest(
                kind="support", relative_coordinates=[-0.5, 0.2, 5.0, 0.25]
            )
        ],
    )
    # Invalid geometry is downgraded to qualitative, never drawn.
    assert rows[0].status == AnnotationStatus.QUALITATIVE
    assert rows[0].relative_coordinates is None


def test_original_screenshot_untouched_by_annotation(user):
    case = make_case(user, coordinates_reliable=True)
    original = case.screenshot.sha256
    AnnotationService().annotate(
        case=case,
        owner=user,
        requests=[AnnotationRequest(kind="support", relative_coordinates=[0.1, 0.2, 0.9, 0.5])],
    )
    case.screenshot.refresh_from_db()
    assert case.screenshot.sha256 == original


# ===========================================================================
# Checkpoint 4 - forward predictions (immutability, locking)
# ===========================================================================
def _record_prediction(user, case, direction=PredictionDirection.UP, **kwargs):
    return ForwardPredictionService().record(
        case=case,
        owner=user,
        data=ForwardRecordInput(
            strategy_key=kwargs.pop("strategy_key", "SS1"),
            strategy_id=kwargs.pop("strategy_id", "BO-SS1"),
            direction=direction,
            strategy_version=kwargs.pop("strategy_version", "1.0"),
            **kwargs,
        ),
    )


def test_prediction_is_locked_with_digest(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case)
    assert prediction.status == PredictionStatus.LOCKED
    assert prediction.payload_sha256
    assert prediction.verify_integrity() is True
    assert prediction.decision_timestamp is not None


def test_prediction_is_idempotent_per_case_strategy(user):
    case = make_case(user, expected=["SS1"])
    first = _record_prediction(user, case)
    second = _record_prediction(user, case)
    assert first.pk == second.pk
    assert ForwardPaperPrediction.objects.filter(case=case, strategy_key="SS1").count() == 1


def test_prediction_requires_eligible_strategy(user):
    case = make_case(user, expected=["SS2"])  # SS1 not named
    with pytest.raises(ValueError, match="not eligible"):
        _record_prediction(user, case, strategy_key="SS1", strategy_id="BO-SS1")


def test_prediction_fields_are_immutable(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case)
    prediction.direction = PredictionDirection.DOWN
    with pytest.raises(PredictionLockedError):
        prediction.save()


def test_prediction_status_cannot_be_edited_directly(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case)
    prediction.status = PredictionStatus.VERIFIED
    with pytest.raises(PredictionLockedError):
        prediction.save()


def test_prediction_probability_requires_calibration(user):
    case = make_case(user, expected=["SS1"])
    with pytest.raises(ValueError, match="calibrated"):
        _record_prediction(user, case, probability=0.7)


def test_prediction_digest_detects_tampering(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case)
    # Bypass the save guard to simulate an out-of-band edit.
    ForwardPaperPrediction.objects.filter(pk=prediction.pk).update(
        prediction_payload={"tampered": True}
    )
    prediction.refresh_from_db()
    assert prediction.verify_integrity() is False


# ===========================================================================
# Checkpoint 5 - outcome verification
# ===========================================================================
def test_verified_correct_outcome(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case, direction=PredictionDirection.UP)
    verifier = OutcomeVerificationService()
    record = verifier.verify(
        prediction=prediction,
        owner=user,
        entry_quote=1.1000,
        settlement_quote=1.1050,
        price_source="iq_option_regular",
        feed_market_type="regular",
        feed="iq_option_regular",
    )
    prediction.refresh_from_db()
    assert record.verdict == OutcomeVerdict.CORRECT
    assert prediction.status == PredictionStatus.VERIFIED


def test_incorrect_outcome_is_recorded(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case, direction=PredictionDirection.UP)
    record = OutcomeVerificationService().verify(
        prediction=prediction,
        owner=user,
        entry_quote=1.1000,
        settlement_quote=1.0950,
        price_source="iq_option_regular",
        feed_market_type="regular",
    )
    assert record.verdict == OutcomeVerdict.INCORRECT


def test_tie_is_recorded_separately(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case, direction=PredictionDirection.UP)
    record = OutcomeVerificationService().verify(
        prediction=prediction,
        owner=user,
        entry_quote=1.1000,
        settlement_quote=1.1000,
        price_source="iq_option_regular",
        feed_market_type="regular",
    )
    prediction.refresh_from_db()
    assert record.verdict == OutcomeVerdict.TIE
    assert prediction.status == PredictionStatus.TIE


def test_otc_prediction_refuses_mt5_feed(user):
    case = make_case(user, otc=True, expected=["SS1"])
    prediction = _record_prediction(user, case, direction=PredictionDirection.UP)
    record = OutcomeVerificationService().verify(
        prediction=prediction,
        owner=user,
        entry_quote=1.1000,
        settlement_quote=1.1050,
        price_source="mt5",
        feed_market_type="regular",
    )
    prediction.refresh_from_db()
    assert record.verdict == OutcomeVerdict.REFUSED
    assert record.reason_code == "INCOMPATIBLE_FEEDS"
    assert prediction.status == PredictionStatus.UNVERIFIED


def test_no_quote_is_unverifiable_not_correct(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case, direction=PredictionDirection.UP)
    record = OutcomeVerificationService().verify(
        prediction=prediction,
        owner=user,
        price_source="iq_option_regular",
        feed_market_type="regular",
    )
    prediction.refresh_from_db()
    assert record.verdict == OutcomeVerdict.UNVERIFIABLE
    assert prediction.status == PredictionStatus.UNVERIFIED


def test_verification_is_write_once(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case, direction=PredictionDirection.UP)
    verifier = OutcomeVerificationService()
    first = verifier.verify(
        prediction=prediction, owner=user, entry_quote=1.1, settlement_quote=1.2,
        price_source="iq_option_regular", feed_market_type="regular",
    )
    second = verifier.verify(
        prediction=prediction, owner=user, entry_quote=1.1, settlement_quote=0.9,
        price_source="iq_option_regular", feed_market_type="regular",
    )
    assert first.pk == second.pk
    assert second.verdict == OutcomeVerdict.CORRECT  # unchanged


def test_no_trade_prediction_has_no_outcome(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case, direction=PredictionDirection.NO_TRADE)
    record = OutcomeVerificationService().verify(
        prediction=prediction, owner=user, price_source="iq_option_regular"
    )
    assert record.verdict == OutcomeVerdict.PENDING
    prediction.refresh_from_db()
    assert prediction.status == PredictionStatus.LOCKED  # untouched


# ===========================================================================
# Checkpoint 6 - metrics (scope separation)
# ===========================================================================
def test_metrics_scopes_are_separate(user):
    payload = ScreenshotMetricsService().build()
    assert payload["recognition"]["metric_scope"] == RECOGNITION_METRIC_SCOPE
    assert payload["prediction"]["metric_scope"] == PREDICTION_METRIC_SCOPE
    assert_scope_separation(payload["recognition"])
    assert_scope_separation(payload["prediction"])


def test_recognition_metrics_none_below_threshold(user):
    make_case(user, expected=["SS4"])
    payload = ScreenshotMetricsService().build()
    rec = payload["recognition"]
    assert rec["labelled_cases"] == 1
    assert rec["precision"] is None
    assert rec["recall"] is None
    assert rec["sufficient_data"] is False


def test_prediction_metrics_exclude_unverified(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case, direction=PredictionDirection.UP)
    OutcomeVerificationService().verify(
        prediction=prediction, owner=user, price_source="mt5", feed_market_type="regular"
    )
    payload = ScreenshotMetricsService().build()
    pred = payload["prediction"]
    assert pred["verified_total"] == 0
    assert pred["hit_rate"] is None
    assert pred["unverified"] == 1


def test_prediction_hit_rate_counts_only_verified(user):
    for i in range(2):
        case = make_case(user, expected=["SS1"], label=f"c{i}")
        prediction = _record_prediction(user, case, direction=PredictionDirection.UP)
        OutcomeVerificationService().verify(
            prediction=prediction,
            owner=user,
            entry_quote=1.1,
            settlement_quote=1.2,
            price_source="iq_option_regular",
            feed_market_type="regular",
        )
    payload = ScreenshotMetricsService().build()
    pred = payload["prediction"]
    assert pred["verified_total"] == 2
    assert pred["verified_correct"] == 2


def test_no_trade_excluded_from_directional_counts(user):
    case = make_case(user, expected=["SS1"])
    _record_prediction(user, case, direction=PredictionDirection.NO_TRADE)
    payload = ScreenshotMetricsService().build()
    pred = payload["prediction"]
    assert pred["no_trade"] == 1
    assert pred["up"] == 0
    assert pred["down"] == 0
    assert pred["verified_total"] == 0


def test_segment_breakdown_by_market_type(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case, direction=PredictionDirection.UP)
    OutcomeVerificationService().verify(
        prediction=prediction,
        owner=user,
        entry_quote=1.1,
        settlement_quote=1.2,
        price_source="iq_option_regular",
        feed_market_type="regular",
    )
    segments = ScreenshotMetricsService().by_segment("market_type")["buckets"]
    assert "regular" in segments
    assert segments["regular"]["verified_total"] == 1


def test_scope_wall_rejects_cross_leak():
    with pytest.raises(ValueError):
        assert_scope_separation(
            {"metric_scope": RECOGNITION_METRIC_SCOPE, "hit_rate": 0.5}
        )
    with pytest.raises(ValueError):
        assert_scope_separation(
            {"metric_scope": PREDICTION_METRIC_SCOPE, "precision": 0.5}
        )


# ===========================================================================
# Checkpoint 7 - error review queue
# ===========================================================================
def test_review_scan_raises_contradiction_items(user):
    case = make_case(user, expected=["SS1"])
    run = ScreenshotRecognitionRun.objects.create(case=case, owner=user)
    ScreenshotRecognition.objects.create(
        run=run,
        strategy_key="SS1",
        strategy_id="BO-SS1",
        recognition_state=BookPatternState.INVALIDATED,
        data_verification="MT5_VERIFIED",
        contradictions=["body sizes disagree"],
        invalidation_evidence=["close back below level"],
    )
    result = ReviewQueueService().scan(owner=user)
    kinds = {item.kind for item in result.items}
    assert ReviewQueueItem.Kind.INCORRECT_BREAKOUT in kinds
    assert ReviewQueueItem.Kind.CONTRADICTORY_EVIDENCE in kinds


def test_review_scan_raises_missing_confirmation(user):
    case = make_case(user, expected=["SS1"])
    run = ScreenshotRecognitionRun.objects.create(case=case, owner=user)
    ScreenshotRecognition.objects.create(
        run=run,
        strategy_key="SS1",
        strategy_id="BO-SS1",
        recognition_state=BookPatternState.AWAITING_CONFIRMATION,
        data_verification="SCREENSHOT_ONLY",
    )
    kinds = {item.kind for item in ReviewQueueService().scan(owner=user).items}
    assert ReviewQueueItem.Kind.MISSING_CONFIRMATION in kinds


def test_review_scan_raises_false_level(user):
    case = make_case(user, expected=["SS1"], coordinates_reliable=False)
    AnnotationService().annotate(
        case=case,
        owner=user,
        requests=[AnnotationRequest(kind="support", label="S1")],
    )
    kinds = {item.kind for item in ReviewQueueService().scan(owner=user).items}
    assert ReviewQueueItem.Kind.FALSE_LEVEL in kinds


def test_review_scan_raises_wrong_timeframe(user):
    make_case(user, expected=["SS1"], timeframe="??")
    kinds = {item.kind for item in ReviewQueueService().scan(owner=user).items}
    assert ReviewQueueItem.Kind.WRONG_TIMEFRAME in kinds


def test_review_scan_is_idempotent(user):
    case = make_case(user, expected=["SS1"])
    run = ScreenshotRecognitionRun.objects.create(case=case, owner=user)
    ScreenshotRecognition.objects.create(
        run=run,
        strategy_key="SS1",
        strategy_id="BO-SS1",
        recognition_state=BookPatternState.FORMING,
        data_verification="SCREENSHOT_ONLY",
    )
    ReviewQueueService().scan(owner=user)
    second = ReviewQueueService().scan(owner=user)
    assert second.created == 0


def test_review_correction_never_rewrites_prediction(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case, direction=PredictionDirection.UP)
    run = ScreenshotRecognitionRun.objects.create(case=case, owner=user)
    ScreenshotRecognition.objects.create(
        run=run, strategy_key="SS1", strategy_id="BO-SS1",
        recognition_state=BookPatternState.INVALIDATED, data_verification="MT5_VERIFIED",
    )
    result = ReviewQueueService().scan(owner=user)
    item = result.items[0]
    ReviewQueueService().resolve(
        item=item, reviewer=user, correction={"label": "SS2"}, resolution_note="fixed"
    )
    prediction.refresh_from_db()
    assert prediction.direction == PredictionDirection.UP
    assert prediction.status == PredictionStatus.LOCKED
    item.refresh_from_db()
    assert item.state == ReviewQueueItem.State.RESOLVED
    assert item.correction == {"label": "SS2"}


def test_review_resolution_requires_authorization(user, other_user):
    case = make_case(user, expected=["SS1"])
    run = ScreenshotRecognitionRun.objects.create(case=case, owner=user)
    ScreenshotRecognition.objects.create(
        run=run, strategy_key="SS1", strategy_id="BO-SS1",
        recognition_state=BookPatternState.FORMING, data_verification="SCREENSHOT_ONLY",
    )
    item = ReviewQueueService().scan(owner=user).items[0]
    with pytest.raises(PermissionError):
        ReviewQueueService().resolve(item=item, reviewer=other_user)


def test_incorrect_outcome_raises_review_item(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case, direction=PredictionDirection.UP)
    OutcomeVerificationService().verify(
        prediction=prediction,
        owner=user,
        entry_quote=1.1,
        settlement_quote=0.9,
        price_source="iq_option_regular",
        feed_market_type="regular",
    )
    result = ReviewQueueService().scan(owner=user)
    kinds = {item.kind for item in result.items}
    assert ReviewQueueItem.Kind.INCORRECT_OUTCOME in kinds


# ===========================================================================
# Checkpoint 8 - management commands & no-lookahead
# ===========================================================================
def test_screenshot_forward_report_command(user, tmp_path):
    out = tmp_path / "report.json"
    call_command("screenshot_forward_report", "--out", str(out))
    assert out.exists()
    import json

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["recognition"]["metric_scope"] == RECOGNITION_METRIC_SCOPE
    assert payload["prediction"]["metric_scope"] == PREDICTION_METRIC_SCOPE
    assert payload["approved_for_decision_use"] is False


def test_scan_review_queue_command(user):
    case = make_case(user, expected=["SS1"])
    run = ScreenshotRecognitionRun.objects.create(case=case, owner=user)
    ScreenshotRecognition.objects.create(
        run=run, strategy_key="SS1", strategy_id="BO-SS1",
        recognition_state=BookPatternState.FORMING, data_verification="SCREENSHOT_ONLY",
    )
    call_command("scan_review_queue", "--owner", user.username)
    assert ReviewQueueItem.objects.filter(state="open").exists()


def test_run_screenshot_recognition_command(user):
    case = make_case(user, expected=["SS1"])
    call_command("run_screenshot_recognition", "--case-id", str(case.pk))
    assert ScreenshotRecognitionRun.objects.filter(case=case).exists()


def test_recognition_command_refuses_when_no_candles(user):
    from django.core.management.base import CommandError

    case = make_case(user, expected=["SS1"])
    with pytest.raises(CommandError):
        call_command(
            "run_screenshot_recognition",
            "--case-id",
            str(case.pk),
            "--symbol",
            "ZZZNOTREAL",
            "--timeframe",
            "M5",
        )


def test_decision_timestamp_is_not_in_the_future(user):
    case = make_case(user, expected=["SS1"])
    prediction = _record_prediction(user, case)
    # The prediction is written before any outcome exists; its payload asserts it.
    assert prediction.prediction_payload["written_before_outcome"] is True
    assert prediction.decision_timestamp <= datetime.now(UTC) + timedelta(seconds=5)


# ===========================================================================
# Checkpoint 9 / dashboard - authorization & rendering
# ===========================================================================
def test_forward_testing_page_requires_login(client):
    response = client.get(reverse("dashboard:forward-testing"))
    assert response.status_code in (301, 302)


def test_forward_testing_page_renders(client, user):
    client.force_login(user)
    response = client.get(reverse("dashboard:forward-testing"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "recognition" in body.lower()
    assert "prediction" in body.lower()


def test_screenshot_cases_page_owner_scoped(client, user, other_user):
    make_case(user, expected=["SS1"], label="mine")
    make_case(other_user, expected=["SS1"], label="theirs")
    client.force_login(user)
    response = client.get(reverse("dashboard:screenshot-cases"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "mine" in body
    assert "theirs" not in body


def test_case_detail_is_owner_scoped(client, user, other_user):
    case = make_case(other_user, expected=["SS1"])
    client.force_login(user)
    response = client.get(
        reverse("dashboard:screenshot-case-detail", args=[case.pk])
    )
    assert response.status_code == 404


def test_review_queue_page_renders(client, user):
    client.force_login(user)
    response = client.get(reverse("dashboard:review-queue"))
    assert response.status_code == 200


def test_review_resolve_view_stores_correction(client, user):
    case = make_case(user, expected=["SS1"])
    run = ScreenshotRecognitionRun.objects.create(case=case, owner=user)
    ScreenshotRecognition.objects.create(
        run=run, strategy_key="SS1", strategy_id="BO-SS1",
        recognition_state=BookPatternState.FORMING, data_verification="SCREENSHOT_ONLY",
    )
    item = ReviewQueueService().scan(owner=user).items[0]
    client.force_login(user)
    response = client.post(
        reverse("dashboard:review-resolve", args=[item.pk]),
        {"action": "resolve", "correction": "label is SS2", "note": "checked"},
    )
    assert response.status_code in (301, 302)
    item.refresh_from_db()
    assert item.state == ReviewQueueItem.State.RESOLVED
    assert item.correction == {"note": "label is SS2"}


# ===========================================================================
# Helpers
# ===========================================================================
def _flat_candles(count: int, start: float = 1.1000) -> list[dict]:
    out = []
    price = start
    for i in range(count):
        o = price
        c = price + (0.0001 if i % 2 == 0 else -0.0001)
        out.append(
            {
                "open_time": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=5 * i),
                "open": o,
                "high": max(o, c) + 0.0001,
                "low": min(o, c) - 0.0001,
                "close": c,
                "complete": True,
            }
        )
        price = c
    return out
