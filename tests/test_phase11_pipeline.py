# tests/test_phase11_pipeline.py
"""Phase 11 CP1 + CP7 — screenshot upload → durable job → assessment.

Proves the *real* pipeline end to end through the public API:

* a multipart screenshot upload dispatches one durable ``AIAnalysisJob``
  (eager in tests) that runs vision → MT5 verification → trusted input →
  evaluation, and returns the structured assessment;
* idempotency: the same (user, screenshot, mode) submission never creates a
  second job — replays return the original (200, not 201);
* forged trusted verdicts in the request body are ignored (server-derived
  sync evidence only);
* ownership is enforced on screenshot references and job endpoints;
* invalid images are rejected with a machine-readable code;
* educational mode (CP7) can never present a trade assessment or a
  probability — in any code path;
* probability (CP9-J): no approved compatible model -> value ``None`` +
  the exact calibration notice; approved compatible model -> the calibrated
  value with the explicit next-candle type.

Every stage reuses existing services; the pipeline is composition, not a
second engine. No live network: the vision provider is a local static fake.
"""

from __future__ import annotations

import unittest.mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.ai_assistant.models import AIAnalysisJob, AIAnalysisSession
from apps.ai_assistant.services.probability_presenter import (
    PROBABILITY_UNAVAILABLE_MESSAGE,
)
from apps.chart_vision.services.screenshot_analyzer import ScreenshotAnalyzer
from apps.research.models import CalibratedModel
from tests.vision_fakes import (
    StaticVisionProvider,
    full_payload,
    make_screenshot,
    uploaded_file,
)

User = get_user_model()

ANALYZE_URL = "/api/assistant/analyze/"


def _patch_analyzer(testcase: TestCase, payload: dict | None = None) -> None:
    """Run the pipeline's vision stage against a fixed, schema-valid payload."""
    patcher = unittest.mock.patch(
        "apps.ai_assistant.services.screenshot_pipeline.ScreenshotAnalyzer",
        lambda: ScreenshotAnalyzer(provider=StaticVisionProvider(payload=payload)),
    )
    patcher.start()
    testcase.addCleanup(patcher.stop)


