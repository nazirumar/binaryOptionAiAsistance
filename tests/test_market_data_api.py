"""Market data API authorization, validation and ingest tests."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.market_data.models import (
    MarketSymbol,
    MT5ConnectionProfile,
    WorkerHeartbeat,
)
from apps.market_data.services.candle_service import persist_candles
from apps.market_data.services.tick_service import persist_ticks
from tests.factories import UserFactory
from tests.marketdata_fakes import make_candle, make_symbol, make_tick

pytestmark = pytest.mark.django_db

WORKER_TOKEN = "unit-test-worker-token"


@pytest.fixture
def user():
    return UserFactory(username="analyst")


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


def _seed_candles(symbol, *, complete, incomplete):
    now = timezone.now()
    step = timedelta(minutes=1)
    if complete:
        series = [make_candle(now - timedelta(minutes=5) - i * step) for i in range(complete)]
        persist_candles(symbol, "M1", series, now=now, feed_delay_seconds=0)
    if incomplete:
        forming = [make_candle(now - timedelta(seconds=20))]
        persist_candles(symbol, "M1", forming, now=now, feed_delay_seconds=0)


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "/api/market/health/",
        "/api/market/symbols/",
        "/api/market/candles/?symbol=EURUSD&timeframe=M1",
        "/api/market/tick/?symbol=EURUSD",
        "/api/market/connection/",
    ],
)
def test_endpoints_require_authentication(client, url):
    response = client.get(url)
    assert response.status_code in (401, 403)


def test_health_returns_degraded_without_connection(auth_client):
    response = auth_client.get("/api/market/health/")
    assert response.status_code == 200
    body = response.json()
    assert body["connection_state"] == "unknown"
    assert body["live_verified"] is False


def test_symbol_visibility_scoped_to_user(auth_client, user):
    other = UserFactory(username="other")
    other_profile = MT5ConnectionProfile.objects.create(name="other", owner=other)
    make_symbol(canonical="GBPUSD", broker_symbol="GBPUSDx", profile=other_profile)
    make_symbol(canonical="EURUSD", broker_symbol="EURUSD", profile=None)

    response = auth_client.get("/api/market/symbols/")
    assert response.status_code == 200
    symbols = response.json()["results"]
    canonicals = {s["canonical"] for s in symbols}
    assert "EURUSD" in canonicals
    assert "GBPUSD" not in canonicals


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------
def test_candles_excludes_incomplete_by_default(auth_client):
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    _seed_candles(symbol, complete=3, incomplete=1)

    response = auth_client.get("/api/market/candles/?symbol=EURUSD&timeframe=M1")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert all(c["is_complete"] for c in body["results"])

    response_all = auth_client.get(
        "/api/market/candles/?symbol=EURUSD&timeframe=M1&include_incomplete=true"
    )
    assert response_all.json()["count"] == 4


def test_candles_rejects_unsupported_timeframe(auth_client):
    make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    response = auth_client.get("/api/market/candles/?symbol=EURUSD&timeframe=M7")
    assert response.status_code == 400


def test_candles_unknown_symbol_returns_404(auth_client):
    response = auth_client.get("/api/market/candles/?symbol=NOPE&timeframe=M1")
    assert response.status_code == 404


def test_tick_endpoint_returns_latest(auth_client):
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    persist_ticks(symbol, [make_tick(timezone.now() - timedelta(seconds=5))])
    response = auth_client.get("/api/market/tick/?symbol=EURUSD")
    assert response.status_code == 200
    body = response.json()
    assert body["tick"] is not None
    assert body["stale"] is False


def test_connection_endpoint_masks_login_and_hides_secrets(auth_client, user):
    MT5ConnectionProfile.objects.create(
        name="acme",
        owner=user,
        login=987654321,
        server="Acme-Demo",
        credential_ref="MT5_PASSWORD",
    )
    response = auth_client.get("/api/market/connection/")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    payload = body["results"][0]
    assert payload["masked_login"] == "*******21"
    text = json.dumps(body)
    assert "987654321" not in text
    assert "credential_ref" not in text


def test_sync_trigger_enqueues_task(auth_client, monkeypatch):
    make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    calls = {}
    from apps.market_data import tasks

    monkeypatch.setattr(
        tasks.sync_candles_task, "delay", lambda *a, **k: calls.setdefault("candles", a)
    )
    monkeypatch.setattr(
        tasks.sync_ticks_task, "delay", lambda *a, **k: calls.setdefault("ticks", a)
    )

    response = auth_client.post(
        "/api/market/sync/",
        data=json.dumps({"symbol": "EURUSD", "kind": "candles", "timeframe": "M5", "count": 10}),
        content_type="application/json",
    )
    assert response.status_code == 202
    assert "candles" in calls


def test_connection_post_enqueues_check(auth_client, monkeypatch):
    from apps.market_data import tasks

    monkeypatch.setattr(tasks.check_connection_task, "delay", lambda *a, **k: None)
    response = auth_client.post("/api/market/connection/")
    assert response.status_code == 202


# ---------------------------------------------------------------------------
# Worker ingest
# ---------------------------------------------------------------------------
def _ingest_candles_payload(open_time: str) -> dict:
    return {
        "canonical": "EURUSD",
        "broker_symbol": "EURUSDm",
        "timeframe": "M1",
        "candles": [
            {
                "open_time": open_time,
                "open": "1.1000",
                "high": "1.1050",
                "low": "1.0950",
                "close": "1.1020",
                "tick_volume": 12,
                "spread": 8,
            }
        ],
    }


@override_settings(MT5_WORKER_TOKEN="")
def test_ingest_disabled_without_worker_token(client):
    response = client.post(
        "/api/market/ingest/candles/",
        data=json.dumps(_ingest_candles_payload("2026-01-05T12:00:00Z")),
        content_type="application/json",
    )
    assert response.status_code == 403


@override_settings(MT5_WORKER_TOKEN=WORKER_TOKEN)
def test_ingest_rejects_missing_token_header(client):
    response = client.post(
        "/api/market/ingest/candles/",
        data=json.dumps(_ingest_candles_payload("2026-01-05T12:00:00Z")),
        content_type="application/json",
    )
    assert response.status_code == 403


@override_settings(MT5_WORKER_TOKEN=WORKER_TOKEN)
def test_ingest_candles_creates_symbol_and_is_idempotent(client):
    payload = _ingest_candles_payload("2026-01-05T12:00:00Z")
    headers = {"X-Worker-Token": WORKER_TOKEN}

    first = client.post(
        "/api/market/ingest/candles/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["inserted"] == 1
    assert MarketSymbol.objects.filter(broker_symbol="EURUSDm").exists()

    second = client.post(
        "/api/market/ingest/candles/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers,
    )
    assert second.json()["inserted"] == 0
    assert second.json()["skipped"] == 1


@override_settings(MT5_WORKER_TOKEN=WORKER_TOKEN)
def test_ingest_rejects_otc_mismatch(client):
    payload = _ingest_candles_payload("2026-01-05T12:00:00Z")
    payload["canonical"] = "EURUSD_OTC"
    payload["is_otc"] = False
    response = client.post(
        "/api/market/ingest/candles/",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"X-Worker-Token": WORKER_TOKEN},
    )
    assert response.status_code == 400


@override_settings(MT5_WORKER_TOKEN=WORKER_TOKEN)
def test_ingest_ticks(client):
    payload = {
        "canonical": "EURUSD",
        "broker_symbol": "EURUSD",
        "ticks": [
            {"time": "2026-01-05T12:00:00Z", "bid": "1.1", "ask": "1.1002", "last": "1.1001"}
        ],
    }
    response = client.post(
        "/api/market/ingest/ticks/",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"X-Worker-Token": WORKER_TOKEN},
    )
    assert response.status_code == 200
    assert response.json()["inserted"] == 1


@override_settings(MT5_WORKER_TOKEN=WORKER_TOKEN)
def test_worker_heartbeat(client):
    response = client.post(
        "/api/market/worker/heartbeat/",
        data=json.dumps({"worker_id": "w-1", "status": "online", "detail": {"x": 1}}),
        content_type="application/json",
        headers={"X-Worker-Token": WORKER_TOKEN},
    )
    assert response.status_code == 200
    assert WorkerHeartbeat.objects.filter(worker_id="w-1").exists()


def test_url_names_reverse():
    assert reverse("market_data:health") == "/api/market/health/"
    assert reverse("market_data:candles") == "/api/market/candles/"
