"""Unit tests for the optional remote ingest push client."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.market_data.services.remote_ingest import (
    RemoteIngestClient,
    RemoteIngestError,
    _candle_payload,
    _tick_payload,
)
from tests.marketdata_fakes import BASE_TIME, make_candle, make_tick


def test_requires_worker_token():
    with pytest.raises(RemoteIngestError):
        RemoteIngestClient("https://example.test", "")


def test_candle_payload_serialises_decimal_and_time():
    payload = _candle_payload(make_candle(BASE_TIME))
    assert payload["open_time"] == BASE_TIME.isoformat()
    assert payload["open"] == "1.1000"
    assert payload["tick_volume"] == 100


def test_tick_payload_serialises_decimal_and_time():
    payload = _tick_payload(make_tick(BASE_TIME))
    assert payload["time"] == BASE_TIME.isoformat()
    assert payload["bid"] == "1.1000"


def test_ingest_posts_with_token_header(monkeypatch):
    client = RemoteIngestClient("https://example.test", "secret")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["token"] = request.get_header("X-worker-token")
        captured["body"] = request.data

        class _Response:
            def read(self):
                return b'{"inserted": 1}'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = client.ingest_candles(
        canonical="EURUSD",
        broker_symbol="EURUSD",
        is_otc=False,
        timeframe="M1",
        candles=[make_candle(BASE_TIME)],
    )
    assert result == {"inserted": 1}
    assert captured["url"].endswith("/api/market/ingest/candles/")
    assert captured["token"] == "secret"


def test_heartbeat_posts(monkeypatch):
    client = RemoteIngestClient("https://example.test", "secret")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: type(
            "R",
            (),
            {
                "read": lambda self: b"{}",
                "__enter__": lambda self: self,
                "__exit__": lambda self, *a: False,
            },
        )(),
    )
    assert client.heartbeat(worker_id="w1") == {}


def test_spread_is_decimal():
    assert make_tick(BASE_TIME).ask - make_tick(BASE_TIME).bid == Decimal("0.0002")
