"""Core views: landing page and health probe."""

from __future__ import annotations

import logging
from datetime import UTC
from typing import Any

from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from apps.core import __version__

logger = logging.getLogger(__name__)


def home(request: HttpRequest):
    """Landing page; authenticated users are sent to the dashboard."""
    if request.user.is_authenticated:
        return redirect("dashboard:index")
    return render(request, "core/home.html")


class HealthCheckView(View):
    """Liveness/readiness probe.

    Returns HTTP 200 with ``status="ok"`` when the database responds, and
    HTTP 503 with ``status="degraded"`` otherwise. Intentionally exempt from
    authentication and never exposes sensitive configuration.

    Kept deliberately cheap (database only) because container orchestrators
    call it every few seconds. Full diagnostics live in
    :class:`HealthDetailView` behind ``/healthz/detail/``.
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        payload = _probe_database()
        healthy = payload["status"] == "ok"
        return JsonResponse(
            {
                "status": "ok" if healthy else "degraded",
                "application": "nazbeen-academy-binary-ai",
                "version": __version__,
                "timestamp": timezone.now().isoformat(),
                "checks": {"database": payload},
            },
            status=200 if healthy else 503,
        )


class HealthDetailView(View):
    """Full operational diagnostics: database, cache, Celery, MT5, freshness.

    Restricted to staff because it reveals internal topology (worker counts,
    queue names, heartbeat ages). Nothing secret is returned: no credentials,
    no hostnames from connection strings, no user data.

    Every check is bounded so a hung dependency cannot hang the endpoint. A
    failing *non-critical* dependency (cache/Celery) reports ``degraded`` but
    still returns 200, so a transient broker blip does not trigger a restart
    storm. Only a database failure returns 503.
    """

    #: Seconds tolerated before a worker heartbeat counts as missing.
    WORKER_HEARTBEAT_STALE_SECONDS = 180
    #: Seconds tolerated before market data counts as stale.
    DATA_FRESHNESS_STALE_SECONDS = 900

    def get(self, request: HttpRequest) -> JsonResponse:
        if not (request.user.is_authenticated and request.user.is_staff):
            return JsonResponse({"detail": "Staff access required."}, status=403)

        checks: dict[str, Any] = {}
        critical_ok = True

        # --- Database (critical) ------------------------------------------
        db = _probe_database()
        checks["database"] = db
        if db["status"] != "ok":
            critical_ok = False

        # --- Cache / Redis --------------------------------------------------
        checks["cache"] = _probe_cache()

        # --- Celery workers -------------------------------------------------
        checks["celery"] = _probe_celery()

        # --- MT5 worker heartbeat -------------------------------------------
        checks["mt5_worker"] = _probe_mt5_worker()

        # --- Market data freshness ------------------------------------------
        checks["data_freshness"] = _probe_data_freshness()

        non_critical_degraded = any(
            item["status"] not in ("ok", "skipped")
            for key, item in checks.items()
            if key != "database"
        )
        if not critical_ok:
            status = "down"
        elif non_critical_degraded:
            status = "degraded"
        else:
            status = "ok"

        return JsonResponse(
            {
                "status": status,
                "application": "nazbeen-academy-binary-ai",
                "version": __version__,
                "timestamp": timezone.now().isoformat(),
                "checks": checks,
            },
            status=200 if critical_ok else 503,
        )


def _probe_database() -> dict[str, Any]:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return {"status": "ok", "vendor": connection.vendor}
    except Exception as exc:  # pragma: no cover - failure path
        logger.warning("health_check.database_failed", extra={"error": type(exc).__name__})
        return {"status": "error", "error": type(exc).__name__}


def _probe_cache() -> dict[str, Any]:
    """Ping the cache with a hard socket deadline.

    A dead broker must not hang the probe, so the call runs in a worker thread
    with a bounded wait.
    """
    from django.core.cache import cache

    def _ping() -> str:
        try:
            cache.set("healthz:probe", "1", timeout=5)
            return "ok" if cache.get("healthz:probe") == "1" else "error"
        except Exception:
            return "error"

    result = _call_with_timeout(_ping, timeout=2.0)
    if result is None:
        return {"status": "error", "error": "Timeout"}
    if result == "error":
        logger.warning("health_check.cache_failed")
    return {"status": result}


def _probe_celery(timeout: float = 1.5) -> dict[str, Any]:
    """Report the number of reachable Celery workers.

    Uses a bounded inspect ping. With no broker configured (local dev without
    Redis) this reports ``skipped`` rather than a false failure.
    """
    from django.conf import settings as django_settings

    if django_settings.CELERY_TASK_ALWAYS_EAGER or not getattr(django_settings, "REDIS_URL", ""):
        return {"status": "skipped", "reason": "no broker configured"}

    def _ping():
        from celery import current_app

        return current_app.control.ping(timeout=timeout)

    result = _call_with_timeout(_ping, timeout=timeout + 0.5)
    if result is None:
        logger.warning("health_check.celery_timeout")
        return {"status": "error", "error": "Timeout", "workers": 0}
    workers = len(result) if isinstance(result, list) else 0
    return {"status": "ok" if workers else "error", "workers": workers}


def _heartbeat_stale_threshold() -> int:
    """Seconds after which an MT5 worker heartbeat counts as missing.

    Defaults to twice the configured heartbeat TTL, so a single missed beat
    does not page anyone.
    """
    from django.conf import settings as django_settings

    ttl = int(getattr(django_settings, "MT5_WORKER_HEARTBEAT_TTL_SECONDS", 90))
    return max(HealthDetailView.WORKER_HEARTBEAT_STALE_SECONDS, ttl * 2)


def _probe_mt5_worker() -> dict[str, Any]:
    """Age of the most recent MT5 worker heartbeat."""
    try:
        from apps.market_data.models import WorkerHeartbeat

        heartbeat = WorkerHeartbeat.objects.order_by("-last_seen").first()
    except Exception as exc:  # pragma: no cover - defensive
        return {"status": "skipped", "reason": type(exc).__name__}
    if heartbeat is None:
        return {"status": "skipped", "reason": "no worker has ever reported"}

    age = (timezone.now() - heartbeat.last_seen).total_seconds()
    threshold = _heartbeat_stale_threshold()
    if age > threshold:
        logger.warning("health_check.mt5_worker_stale", extra={"age_seconds": int(age)})
        return {
            "status": "error",
            "worker_id": heartbeat.worker_id,
            "heartbeat_age_seconds": int(age),
            "stale_threshold_seconds": threshold,
        }
    return {
        "status": "ok",
        "worker_id": heartbeat.worker_id,
        "heartbeat_age_seconds": int(age),
        "stale_threshold_seconds": threshold,
    }


def _probe_data_freshness() -> dict[str, Any]:
    """How old the newest stored market data is (informational metric)."""
    try:
        from apps.market_data.models import Candle

        newest = Candle.objects.order_by("-time").values_list("time", flat=True).first()
    except Exception as exc:  # pragma: no cover - defensive
        return {"status": "skipped", "reason": type(exc).__name__}
    if newest is None:
        return {"status": "skipped", "reason": "no candles stored"}

    if timezone.is_naive(newest):
        newest = timezone.make_aware(newest, UTC)
    age = (timezone.now() - newest).total_seconds()
    stale = age > HealthDetailView.DATA_FRESHNESS_STALE_SECONDS
    return {
        "status": "error" if stale else "ok",
        "newest_candle_age_seconds": int(age),
        "stale_threshold_seconds": HealthDetailView.DATA_FRESHNESS_STALE_SECONDS,
    }


def _call_with_timeout(func, *, timeout: float):  # type: ignore[no-untyped-def]
    """Run ``func`` in a thread and give up after ``timeout`` seconds.

    Returns the function's result, or ``None`` on timeout. Thread creation is
    cheap relative to the network call being guarded.
    """
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeoutError

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            future.cancel()
            return None
        except Exception:
            return "error"
