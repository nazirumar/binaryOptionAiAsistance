"""Tests for the market-synchronization Celery task."""

from __future__ import annotations

import pytest

from apps.market_sync.constants import SessionStatus, SyncStatus
from apps.market_sync.models import MarketSyncSession
from apps.market_sync.tasks import run_verification_task
from tests.factories import UserFactory
from tests.sync_fakes import build_aligned_scenario

pytestmark = pytest.mark.django_db


def test_task_runs_persisted_session():
    user = UserFactory(username="sync-task-user")
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)
    session = MarketSyncSession.objects.create(
        owner=user, analysis=analysis, screenshot=analysis.screenshot
    )

    result = run_verification_task(session.pk)

    assert result == session.pk
    session.refresh_from_db()
    assert session.status == SessionStatus.COMPLETED
    assert session.outcome == SyncStatus.VERIFIED_ALIGNMENT


def test_task_is_safe_for_missing_session():
    result = run_verification_task(999999)
    assert result is None
