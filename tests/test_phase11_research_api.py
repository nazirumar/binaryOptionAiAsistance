# tests/test_phase11_research_api.py
"""Phase 11 CP3 — research APIs read persisted, owner-scoped truth.

The Phase-10 audit found placeholder endpoints: ``GET /backtests/<pk>/``
answered ``{"id": pk}`` for *any* id (IDOR-shaped), lists were always empty
and performance/calibration returned static shells. These tests pin the
replacements:

* datasets/backtests/models lists are paginated and owner-scoped (plus the
  intentionally shared ownerless datasets — nothing else leaks);
* backtest detail 404s across owners and returns the real stored run;
* ``POST /backtests/`` queues the real task against an owned/shared dataset;
* performance reflects exactly the stored rows — including honest
  ``accuracy_status`` values, never computed or invented metrics;
* calibration reads "unavailable_uncalibrated" without approved evidence and
  exposes the persisted evidence fields with it;
* the registry never serialises ``model_data`` internals and never accepts
  an approval flag from anywhere but the database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.research.models import BacktestRun, CalibratedModel, HistoricalDataset

User = get_user_model()

BASE = "/api/research/"
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(days=7)


def _dataset(owner, *, name="ds", instrument="EURUSD"):
    return HistoricalDataset.objects.create(
        owner=owner,
        name=name,
        instrument=instrument,
        timeframe="M1",
        market_type="forex",
        start_time=EARLIER,
        end_time=NOW,
        candle_count=1440,
        source="mt5",
        is_validated=True,
    )


def _run(owner, *, name="run", status="completed", metrics=None, sample_count=0):
    return BacktestRun.objects.create(
        owner=owner,
        name=name,
        status=status,
        metrics=metrics or {},
        sample_count=sample_count,
    )


class ResearchApiTestBase(TestCase):
    def setUp(self):
        cache.clear()  # keep DRF's locmem throttle cache from leaking across tests
        self.user = User.objects.create_user("res-user", "pw")
        self.other = User.objects.create_user("res-other", "pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)


class DatasetApiTests(ResearchApiTestBase):
    def test_list_is_paginated_owner_scoped_plus_shared(self):
        mine = _dataset(self.user, name="mine")
        shared = _dataset(None, name="shared")
        _dataset(self.other, name="theirs")

        resp = self.client.get(BASE + "datasets/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("count", body)
        self.assertIn("results", body)
        names = {row["name"] for row in body["results"]}
        self.assertEqual(names, {"mine", "shared"})
        self.assertEqual(body["count"], 2)
        self.assertIn(mine.pk, [row["id"] for row in body["results"]])
        self.assertIn(shared.pk, [row["id"] for row in body["results"]])

    def test_detail_scoping(self):
        mine = _dataset(self.user, name="mine")
        shared = _dataset(None, name="shared")
        foreign = _dataset(self.other, name="theirs")

        self.assertEqual(self.client.get(f"{BASE}datasets/{mine.pk}/").status_code, 200)
        self.assertEqual(self.client.get(f"{BASE}datasets/{shared.pk}/").status_code, 200)
        self.assertEqual(self.client.get(f"{BASE}datasets/{foreign.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"{BASE}datasets/999999/").status_code, 404)

    def test_detail_returns_persisted_fields_only(self):
        dataset = _dataset(self.user)
        body = self.client.get(f"{BASE}datasets/{dataset.pk}/").json()
        self.assertEqual(body["instrument"], "EURUSD")
        self.assertEqual(body["timeframe"], "M1")
        self.assertEqual(body["candle_count"], 1440)
        self.assertTrue(body["is_validated"])


class BacktestApiTests(ResearchApiTestBase):
    def test_list_shows_only_own_runs(self):
        mine = _run(self.user, name="mine")
        _run(self.other, name="theirs")

        body = self.client.get(BASE + "backtests/").json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["id"], mine.pk)
        self.assertEqual(body["results"][0]["name"], "mine")

    def test_detail_no_longer_echoes_any_id(self):
        """D-defect regression: the stub returned {id} for arbitrary ids."""
        mine = _run(
            self.user,
            name="measured",
            metrics={"directional_accuracy": 0.61, "accuracy_status": "measured"},
            sample_count=320,
        )
        foreign = _run(self.other, name="theirs")

        mine_resp = self.client.get(f"{BASE}backtests/{mine.pk}/")
        self.assertEqual(mine_resp.status_code, 200)
        body = mine_resp.json()
        self.assertEqual(body["name"], "measured")
        self.assertEqual(body["sample_count"], 320)
        self.assertEqual(body["metrics"]["accuracy_status"], "measured")

        self.assertEqual(self.client.get(f"{BASE}backtests/{foreign.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"{BASE}backtests/424242/").status_code, 404)

    def test_create_queues_real_task_against_own_dataset(self):
        dataset = _dataset(self.user)
        resp = self.client.post(
            BASE + "backtests/",
            {"dataset_id": dataset.pk, "name": "r1", "strategy": "trend"},
            format="json",
        )
        self.assertEqual(resp.status_code, 202, resp.content)
        body = resp.json()
        run = BacktestRun.objects.get(pk=body["id"])
        self.assertEqual(run.owner, self.user)
        self.assertEqual(run.dataset, dataset)
        self.assertEqual(run.strategy_config["strategy"], "trend")
        self.assertEqual(run.strategy_config["instrument"], "EURUSD")
        # Eager Celery executed the real task: the persisted state is
        # terminal (or still pending) — never a fabricated success.
        self.assertIn(run.status, ("pending", "running", "completed", "failed"))
        self.assertEqual(body["status"], run.status)

    def test_create_accepts_shared_dataset_but_not_foreign(self):
        shared = _dataset(None, name="shared")
        resp = self.client.post(BASE + "backtests/", {"dataset_id": shared.pk}, format="json")
        self.assertEqual(resp.status_code, 202)

        foreign = _dataset(self.other, name="theirs")
        resp = self.client.post(BASE + "backtests/", {"dataset_id": foreign.pk}, format="json")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(BacktestRun.objects.filter(owner=self.other).count(), 0)

    def test_create_requires_dataset_id(self):
        resp = self.client.post(BASE + "backtests/", {}, format="json")
        self.assertEqual(resp.status_code, 400)


class PerformanceApiTests(ResearchApiTestBase):
    def test_reports_exactly_the_stored_rows(self):
        _run(
            self.user,
            name="a",
            status="completed",
            metrics={"directional_accuracy": 0.61, "accuracy_status": "measured"},
            sample_count=320,
        )
        _run(
            self.user,
            name="b",
            status="completed",
            metrics={"accuracy_status": "not_evaluated", "accuracy_note": "single side"},
            sample_count=17,
        )
        _run(self.user, name="c", status="failed")
        _run(self.other, name="foreign", metrics={"directional_accuracy": 0.99})

        body = self.client.get(BASE + "performance/").json()
        self.assertEqual(body["runs_total"], 3)
        self.assertEqual(body["status_counts"], {"completed": 2, "failed": 1})
        self.assertEqual(sorted(int(v) for v in body["sample_counts"].values()), [0, 17, 320])
        # Honest accuracy statuses travel through untouched.
        accuracies = [m.get("directional_accuracy") for m in body["metrics"].values()]
        self.assertIn(0.61, accuracies)
        self.assertIn(None, accuracies)  # not_evaluated row carries no number
        # Another user's 0.99 must never appear here.
        self.assertNotIn(0.99, accuracies)

    def test_empty_state_is_honest(self):
        body = self.client.get(BASE + "performance/").json()
        self.assertEqual(body["runs_total"], 0)
        self.assertEqual(body["status_counts"], {})
        self.assertEqual(body["sample_counts"], {})
        self.assertEqual(body["metrics"], {})


class CalibrationApiTests(ResearchApiTestBase):
    def test_without_approved_model_reads_unavailable(self):
        body = self.client.get(BASE + "calibration/").json()
        self.assertFalse(body["calibrated"])
        self.assertEqual(body["status"], "unavailable_uncalibrated")
        self.assertEqual(body["models_total"], 0)

    def test_unapproved_or_inactive_model_is_not_calibration(self):
        CalibratedModel.objects.create(
            owner=self.user,
            name="draft",
            version="v0",
            is_active=True,
            is_approved=False,
            calibration_method="isotonic",
            brier_score=0.2,
            calibration_error=0.05,
        )
        CalibratedModel.objects.create(
            owner=self.user,
            name="retired",
            version="v9",
            is_active=False,
            is_approved=True,  # approved but inactive
            calibration_method="isotonic",
            brier_score=0.2,
            calibration_error=0.05,
        )
        body = self.client.get(BASE + "calibration/").json()
        self.assertFalse(body["calibrated"])
        self.assertEqual(body["status"], "unavailable_uncalibrated")
        self.assertEqual(body["models_total"], 2)

    def test_approved_active_model_exposes_persisted_evidence(self):
        CalibratedModel.objects.create(
            owner=self.other,
            name="foreign",
            version="vx",
            is_active=True,
            is_approved=True,
            calibration_method="isotonic",
            brier_score=0.1,
            calibration_error=0.01,
        )  # another user's model must not calibrate this account
        CalibratedModel.objects.create(
            owner=self.user,
            name="next-candle",
            version="v3",
            is_active=True,
            is_approved=True,
            calibration_method="isotonic",
            brier_score=0.20,
            calibration_error=0.05,
            evaluation_metrics={
                "prediction_target": "next_candle_directional",
                "sample_count": 500,
            },
        )

        body = self.client.get(BASE + "calibration/").json()
        self.assertTrue(body["calibrated"])
        self.assertEqual(body["status"], "calibrated")
        self.assertEqual(body["model_version"], "v3")
        self.assertEqual(body["calibration_method"], "isotonic")
        self.assertEqual(body["brier_score"], 0.20)
        self.assertEqual(body["calibration_error"], 0.05)
        self.assertEqual(body["evaluation_metrics"]["sample_count"], 500)
        self.assertEqual(body["models_total"], 1)  # only own rows counted


class ModelRegistryApiTests(ResearchApiTestBase):
    def test_registry_is_paginated_scoped_and_hides_model_data(self):
        CalibratedModel.objects.create(
            owner=self.user,
            name="mine",
            version="v1",
            is_active=True,
            is_approved=True,
            calibration_method="isotonic",
            brier_score=0.2,
            calibration_error=0.05,
            model_data={"probability": 0.63, "instrument": "EURUSD"},
        )
        CalibratedModel.objects.create(
            owner=self.other,
            name="theirs",
            version="v1",
            is_active=True,
            is_approved=True,
            calibration_method="platt",
            brier_score=0.3,
            calibration_error=0.1,
        )

        body = self.client.get(BASE + "models/").json()
        self.assertIn("count", body)
        self.assertEqual(body["count"], 1)
        row = body["results"][0]
        self.assertEqual(row["name"], "mine")
        self.assertEqual(row["version"], "v1")
        self.assertTrue(row["is_approved"])
        self.assertEqual(row["brier_score"], 0.2)
        # Model internals are never serialised to the registry.
        self.assertNotIn("model_data", row)
        # And no approval is ever *derived* from the request: GET has no
        # write path at all (405 on POST).
        self.assertEqual(self.client.post(BASE + "models/", {}).status_code, 405)

    def test_unauthenticated_rejected(self):
        anon = APIClient()
        self.assertIn(anon.get(BASE + "models/").status_code, (401, 403))
        self.assertIn(anon.get(BASE + "calibration/").status_code, (401, 403))
        self.assertIn(anon.get(BASE + "backtests/").status_code, (401, 403))
