# tests/test_phase12_knowledge.py
"""Phase 12 — knowledge base, recognition services, dataset, metrics, pages.

Covers CP1 (models + schemas), CP8 (registry over DB definitions), CP9
(candidate mapping + deterministic verification), CP10 (de-duplication and the
multi-strategy pipeline), CP11 (retrieval + assistant knowledge context),
CP12 (dashboard library pages), CP13 (annotation never mutates the original),
CP14 (dataset workflow: reviewer labels are the only ground truth) and CP15
(honest detection metrics — never fabricated accuracy).

Every test is hermetic: SQLite, static vision payloads, hand-built candles.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from apps.ai_assistant.services.assistant_service import (
    MAX_KNOWLEDGE_CONTEXT_CHARS,
    AssistantService,
)
from apps.chart_vision.services.screenshot_analyzer import (
    ScreenshotAnalyzer,
    get_or_create_analysis,
)
from apps.strategy_knowledge.constants import (
    ConditionKind,
    DatasetSampleKind,
    DetectionStatus,
    EvidenceProvenance,
    LabelSource,
    ValidationStatus,
)
from apps.strategy_knowledge.models import (
    StrategyCategory,
    StrategyCondition,
    StrategyDefinition,
    StrategyDetection,
    StrategyPatternLabel,
    StrategyVersion,
)
from apps.strategy_knowledge.registry import run_detector
from apps.strategy_knowledge.services import (
    DatasetWorkflowError,
    DetectionMetricsService,
    KnowledgeRetrievalService,
    MultiStrategyRecognitionService,
    PatternVerificationService,
    StrategyCandidate,
    StrategyDatasetWorkflow,
    build_candidates,
    dedupe_candidates,
)
from apps.strategy_knowledge.services.annotation import annotate_screenshot
from tests.factories import UserFactory
from tests.pa_fakes import CONFIG, candle
from tests.vision_fakes import StaticVisionProvider, full_payload, make_screenshot

pytestmark = pytest.mark.django_db

#: Two candles whose last candle is a confirmed bullish engulfing (same
#: geometry as the Phase 5 pattern tests).
ENGULFING = [candle(1.0, 1.01, 0.99, 0.995), candle(0.993, 1.02, 0.99, 1.019)]


def run_analysis(screenshot, provider):
    """Persist a completed analysis exactly like the chart-vision tests do."""
    analysis, _ = get_or_create_analysis(screenshot)
    ScreenshotAnalyzer(provider=provider).analyze(screenshot, analysis)
    analysis.refresh_from_db()
    return analysis


@pytest.fixture
def user():
    return UserFactory(username="knowledge-analyst")


@pytest.fixture
def version():
    return StrategyVersion.objects.create(version="test-12")


@pytest.fixture
def category():
    return StrategyCategory.objects.create(slug="test-cat", name="Test category")


def make_definition(
    category,
    version,
    *,
    strategy_id="cs.test_engulfing",
    detector_key="cs.bullish_engulfing",
    name="Bullish engulfing setup",
    status=ValidationStatus.APPROVED,
    enabled=True,
    variant="bullish",
):
    return StrategyDefinition.objects.create(
        strategy_id=strategy_id,
        name=name,
        category=category,
        description="A bullish candle engulfs the prior bearish body.",
        market_context="after a decline",
        variant=variant,
        detector_key=detector_key,
        validation_status=status,
        version=version,
        enabled=enabled,
    )


def make_candidate(definition, *, refs=None, confidence=0.5, label="bullish_engulfing"):
    return StrategyCandidate(
        definition=definition,
        strategy_id=definition.strategy_id,
        direction=definition.variant,
        source_kind="pattern",
        source_label=label,
        confidence=confidence,
        vision_confirmed=True,
        evidence_summary="vision observed the pattern",
        candle_refs=list(refs or [1]),
        result_path=f"patterns.{label}",
    )


# ---------------------------------------------------------------------------
# CP1 — models & schemas: database content can never become executable logic
# ---------------------------------------------------------------------------
def test_unknown_detector_key_is_rejected_by_model_validation(category, version):
    definition = StrategyDefinition(
        strategy_id="evil.detector",
        name="Not a detector",
        category=category,
        description="tries to reference arbitrary logic",
        detector_key="evil.run_code",
    )
    with pytest.raises(ValidationError):
        definition.full_clean()


def test_condition_params_reject_unknown_keys_and_non_scalars(category, version):
    definition = make_definition(category, version)
    for bad in (
        {"execute": "os.system('rm')"},  # unknown key
        {"lookback": [1, 2, 3]},  # non-scalar value
        {"min_touches": 999},  # out of whitelisted range
        {"tolerance": 0.5},  # above the 0.1 max
    ):
        condition = StrategyCondition(
            definition=definition,
            kind=str(ConditionKind.REQUIRED),
            label="bad",
            params=bad,
        )
        with pytest.raises(ValidationError):
            condition.clean()


def test_valid_condition_params_pass_validation(category, version):
    definition = make_definition(category, version)
    condition = StrategyCondition(
        definition=definition,
        kind=str(ConditionKind.REQUIRED),
        label="Long lower wick",
        params={"min_wick_ratio": 0.55, "max_body_ratio": 0.4, "lookback": 2},
    )
    condition.clean()  # must not raise


def test_experimental_definitions_are_labelled_and_never_active(category, version):
    experimental = make_definition(
        category,
        version,
        strategy_id="cs.experimental",
        name="Experimental variant",
        status=ValidationStatus.EXPERIMENTAL,
        enabled=True,
    )
    assert experimental.status_label == "Experimental (not validated)"
    assert experimental.is_active is False

    disabled = make_definition(
        category, version, strategy_id="cs.disabled", name="Disabled one", enabled=False
    )
    assert disabled.status_label == "Disabled"

    approved = make_definition(category, version)
    assert approved.status_label == "Approved"
    assert approved.is_active is True


# ---------------------------------------------------------------------------
# CP8 — registry: definitions reference detectors, never expressions
# ---------------------------------------------------------------------------
def test_registry_runs_known_key_and_ignores_everything_else():
    observation = run_detector("cs.bullish_engulfing", ENGULFING, config=CONFIG)
    assert observation is not None
    assert observation["detector"] == "cs.bullish_engulfing"
    # The same candles do not satisfy the mirrored detector.
    assert run_detector("cs.bearish_engulfing", ENGULFING, config=CONFIG) is None
    # Unknown / expression-like keys are inert.
    assert run_detector("evil.run_code", ENGULFING, config=CONFIG) is None
    assert run_detector("__import__", ENGULFING, config=CONFIG) is None


# ---------------------------------------------------------------------------
# CP9 — candidate mapper: deterministic translation of vision output
# ---------------------------------------------------------------------------
def test_build_candidates_maps_a_vision_pattern_to_its_definition(category, version, user):
    definition = make_definition(category, version)
    StrategyPatternLabel.objects.create(label="bullish_engulfing", definition=definition)
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))

    candidates = build_candidates(analysis)
    match = [c for c in candidates if c.strategy_id == definition.strategy_id]
    assert match, "the vision 'bullish engulfing' pattern must map to the definition"
    candidate = match[0]
    assert candidate.provenance == str(EvidenceProvenance.VISION)
    assert candidate.requires_ohlc_confirmation is True
    assert candidate.source_kind == "pattern"


def test_unmapped_vision_records_never_invent_candidates(category, version, user):
    # A definition exists but no pattern label links it to the vision output.
    make_definition(category, version)
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))
    assert build_candidates(analysis) == []


# ---------------------------------------------------------------------------
# CP9 — deterministic verification (DETECTED / POSSIBLE / REJECTED / INSUFFICIENT)
# ---------------------------------------------------------------------------
def test_verification_detects_only_when_the_detector_confirms(category, version, user):
    definition = make_definition(category, version)
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))

    service = PatternVerificationService(config=CONFIG)
    results = service.verify(analysis, [make_candidate(definition)], candles=ENGULFING)

    result = results[0]
    assert result.status == str(DetectionStatus.DETECTED)
    assert result.ohlc_confirmed is True
    assert result.provenance == str(EvidenceProvenance.OHLC)
    assert result.detector_observation["detector"] == "cs.bullish_engulfing"
    # The detection is persisted and auditable.
    detection = analysis.strategy_detections.get()
    assert detection.definition_version == definition.version.version
    assert detection.metadata["knowledge_validation_status"] == str(ValidationStatus.APPROVED)
    assert detection.evidence_items.count() >= 1


def test_verification_rejects_when_the_detector_finds_nothing(category, version, user):
    definition = make_definition(
        category, version, strategy_id="cs.test_bearish", detector_key="cs.bearish_engulfing"
    )
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))

    service = PatternVerificationService(config=CONFIG)
    result = service.verify(analysis, [make_candidate(definition)], candles=ENGULFING)[0]

    assert result.status == str(DetectionStatus.REJECTED)
    assert result.ohlc_confirmed is False
    assert result.provenance == str(EvidenceProvenance.OHLC)


def test_verification_without_candles_never_claims_detection(category, version, user):
    definition = make_definition(category, version)
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))
    service = PatternVerificationService(config=CONFIG)

    with_confidence = service.verify(
        analysis, [make_candidate(definition, confidence=0.5)], candles=None
    )[0]
    assert with_confidence.status == str(DetectionStatus.POSSIBLE)
    assert with_confidence.ohlc_confirmed is False
    assert "verified OHLC candles" in with_confidence.missing_conditions

    no_confidence = service.verify(
        analysis, [make_candidate(definition, confidence=None)], candles=None
    )[0]
    assert no_confidence.status == str(DetectionStatus.INSUFFICIENT)


def test_otc_screenshot_is_never_confirmed_with_normal_session_prices(category, version, user):
    definition = make_definition(category, version)
    screenshot = make_screenshot(user)
    payload = full_payload()
    payload["chart_metadata"]["otc_status"] = "otc"
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=payload))

    service = PatternVerificationService(config=CONFIG)
    result = service.verify(analysis, [make_candidate(definition)], candles=ENGULFING)[0]

    assert result.status == str(DetectionStatus.POSSIBLE)  # capped, never detected
    assert result.otc_incompatible is True
    assert result.provenance == str(EvidenceProvenance.SCREENSHOT_ONLY)
    assert "OTC" in result.summary


def test_verification_carries_invalidation_conditions_from_the_definition(category, version, user):
    definition = make_definition(category, version)
    StrategyCondition.objects.create(
        definition=definition,
        kind=str(ConditionKind.INVALIDATION),
        order=0,
        label="Close back below the pin low",
    )
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))

    service = PatternVerificationService(config=CONFIG)
    result = service.verify(analysis, [make_candidate(definition)], candles=ENGULFING)[0]
    assert result.invalidation == ["Close back below the pin low"]


# ---------------------------------------------------------------------------
# CP10 — de-duplication and the multi-strategy pipeline
# ---------------------------------------------------------------------------
def test_overlapping_candidates_are_grouped_not_double_counted(category, version):
    definition = make_definition(category, version)
    a = make_candidate(definition, refs=[1, 2], label="bullish_engulfing")
    b = make_candidate(definition, refs=[2, 3], label="bullish_engulfing")

    groups = dedupe_candidates([a, b])
    assert len(groups) == 1
    assert groups[0].primary is a
    assert [c.strategy_id for c in groups[0].related] == [definition.strategy_id]
    assert groups[0].overlap_reason == "shared_candles"


def test_disjoint_candidates_stay_separate(category, version):
    definition = make_definition(category, version)
    a = make_candidate(definition, refs=[0])
    b = make_candidate(definition, refs=[5])
    groups = dedupe_candidates([a, b])
    assert len(groups) == 2
    assert all(not g.related for g in groups)


def test_recognition_pipeline_persists_one_deduped_detection(category, version, user):
    definition = make_definition(category, version)
    StrategyPatternLabel.objects.create(label="bullish_engulfing", definition=definition)
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))

    outcome = MultiStrategyRecognitionService(config=CONFIG).recognize(analysis, candles=ENGULFING)

    assert outcome.candidate_count == 1
    assert outcome.group_count == 1
    assert len(outcome.results) == 1
    assert outcome.results[0].status == str(DetectionStatus.DETECTED)
    assert analysis.strategy_detections.count() == 1


def test_recognition_labels_experimental_definitions(category, version, user):
    definition = make_definition(
        category,
        version,
        strategy_id="cs.experimental_engulfing",
        name="Experimental engulfing",
        status=ValidationStatus.EXPERIMENTAL,
    )
    StrategyPatternLabel.objects.create(label="bullish_engulfing", definition=definition)
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))

    outcome = MultiStrategyRecognitionService(config=CONFIG).recognize(analysis)
    assert outcome.results
    assert any("experimental" in note for note in outcome.notes)
    detection = analysis.strategy_detections.get()
    assert detection.metadata["knowledge_validation_status"] == str(ValidationStatus.EXPERIMENTAL)


# ---------------------------------------------------------------------------
# CP11 — retrieval + assistant knowledge context
# ---------------------------------------------------------------------------
def test_retrieval_returns_only_enabled_reviewed_or_approved(category, version):
    approved = make_definition(category, version)
    StrategyCondition.objects.create(
        definition=approved,
        kind=str(ConditionKind.REQUIRED),
        order=0,
        label="Prior bearish candle",
    )
    StrategyCondition.objects.create(
        definition=approved,
        kind=str(ConditionKind.INVALIDATION),
        order=0,
        label="Close back below the engulfed body",
    )
    make_definition(
        category,
        version,
        strategy_id="cs.draft_hammer",
        name="Draft hammer notes",
        detector_key="cs.hammer",
        status=ValidationStatus.DRAFT,
    )
    make_definition(
        category,
        version,
        strategy_id="cs.experimental_hammer",
        name="Experimental hammer notes",
        detector_key="cs.hammer",
        status=ValidationStatus.EXPERIMENTAL,
    )

    service = KnowledgeRetrievalService()
    results = service.retrieve("hammer")
    assert results == [], "draft and experimental definitions must not be retrieved"

    approved_hits = service.retrieve("engulfing")
    assert [r.strategy_id for r in approved_hits] == [approved.strategy_id]
    hit = approved_hits[0]
    assert hit.required_conditions == ["Prior bearish candle"]
    assert hit.invalidation_conditions == ["Close back below the engulfed body"]
    assert hit.status_label == "Approved"

    with_experimental = service.retrieve("hammer", include_experimental=True)
    assert with_experimental[0].strategy_id == "cs.experimental_hammer"
    assert with_experimental[0].status_label == "Experimental (not validated)"
    # Everything returned carries an explicit non-approved status label.
    assert all(r.status_label != "Approved" for r in with_experimental)


def test_assistant_knowledge_context_is_stored_knowledge_and_bounded(category, version, user):
    definition = make_definition(category, version)
    StrategyCondition.objects.create(
        definition=definition,
        kind=str(ConditionKind.REQUIRED),
        order=0,
        label="Prior bearish candle",
    )
    service = AssistantService()

    context = service._knowledge_context("is this an engulfing", {})
    assert definition.strategy_id in context
    assert "Approved" in context
    assert len(context) <= MAX_KNOWLEDGE_CONTEXT_CHARS


def test_assistant_knowledge_context_is_empty_without_reviewed_knowledge(category, version, user):
    make_definition(category, version, status=ValidationStatus.DRAFT)
    service = AssistantService()
    assert service._knowledge_context("is this an engulfing", {}) == ""


def test_follow_up_receives_knowledge_context(category, version, user):
    definition = make_definition(category, version)
    StrategyCondition.objects.create(
        definition=definition,
        kind=str(ConditionKind.REQUIRED),
        order=0,
        label="Prior bearish candle",
    )

    class CapturingProvider:
        def __init__(self):
            self.requests = []

        def complete(self, request):
            self.requests.append(request)
            return SimpleNamespace(content="stored-knowledge reply")

    service = AssistantService()
    capture = CapturingProvider()
    service.provider = capture
    conversation = service.conversations.create_conversation(user, title="cp11")

    service.handle_follow_up(user, conversation.pk, "is this an engulfing")

    assert capture.requests, "the provider must have been called"
    context = capture.requests[-1].context
    assert "strategy_knowledge" in context
    assert definition.strategy_id in context["strategy_knowledge"]


# ---------------------------------------------------------------------------
# CP12 — dashboard pages
# ---------------------------------------------------------------------------
def test_strategy_library_page_lists_and_labels_definitions(client, category, version):
    make_definition(category, version)
    make_definition(
        category,
        version,
        strategy_id="cs.experimental_page",
        name="Experimental on page",
        detector_key="cs.hammer",
        status=ValidationStatus.EXPERIMENTAL,
    )

    client.force_login(UserFactory())
    response = client.get("/dashboard/strategies/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Bullish engulfing setup" in content
    assert "Experimental on page" in content
    assert "Experimental" in content and "not validated" in content


def test_strategy_library_requires_login(client):
    response = client.get("/dashboard/strategies/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_strategy_detail_page_shows_conditions(client, category, version):
    definition = make_definition(category, version)
    StrategyCondition.objects.create(
        definition=definition,
        kind=str(ConditionKind.REQUIRED),
        order=0,
        label="Prior bearish candle",
    )
    client.force_login(UserFactory())
    response = client.get(f"/dashboard/strategies/{definition.strategy_id}/")
    assert response.status_code == 200
    assert "Prior bearish candle" in response.content.decode()


def test_strategy_detail_unknown_id_is_404(client, user):
    client.force_login(user)
    response = client.get("/dashboard/strategies/cs.no_such_strategy/")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# CP13 — annotation never modifies the original screenshot
# ---------------------------------------------------------------------------
def test_annotation_draws_only_reliable_boxes_and_keeps_original_bytes(category, version, user):
    screenshot = make_screenshot(user)
    with screenshot.image.open() as fh:
        original = fh.read()

    candles = [
        {"high_px": 10, "low_px": 50, "body_top_px": 15, "body_bottom_px": 45},
        {"high_px": 12},  # incomplete pixel box: must stay text-only
    ]
    result = annotate_screenshot(
        screenshot,
        detections=[
            {
                "strategy_id": "cs.bullish_engulfing",
                "direction": "bullish",
                "candle_refs": [0, 1, 99],
            }
        ],
        candles=candles,
    )

    with screenshot.image.open() as fh:
        assert fh.read() == original, "the original screenshot bytes must be untouched"

    drawn = [a for a in result.annotations if a.drawn]
    text_only = [a for a in result.annotations if not a.drawn]
    assert len(drawn) == 1 and drawn[0].candle_index == 0
    assert {a.candle_index for a in text_only} == {1, 99}
    assert result.text_explanation


def test_annotation_without_reliable_boxes_returns_text_explanation(user):
    screenshot = make_screenshot(user)
    with screenshot.image.open() as fh:
        original = fh.read()

    result = annotate_screenshot(
        screenshot,
        detections=[{"strategy_id": "cs.doji", "direction": "neutral", "candle_refs": [0]}],
        candles=[{"high_px": 10}],
    )

    with screenshot.image.open() as fh:
        assert fh.read() == original
    assert result.drew_anything is False
    assert result.notes
    assert result.text_explanation


# ---------------------------------------------------------------------------
# CP14 — dataset workflow: reviewer labels are the only ground truth
# ---------------------------------------------------------------------------
def test_candidate_sample_is_not_ground_truth_until_reviewed(category, version, user):
    definition = make_definition(category, version)
    screenshot = make_screenshot(user)
    workflow = StrategyDatasetWorkflow()

    sample = workflow.add_candidate(screenshot, label="bullish_engulfing", definition=definition)
    assert sample.label_source == str(LabelSource.VISION_CANDIDATE)
    assert sample.reviewer_approved is False
    assert list(workflow.ground_truth("0")) == []
    assert sample in workflow.pending_review()

    workflow.approve(sample, user)
    sample.refresh_from_db()
    assert sample.label_source == str(LabelSource.REVIEWER)
    assert sample.reviewer_approved is True
    assert sample in workflow.ground_truth("0")
    assert sample not in workflow.pending_review()


def test_approval_with_corrected_label_keeps_prior_text(category, version, user):
    make_definition(category, version)
    screenshot = make_screenshot(user)
    workflow = StrategyDatasetWorkflow()
    sample = workflow.add_candidate(screenshot, label="bullish_engulfing")

    workflow.approve(sample, user, label="hammer")
    sample.refresh_from_db()
    assert sample.label == "hammer"
    assert "[prior candidate label: bullish_engulfing]" in sample.notes


def test_invalid_dataset_transitions_raise(category, version, user):
    make_definition(category, version)
    screenshot = make_screenshot(user)
    workflow = StrategyDatasetWorkflow()

    with pytest.raises(DatasetWorkflowError):
        workflow.add_candidate(screenshot, label="x", sample_kind="not_a_kind")

    sample = workflow.add_candidate(screenshot, label="bullish_engulfing")
    with pytest.raises(DatasetWorkflowError):
        workflow.approve(sample, None)
    with pytest.raises(DatasetWorkflowError):
        workflow.reject(sample, None)
    with pytest.raises(DatasetWorkflowError):
        workflow.approve(sample, user, label_confidence=1.5)

    rejected = workflow.reject(sample, user, notes="blurry screenshot")
    assert rejected.reviewer_approved is False
    assert "blurry screenshot" in rejected.notes


def test_poor_quality_and_otc_are_first_class_sample_kinds(category, version, user):
    definition = make_definition(category, version)
    screenshot = make_screenshot(user)
    workflow = StrategyDatasetWorkflow()

    workflow.add_candidate(
        screenshot,
        label="unusable",
        definition=definition,
        sample_kind=DatasetSampleKind.POOR_QUALITY,
    )
    workflow.add_candidate(
        screenshot, label="otc_only", definition=definition, sample_kind=DatasetSampleKind.OTC
    )

    summary = workflow.summary("0")
    assert summary["total"] == 2
    assert summary["by_kind"]["poor_quality"] == 1
    assert summary["by_kind"]["otc"] == 1
    assert summary["pending_review"] == 2


# ---------------------------------------------------------------------------
# CP15 — detection metrics: honest counts, never fabricated accuracy
# ---------------------------------------------------------------------------
def test_metrics_never_fabricate_rates_from_an_empty_dataset():
    report = DetectionMetricsService().compute("empty-version")
    assert report["metric_scope"] == "pattern_detection"
    assert "NOT" in report["disclaimer"]
    overall = report["overall"]
    assert overall["tp"] == overall["fp"] == overall["fn"] == 0
    assert overall["precision"] is None
    assert overall["recall"] is None, "undefined recall must be None, never 100%"


def test_metrics_use_reviewer_labels_only(category, version, user):
    definition = make_definition(category, version)
    other = make_definition(
        category, version, strategy_id="cs.other", name="Other", detector_key="cs.hammer"
    )
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))
    workflow = StrategyDatasetWorkflow()

    # Reviewer-approved positive sample -> ground truth.
    approved = workflow.add_candidate(screenshot, label="bullish_engulfing", definition=definition)
    workflow.approve(approved, user)
    approved.dataset_version = "v1"
    approved.save()

    # Vision-candidate-only sample -> must never count as ground truth.
    unverified = workflow.add_candidate(screenshot, label="hammer", definition=other)
    unverified.dataset_version = "v1"
    unverified.save()

    # The recogniser detected the approved strategy on this analysis.
    StrategyDetection.objects.create(
        analysis=analysis,
        definition=definition,
        status=str(DetectionStatus.DETECTED),
        direction="bullish",
        provenance=str(EvidenceProvenance.OHLC),
    )

    report = DetectionMetricsService().compute("v1")
    overall = report["overall"]
    assert overall["tp"] == 1
    assert overall["fp"] == 0
    assert overall["precision"] == 1.0
    assert overall["recall"] == 1.0
    strategy_ids = {row["strategy_id"] for row in report["per_strategy"]}
    assert strategy_ids == {definition.strategy_id}, "unverified labels never count"
    assert report["ground_truth_source"] == "reviewer_approved_labels_only"


def test_metrics_report_none_recall_when_no_positive_ground_truth_exists(category, version, user):
    definition = make_definition(category, version)
    screenshot = make_screenshot(user)
    analysis = run_analysis(screenshot, StaticVisionProvider(payload=full_payload()))
    workflow = StrategyDatasetWorkflow()

    negative = workflow.add_candidate(
        screenshot,
        label="not_an_engulfing",
        definition=definition,
        sample_kind=DatasetSampleKind.NEGATIVE,
    )
    workflow.approve(negative, user)
    negative.dataset_version = "v2"
    negative.save()

    StrategyDetection.objects.create(
        analysis=analysis,
        definition=definition,
        status=str(DetectionStatus.DETECTED),
        direction="bullish",
        provenance=str(EvidenceProvenance.OHLC),
    )

    report = DetectionMetricsService().compute("v2")
    overall = report["overall"]
    assert overall["fp"] == 1  # claimed where ground truth says negative
    assert overall["recall"] is None  # no ground-truth positive: undefined
    assert "recall is None" in report["interpretation_note"]
