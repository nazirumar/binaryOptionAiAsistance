"""Optional HTTP push client for running the worker on a separate host.

When a worker cannot reach the database directly, it can authenticate to the
Django server with a shared worker token and POST normalised data to the ingest
endpoints. HTTPS is expected in production; the token is sent in
``X-Worker-Token`` and never logged.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any

from apps.market_data.services.dto import Candle, Tick

logger = logging.getLogger(__name__)

_HEADER = "X-Worker-Token"


class RemoteIngestError(Exception):
    """Raised when the remote ingest call fails."""


def _candle_payload(candle: Candle) -> dict[str, Any]:
    return {
        "open_time": candle.open_time.isoformat(),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "tick_volume": candle.tick_volume,
        "real_volume": candle.real_volume,
        "spread": candle.spread,
    }


def _tick_payload(tick: Tick) -> dict[str, Any]:
    payload = asdict(tick)
    payload["time"] = tick.time.isoformat()
    for key in ("bid", "ask", "last"):
        if payload[key] is not None:
            payload[key] = str(payload[key])
    return payload


class RemoteIngestClient:
    """Minimal token-authenticated client for the server ingest API."""

    def __init__(self, base_url: str, token: str, *, timeout: float = 15.0) -> None:
        if not token:
            raise RemoteIngestError("A worker token is required for push mode.")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json", _HEADER: self.token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            raise RemoteIngestError(f"HTTP {exc.code} from {path}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover - network path
            raise RemoteIngestError(f"Transport error for {path}: {exc.reason}") from exc
        return json.loads(body) if body else {}

    def ingest_candles(
        self,
        *,
        canonical: str,
        broker_symbol: str,
        is_otc: bool,
        timeframe: str,
        candles: list[Candle],
        source: str = "mt5",
        collector: str = "",
        profile_id: int | None = None,
    ) -> dict[str, Any]:
        return self._post(
            "/api/market/ingest/candles/",
            {
                "canonical": canonical,
                "broker_symbol": broker_symbol,
                "is_otc": is_otc,
                "timeframe": timeframe,
                "source": source,
                "collector": collector,
                "profile": profile_id,
                "candles": [_candle_payload(c) for c in candles],
            },
        )

    def ingest_ticks(
        self,
        *,
        canonical: str,
        broker_symbol: str,
        is_otc: bool,
        ticks: list[Tick],
        source: str = "mt5",
        collector: str = "",
        profile_id: int | None = None,
    ) -> dict[str, Any]:
        return self._post(
            "/api/market/ingest/ticks/",
            {
                "canonical": canonical,
                "broker_symbol": broker_symbol,
                "is_otc": is_otc,
                "source": source,
                "collector": collector,
                "profile": profile_id,
                "ticks": [_tick_payload(t) for t in ticks],
            },
        )

    def heartbeat(
        self, *, worker_id: str, status: str = "online", detail: dict | None = None
    ) -> dict:
        return self._post(
            "/api/market/worker/heartbeat/",
            {"worker_id": worker_id, "status": status, "detail": detail or {}},
        )


__all__ = ["RemoteIngestClient", "RemoteIngestError"]
