# tests/test_phase10_backtest_reliability.py
"""Phase 10, Steps 5/6 — backtest execution reliability and authorization.

Covers the two defects found by the Phase 10 repository audit:

* ``apps/research/tasks.py`` did not exist, so every ``POST
  /dashboard/backtests/run/`` raised ``ImportError`` (HTTP 500).
* The dataset lookup ignored ownership, letting one user queue a backtest
  against another user's dataset (IDOR).

It also pins the honesty rules for background results: a run that produced no
settled outcomes must never report an accuracy figure.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.research.models import BacktestRun, HistoricalCandle, HistoricalDataset
from apps.research.tasks import MIN_HISTORY, run_backtest_task
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

RUN_URL = "/dashboard/backtests/run/"


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user():
    return UserFactory(username="backtest-owner")


@pytest.fixture
def api(user):
    client = APIClient()
    client.force_login(user)
    return client


def _dataset(owner, *, name="Test series", candle_count: int = 0) -> HistoricalDataset:
    start = timezone.now() - timedelta(days=1)
    return HistoricalDataset.objects.create(
        owner=owner,
        name=name,
        instrument="EURUSD",
        timeframe="M1",
        start_time=start,
        end_time=start + timedelta(hours=1),
        candle_count=candle_count,
        is_validated=True,
    )


def _seed_candles(dataset, count: int) -> None:
    start = dataset.start_time
    candles = [
        HistoricalCandle(
            dataset=dataset,
            open_time=start + timedelta(minutes=index),
            close_time=start + timedelta(minutes=index, seconds=59),
            open=1.1000 + index * 0.0001,
            high=1.1005 + index * 0.0001,
            low=1.0995 + index * 0.0001,
            close=1.1003 + index * 0.0001,
            is_complete=True,
        )
        for index in range(count)
    ]
    HistoricalCandle.objects.bulk_create(candles)


# ---------------------------------------------------------------------------
# Step 1: the queueing view actually works (previously ImportError -> 500)
# ---------------------------------------------------------------------------
def test_backtest_run_queues_without_error(api, user):
    dataset = _dataset(user)

    response = api.post(RUN_URL, {"dataset_id": dataset.pk, "strategy": "sr_rejection"})

    assert response.status_code == 302
    run = BacktestRun.objects.get(owner=user)
    assert run.dataset == dataset
    assert run.status in {"pending", "running", "completed", "failed"}
    assert run.strategy_config["strategy"] == "sr_rejection"


# ---------------------------------------------------------------------------
# Step 2: authorization (IDOR)
# ---------------------------------------------------------------------------
def test_backtest_run_rejects_another_users_dataset(api):
    other = UserFactory(username="backtest-victim")
    stolen = _dataset(other, name="Someone else's data")

    response = api.post(RUN_URL, {"dataset_id": stolen.pk})

    # No run is created for the caller, and the victim's dataset is untouched.
    assert response.status_code == 302
    assert BacktestRun.objects.filter(owner__username="backtest-owner").count() == 0
    assert BacktestRun.objects.filter(dataset=stolen).count() == 0


def test_backtest_run_rejects_malformed_dataset_id(api):
    for bad in ("", "abc", "-1"):
        response = api.post(RUN_URL, {"dataset_id": bad})
        assert response.status_code == 302
    assert BacktestRun.objects.count() == 0


def test_shared_ownerless_dataset_is_still_usable(api):
    """System-owned (ownerless) datasets remain available to everyone."""
    shared = _dataset(None, name="Shared reference series")

    response = api.post(RUN_URL, {"dataset_id": shared.pk})

    assert response.status_code == 302
    assert BacktestRun.objects.filter(dataset=shared).exists()


# ---------------------------------------------------------------------------
# Step 3: background execution honesty
# ---------------------------------------------------------------------------
def test_undersized_dataset_fails_explicitly_without_metrics(user):
    dataset = _dataset(user, name="Too small")
    _seed_candles(dataset, MIN_HISTORY)  # exactly at the floor -> not enough
    run = BacktestRun.objects.create(owner=user, dataset=dataset, name="short")

    summary = run_backtest_task(run.pk)

    run.refresh_from_db()
    assert summary["status"] == "failed"
    assert run.status == "failed"
    # An explicit reason, never plausible-looking numbers.
    assert run.metrics["error"] == "insufficient_candles"
    assert run.sample_count == 0
    assert run.results == {}


def test_completed_run_reports_no_accuracy_when_outcomes_were_not_settled(user):
    dataset = _dataset(user, name="Enough candles")
    _seed_candles(dataset, MIN_HISTORY + 40)
    run = BacktestRun.objects.create(owner=user, dataset=dataset, name="full")

    summary = run_backtest_task(run.pk)

    run.refresh_from_db()
    assert summary["status"] == "completed"
    assert run.status == "completed"
    assert run.sample_count > 0, "replay produced no evaluation points"
    assert run.end_time is not None

    # The critical honesty rule: decisions were recorded, outcomes were not,
    # so no win rate / accuracy may be presented.
    assert run.metrics["accuracy_status"] == "not_evaluated"
    assert run.metrics["directional_accuracy"] is None
    assert "not settled" in run.metrics["accuracy_note"]


def test_terminal_run_is_not_overwritten_on_redelivery(user):
    """``task_acks_late`` can redeliver; a finished run must stay finished."""
    dataset = _dataset(user, name="Already done")
    _seed_candles(dataset, MIN_HISTORY + 10)
    run = BacktestRun.objects.create(
        owner=user,
        dataset=dataset,
        name="done",
        status="completed",
        sample_count=42,
        metrics={"accuracy_status": "measured", "directional_accuracy": 0.5},
    )

    summary = run_backtest_task(run.pk)

    run.refresh_from_db()
    assert summary["skipped"] is True
    assert run.sample_count == 42, "redelivery overwrote a finished run"
    assert run.metrics["accuracy_status"] == "measured"


def test_missing_run_is_reported_not_raised():
    summary = run_backtest_task(999_999)
    assert summary["status"] == "missing"