class AnalyzeApiTests(TestCase):
    def setUp(self):
        cache.clear()  # keep DRF's locmem throttle cache from leaking across tests
        self.user = User.objects.create_user("cp1-user", "pw")
        self.other = User.objects.create_user("cp1-other", "pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _post(self, data):
        return self.client.post(ANALYZE_URL, data, format="multipart")

    # -- happy path --------------------------------------------------------

    def test_upload_returns_completed_job_with_structured_assessment(self):
        _patch_analyzer(self)
        resp = self._post({"screenshot": uploaded_file(), "title": "my chart"})
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()

        job = AIAnalysisJob.objects.get(pk=body["id"])
        self.assertEqual(body["status"], AIAnalysisJob.Status.COMPLETED)
        self.assertEqual(job.owner, self.user)
        self.assertIsNotNone(job.conversation)
        self.assertIsNotNone(job.session)

        summary = body["result_summary"]
        # No MT5 reference candles in this scenario: the unverifiable case
        # must be NO TRADE with provenance declared — never a guess.
        self.assertEqual(summary["direction"], "NO TRADE")
        self.assertIn(
            summary["sync_evidence"]["candle_provenance"],
            ("none", "stored_mt5", "client_supplied"),
        )
        self.assertIn("probability_value", summary)
        self.assertIsNone(summary["probability_value"])
        self.assertFalse(summary["sync_evidence"]["verified"])

        # The analysis session is persisted and linked to the conversation.
        conversation = job.conversation
        self.assertIsNotNone(conversation.screenshot_analysis_id)
        self.assertTrue(AIAnalysisSession.objects.filter(pk=job.session_id).exists())

    def test_reference_submission_is_idempotent(self):
        _patch_analyzer(self)
        screenshot = make_screenshot(self.user)

        first = self._post({"screenshot_id": screenshot.pk})
        second = self._post({"screenshot_id": screenshot.pk})

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)  # replay, not a new job
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(AIAnalysisJob.objects.count(), 1)

    def test_different_mode_dispatches_a_separate_job(self):
        _patch_analyzer(self)
        screenshot = make_screenshot(self.user)

        std = self._post({"screenshot_id": screenshot.pk})
        edu = self._post({"screenshot_id": screenshot.pk, "educational": "true"})

        self.assertEqual(std.status_code, 201)
        self.assertEqual(edu.status_code, 201)
        self.assertNotEqual(std.json()["id"], edu.json()["id"])
        self.assertEqual(AIAnalysisJob.objects.count(), 2)

    # -- validation & ownership -------------------------------------------

    def test_exactly_one_screenshot_source_is_required(self):
        none_resp = self._post({"title": "empty"})
        self.assertEqual(none_resp.status_code, 400)

        screenshot = make_screenshot(self.user)
        both_resp = self._post({"screenshot": uploaded_file(), "screenshot_id": screenshot.pk})
        self.assertEqual(both_resp.status_code, 400)

    def test_invalid_image_bytes_rejected_with_code(self):
        resp = self._post({"screenshot": uploaded_file(data=b"definitely not a png")})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "invalid_image")

    def test_cross_user_screenshot_reference_is_404(self):
        foreign = make_screenshot(self.other)
        resp = self._post({"screenshot_id": foreign.pk})
        self.assertEqual(resp.status_code, 404)

    def test_job_endpoints_are_owner_scoped(self):
        _patch_analyzer(self)
        body = self._post({"screenshot": uploaded_file()}).json()
        job_id = body["id"]

        mine = self.client.get(f"/api/assistant/jobs/{job_id}/")
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(mine.json()["id"], job_id)

        intruder = APIClient()
        intruder.force_authenticate(self.other)
        self.assertEqual(intruder.get(f"/api/assistant/jobs/{job_id}/").status_code, 404)
        self.assertEqual(intruder.post(f"/api/assistant/jobs/{job_id}/cancel/").status_code, 404)

    def test_completed_job_cannot_be_cancelled(self):
        _patch_analyzer(self)
        body = self._post({"screenshot": uploaded_file()}).json()
        resp = self.client.post(f"/api/assistant/jobs/{body['id']}/cancel/")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["code"], "already_terminal")

    def test_pending_job_can_be_cancelled(self):
        screenshot = make_screenshot(self.user)
        job = AIAnalysisJob.objects.create(
            owner=self.user,
            screenshot=screenshot,
            idempotency_key="analyze:cancel-me",
        )
        resp = self.client.post(f"/api/assistant/jobs/{job.pk}/cancel/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["cancelled"])
        job.refresh_from_db()
        self.assertEqual(job.status, "cancelled")

    # -- forgery resistance -------------------------------------------------

    def test_forged_trusted_fields_in_body_are_ignored(self):
        _patch_analyzer(self)
        resp = self._post(
            {
                "screenshot": uploaded_file(),
                # Forged "trusted" verdicts:
                "sync_status": "verified_alignment",
                "feed_compatibility": "compatible",
                "data_freshness": "fresh",
                "market_type": "forex",
                "timing_validity": "valid",
                "calibration_approved": "true",
            }
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        summary = resp.json()["result_summary"]
        evidence = summary["sync_evidence"]
        self.assertNotEqual(evidence["sync_status"], "verified_alignment")
        self.assertFalse(evidence["verified"])
        self.assertEqual(summary["direction"], "NO TRADE")
        self.assertIsNone(summary["probability_value"])

    def test_vision_failure_marks_job_failed_with_stage_code(self):
        failing = unittest.mock.MagicMock()
        failing.analyze.side_effect = RuntimeError("provider exploded")
        patcher = unittest.mock.patch(
            "apps.ai_assistant.services.screenshot_pipeline.ScreenshotAnalyzer",
            lambda: failing,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        resp = self._post({"screenshot": uploaded_file()})
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["status"], "failed")
        job = AIAnalysisJob.objects.get(pk=body["id"])
        self.assertEqual(job.status, "failed")
        self.assertTrue(job.error_message)  # honest failure record, no retry loop

    # -- CP7: educational mode ---------------------------------------------

    def test_educational_mode_never_presents_a_prediction(self):
        _patch_analyzer(self, full_payload())
        resp = self._post({"screenshot": uploaded_file(), "educational": "true"})
        self.assertEqual(resp.status_code, 201, resp.content)
        summary = resp.json()["result_summary"]

        self.assertEqual(summary["direction"], "EDUCATIONAL")
        self.assertTrue(summary["educational"])
        self.assertIsNone(summary["probability_value"])
        self.assertIsNone(summary["probability_type"])
        self.assertEqual(summary["calibration_status"], "not_applicable_educational")
        self.assertIn("not a trade assessment", summary["explanation"])
        self.assertIn("contains no prediction", summary["explanation"])
        # No actionable next-candle claim anywhere in the payload text.
        text = str(resp.content)
        self.assertNotIn("Direction: UP", text)
        self.assertNotIn("Direction: DOWN", text)
        # The persisted session carries the educational form too.
        session = AIAnalysisSession.objects.get(pk=resp.json()["session"])
        schema = session.response_schema
        self.assertEqual(schema["direction"], "EDUCATIONAL")

    def test_educational_mode_through_early_exit_paths(self):
        """OTC-guard / no-verification early exits stay educational (CP7)."""
        from apps.ai_assistant.models import AIConversation
        from apps.ai_assistant.services.analysis_orchestrator import (
            AnalysisOrchestrator,
        )

        conversation = AIConversation.objects.create(
            owner=self.user, title="edu-early", is_educational=True
        )
        # Early exit: market_type OTC without VERIFIED_ALIGNMENT.
        response = AnalysisOrchestrator().run(
            conversation,
            evaluation_input={"market_type": "OTC", "sync_status": ""},
            educational=True,
        )
        self.assertEqual(response["direction"], "EDUCATIONAL")
        self.assertIsNone(response["probability_value"])
        self.assertEqual(response["calibration_status"], "not_applicable_educational")
        self.assertIn("not a trade assessment", response["explanation"])

    # -- CP9-J: probability availability -----------------------------------

    def test_without_approved_model_probability_is_unavailable(self):
        _patch_analyzer(self, full_payload())
        resp = self._post({"screenshot": uploaded_file()})
        self.assertEqual(resp.status_code, 201, resp.content)
        summary = resp.json()["result_summary"]

        self.assertIsNone(summary["probability_value"])
        self.assertIsNone(summary["probability_type"])
        self.assertEqual(summary["calibration_status"], "uncalibrated")
        self.assertIn(PROBABILITY_UNAVAILABLE_MESSAGE, summary["explanation"])

    def test_with_approved_compatible_model_probability_is_calibrated(self):
        _patch_analyzer(self, full_payload())  # extracts EURUSD / M1
        CalibratedModel.objects.create(
            owner=self.user,
            name="next-candle",
            version="v1",
            is_active=True,
            is_approved=True,
            calibration_method="isotonic",
            brier_score=0.20,
            calibration_error=0.05,
            evaluation_metrics={
                "prediction_target": "next_candle_directional",
                "sample_count": 500,
            },
            model_data={
                "probability": 0.63,
                "instrument": "EURUSD",
                "timeframe": "M1",
                "prediction_target": "next_candle_directional",
            },
        )
        resp = self._post({"screenshot": uploaded_file()})
        self.assertEqual(resp.status_code, 201, resp.content)
        summary = resp.json()["result_summary"]

        self.assertEqual(summary["probability_value"], 0.63)
        self.assertEqual(summary["probability_type"], "next_candle_directional")
        self.assertEqual(summary["calibration_status"], "calibrated")
        self.assertNotIn(PROBABILITY_UNAVAILABLE_MESSAGE, summary["explanation"])

    def test_unapproved_model_is_never_presented(self):
        _patch_analyzer(self, full_payload())
        CalibratedModel.objects.create(
            owner=self.user,
            name="draft",
            version="v0",
            is_active=True,
            is_approved=False,  # not approved
            calibration_method="isotonic",
            brier_score=0.20,
            calibration_error=0.05,
            evaluation_metrics={
                "prediction_target": "next_candle_directional",
                "sample_count": 500,
            },
            model_data={
                "probability": 0.91,
                "instrument": "EURUSD",
                "timeframe": "M1",
                "prediction_target": "next_candle_directional",
            },
        )
        resp = self._post({"screenshot": uploaded_file()})
        summary = resp.json()["result_summary"]
        self.assertIsNone(summary["probability_value"])
        self.assertEqual(summary["calibration_status"], "uncalibrated")


class PipelineServiceTests(TestCase):
    """Direct unit checks on the pipeline's server-side guarantees."""

    def setUp(self):
        cache.clear()  # keep DRF's locmem throttle cache from leaking across tests
        self.user = User.objects.create_user("cp1-svc", "pw")

    def test_lookup_requires_approved_flag(self):
        from apps.ai_assistant.services.screenshot_pipeline import lookup_approved_model

        self.assertIsNone(lookup_approved_model("EURUSD", "M1"))

    def test_json_safe_converts_datetimes_and_non_finite(self):
        from datetime import UTC, datetime

        from apps.ai_assistant.services.screenshot_pipeline import json_safe

        result = json_safe(
            {
                "when": datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
                "bad": float("nan"),
                "inf": float("inf"),
                "nested": [{"t": datetime(2026, 3, 1, 10, 0, tzinfo=UTC)}],
            }
        )
        self.assertEqual(result["when"], "2026-03-01T10:00:00+00:00")
        self.assertIsNone(result["bad"])
        self.assertIsNone(result["inf"])
        self.assertEqual(result["nested"][0]["t"], "2026-03-01T10:00:00+00:00")

    def test_idempotency_key_covers_mode(self):
        from apps.ai_assistant.models import AIAnalysisJob

        std = AIAnalysisJob.make_idempotency_key(1, 2, "v1", False)
        edu = AIAnalysisJob.make_idempotency_key(1, 2, "v1", True)
        self.assertNotEqual(std, edu)
        self.assertEqual(std, AIAnalysisJob.make_idempotency_key(1, 2, "v1", False))

    def test_pipeline_stage_error_records_its_code_on_the_job(self):
        from apps.ai_assistant import tasks
        from apps.ai_assistant.services import screenshot_pipeline as sp

        job = AIAnalysisJob.objects.create(
            owner=self.user,
            screenshot=make_screenshot(self.user),
            idempotency_key="analyze:stage-error",
        )
        with unittest.mock.patch.object(
            sp, "run_job", side_effect=sp.PipelineError("vision_failed", "bad image")
        ):
            result = tasks.run_screenshot_analysis_task.apply(args=(job.pk,))
        self.assertEqual(result.result["status"], "failed")
        self.assertEqual(result.result["error"], "vision_failed")
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error_code, "vision_failed")
        self.assertEqual(job.error_message, "bad image")
