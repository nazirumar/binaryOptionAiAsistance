"""Tests for the market-synchronization dashboard pages."""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.market_sync.dashboard import DISCLAIMER
from apps.market_sync.models import MarketSyncSession
from apps.market_sync.services.synchronization_service import SynchronizationService
from tests.factories import UserFactory
from tests.sync_fakes import build_aligned_scenario

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return UserFactory(username="sync-dashboard-user")


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


def test_sync_page_requires_login(client):
    response = client.get(reverse("dashboard:sync"))
    assert response.status_code == 302
    assert "login" in response["Location"]


def test_sync_page_renders_with_disclaimer(auth_client):
    response = auth_client.get(reverse("dashboard:sync"))
    assert response.status_code == 200
    content = response.content.decode()
    assert DISCLAIMER in content
    assert "Verify an analysis" in content


def test_sync_page_lists_analyses_and_history(auth_client, user):
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)
    SynchronizationService().verify(analysis=analysis, owner=user)

    response = auth_client.get(reverse("dashboard:sync"))
    content = response.content.decode()
    assert f'value="{analysis.pk}"' in content
    assert reverse("dashboard:sync-detail", args=[1]) in content


def test_sync_verify_creates_session_and_redirects(auth_client, user):
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)
    response = auth_client.post(reverse("dashboard:sync-verify"), {"analysis_id": analysis.pk})

    session = MarketSyncSession.objects.get(owner=user)
    assert response.status_code == 302
    assert response["Location"] == reverse("dashboard:sync-detail", args=[session.pk])


def test_sync_verify_without_selection_shows_error(auth_client, user):
    response = auth_client.post(reverse("dashboard:sync-verify"), {}, follow=True)
    assert response.status_code == 200
    assert "Please choose an analysis" in response.content.decode()


def test_sync_verify_cannot_reach_other_users_analysis(auth_client, user):
    other = UserFactory(username="sync-dashboard-other")
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(other)
    response = auth_client.post(
        reverse("dashboard:sync-verify"), {"analysis_id": analysis.pk}, follow=True
    )
    assert response.status_code == 200
    assert "could not be found" in response.content.decode()
    assert not MarketSyncSession.objects.filter(owner=user).exists()


def test_sync_detail_shows_verified_badge(auth_client, user):
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)
    session = SynchronizationService().verify(analysis=analysis, owner=user)

    response = auth_client.get(reverse("dashboard:sync-detail", args=[session.pk]))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Verified alignment" in content
    assert DISCLAIMER in content


def test_sync_detail_never_marks_unverified_as_success(auth_client, user):
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(
        user, instrument="EURUSD-OTC", otc_status="otc"
    )
    session = SynchronizationService().verify(analysis=analysis, owner=user)

    response = auth_client.get(reverse("dashboard:sync-detail", args=[session.pk]))
    content = response.content.decode()
    assert "Not verified" in content
    assert "Verified alignment — screenshot" not in content


def test_sync_detail_is_owner_scoped(auth_client, user):
    other = UserFactory(username="sync-dashboard-scoped-other")
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(other)
    session = SynchronizationService().verify(analysis=analysis, owner=other)

    response = auth_client.get(reverse("dashboard:sync-detail", args=[session.pk]))
    assert response.status_code == 404


def test_dashboard_index_links_to_sync(auth_client):
    response = auth_client.get(reverse("dashboard:index"))
    assert response.status_code == 200
    assert reverse("dashboard:sync") in response.content.decode()
