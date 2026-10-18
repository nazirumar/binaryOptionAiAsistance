"""API tests for the market-synchronization endpoints (Step 14).

Covers authentication, ownership scoping, validation, idempotency, pagination
and the health summary. All data is stored locally; no MT5 terminal is needed.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import Client

from apps.market_sync.models import MarketSyncSession
from tests.factories import UserFactory
from tests.sync_fakes import build_aligned_scenario

pytestmark = pytest.mark.django_db

VERIFY_URL = "/api/sync/verify/"


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user():
    return UserFactory(username="sync-api-user")


@pytest.fixture
def other():
    return UserFactory(username="sync-api-other")


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method,url",
    [
        ("post", VERIFY_URL),
        ("get", "/api/sync/results/1/"),
        ("get", "/api/sync/history/"),
        ("get", "/api/sync/health/"),
    ],
)
def test_endpoints_require_authentication(client, method, url):
    response = getattr(client, method)(url, {})
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
def test_verify_creates_verified_session(auth_client, user):
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)
    response = auth_client.post(VERIFY_URL, {"analysis_id": analysis.pk})

    assert response.status_code == 201
    body = response.json()
    assert body["outcome"] == "verified_alignment"
    assert body["is_verified"] is True
    assert "status_message" in body
    assert body["mt5_broker_symbol"] == "EURUSD"
    assert len(body["alignments"]) == 12


def test_verify_by_screenshot_id(auth_client, user):
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)
    response = auth_client.post(VERIFY_URL, {"screenshot_id": analysis.screenshot_id})
    assert response.status_code == 201
    assert response.json()["analysis"] == analysis.pk


def test_verify_unknown_analysis_returns_404(auth_client):
    response = auth_client.post(VERIFY_URL, {"analysis_id": 999999})
    assert response.status_code == 404


def test_verify_requires_an_identifier(auth_client):
    response = auth_client.post(VERIFY_URL, {})
    assert response.status_code == 400


def test_verify_rejects_invalid_timeframe(auth_client, user):
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)
    response = auth_client.post(VERIFY_URL, {"analysis_id": analysis.pk, "timeframe": "M7"})
    assert response.status_code == 400


def test_verify_cannot_reach_another_users_analysis(auth_client, other):
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(other)
    response = auth_client.post(VERIFY_URL, {"analysis_id": analysis.pk})
    assert response.status_code == 404


def test_verify_is_idempotent_per_user(auth_client, user):
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)
    payload = {"analysis_id": analysis.pk, "idempotency_key": "same-request"}

    first = auth_client.post(VERIFY_URL, payload)
    second = auth_client.post(VERIFY_URL, payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert MarketSyncSession.objects.count() == 1


def test_idempotency_keys_are_user_scoped(auth_client, user, other):
    _symbol, _prices, analysis_a, _anchor = build_aligned_scenario(user)
    _symbol2, _prices2, analysis_b, _anchor2 = build_aligned_scenario(other)

    first = auth_client.post(
        VERIFY_URL, {"analysis_id": analysis_a.pk, "idempotency_key": "shared"}
    )
    assert first.status_code == 201

    client_b = Client()
    client_b.force_login(other)
    second = client_b.post(VERIFY_URL, {"analysis_id": analysis_b.pk, "idempotency_key": "shared"})
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]
    assert MarketSyncSession.objects.count() == 2


def test_otc_incompatibility_reported_not_verified(auth_client, user):
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(
        user, instrument="EURUSD-OTC", otc_status="otc"
    )
    response = auth_client.post(VERIFY_URL, {"analysis_id": analysis.pk})
    body = response.json()
    assert response.status_code == 201
    assert body["outcome"] == "incompatible_feed"
    assert body["is_verified"] is False


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
def test_result_returns_detail(auth_client, user):
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(user)
    created = auth_client.post(VERIFY_URL, {"analysis_id": analysis.pk}).json()

    response = auth_client.get(f"/api/sync/results/{created['id']}/")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["feed_assessment"]["compatibility"] == "compatible"
    assert "audit_logs" in body


def test_result_is_owner_scoped(auth_client, other):
    _symbol, _prices, analysis, _anchor = build_aligned_scenario(other)
    session = MarketSyncSession.objects.create(owner=other, analysis=analysis)

    response = auth_client.get(f"/api/sync/results/{session.pk}/")
    assert response.status_code == 404


def test_result_unknown_id_returns_404(auth_client):
    response = auth_client.get("/api/sync/results/999999/")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
def test_history_is_paginated_and_owner_scoped(auth_client, user, other):
    _s, _p, analysis, _a = build_aligned_scenario(user)
    auth_client.post(VERIFY_URL, {"analysis_id": analysis.pk})
    MarketSyncSession.objects.create(owner=other)

    response = auth_client.get("/api/sync/history/")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["is_verified"] is True


def test_history_filters_by_outcome(auth_client, user):
    _s, _p, good, _a = build_aligned_scenario(user)
    auth_client.post(VERIFY_URL, {"analysis_id": good.pk})
    _s2, _p2, otc, _a2 = build_aligned_scenario(
        user,
        instrument="GBPUSD-OTC",
        otc_status="otc",
        broker_symbol="GBPUSD",
        canonical="GBPUSD",
    )
    auth_client.post(VERIFY_URL, {"analysis_id": otc.pk})

    response = auth_client.get("/api/sync/history/?outcome=incompatible_feed")
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["outcome"] == "incompatible_feed"


def test_history_rejects_unknown_outcome(auth_client):
    response = auth_client.get("/api/sync/history/?outcome=not_a_status")
    assert response.status_code == 400


def test_history_rejects_unknown_timeframe(auth_client):
    response = auth_client.get("/api/sync/history/?timeframe=M7")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
def test_health_reports_reference_data(auth_client, user):
    _symbol, _prices, _analysis, _anchor = build_aligned_scenario(user)
    response = auth_client.get("/api/sync/health/")

    assert response.status_code == 200
    body = response.json()
    assert body["config_version"] == "1.0"
    assert body["mt5_reference_available"] is True
    assert body["mt5_candle_count"] == 12
    assert isinstance(body["mt5_reference_series"], list)
    assert body["server_time"]


def test_health_without_reference_data(auth_client):
    response = auth_client.get("/api/sync/health/")
    body = response.json()
    assert body["mt5_reference_available"] is False
    assert body["mt5_candle_count"] == 0
