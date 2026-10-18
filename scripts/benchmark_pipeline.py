"""Phase 10, Step 11 - real latency benchmark for the analysis pipeline.

Runs against the hermetic test settings (in-memory SQLite, eager Celery, mock
vision/reasoning providers). Every reported number comes from this script's own
run: ``time.perf_counter()`` samples with warm-up, reported as min / median /
p95 / mean over N repetitions per stage.

IMPORTANT: vision-task and reasoning numbers are MOCK-provider figures. A live
LLM round trip cannot be measured here and is listed in the doc's
"Not measured" section. Celery runs eagerly (``apply()``), so task numbers are
raw task execution time, NOT real broker/queue latency.

Usage (from the project root, Windows):
    .\\.venv\\Scripts\\python.exe scripts\\benchmark_pipeline.py
"""

from __future__ import annotations

import json
import math
import os
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

import django  # noqa: E402
from django.core.management import call_command  # noqa: E402

django.setup()

from datetime import timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402
from unittest import mock  # noqa: E402

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.core.files.base import ContentFile  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.models import Max  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.ai_assistant.services.assistant_service import AssistantService  # noqa: E402
from apps.ai_assistant.services.reasoning_provider import (  # noqa: E402
    ReasoningProvider,
    ReasoningRequest,
)
from apps.chart_vision.models import ChartScreenshot, ScreenshotAnalysis  # noqa: E402
from apps.chart_vision.services.screenshot_analyzer import get_or_create_analysis  # noqa: E402
from apps.chart_vision.tasks import analyze_screenshot_task  # noqa: E402
from apps.dashboard.services.overview_service import OverviewService  # noqa: E402
from apps.market_data.models import MarketCandle  # noqa: E402
from apps.strategy_engine.models import StrategyEvaluation  # noqa: E402
from apps.strategy_engine.services.evaluation_service import EvaluationService  # noqa: E402
from apps.trading_journal.models import JournalTrade  # noqa: E402
from tests.sync_fakes import (  # noqa: E402
    Price,
    build_aligned_scenario,
    make_analysis,
    make_candle,
    now_floor,
    screenshot_candles,
    uptrend_prices,
)
from tests.vision_fakes import StaticVisionProvider, full_payload, png_bytes, uploaded_file  # noqa: E402

# ---------------------------------------------------------------------------
# Benchmark configuration
# ---------------------------------------------------------------------------
REPS = 25  # repetitions per stage
WARMUP = 3  # warm-up iterations discarded per stage
CANDLE_REPS = 50  # cheaper DB reads get more samples
REASONING_REPS = 50

EXTRA_CANDLES = 200  # older candles seeded for realistic retrieval volume
SEED_ROUND_1 = 15  # rows before the first query-count pass
SEED_ROUND_2 = 15  # additional rows before the second query-count pass

RESULTS: list[dict] = []
QUERY_ROWS: list[dict] = []


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------
def _pct(sorted_samples: list[float], pct: float) -> float:
    if not sorted_samples:
        return 0.0
    index = math.ceil(pct / 100.0 * len(sorted_samples)) - 1
    return sorted_samples[max(0, min(index, len(sorted_samples) - 1))]


def summarize(samples_ms: list[float]) -> dict:
    ordered = sorted(samples_ms)
    return {
        "n": len(ordered),
        "min_ms": round(ordered[0], 3),
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(_pct(ordered, 95), 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
    }


def bench(label: str, fn, *, reps: int = REPS, warmup: int = WARMUP, pre=None, note: str = ""):
    """Warm up, then time ``fn`` ``reps`` times; store min/median/p95/mean."""
    for _ in range(warmup):
        if pre is not None:
            pre()
        fn()
    samples: list[float] = []
    for _ in range(reps):
        if pre is not None:
            pre()
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    stats = summarize(samples)
    stats.update({"stage": label, "note": note})
    RESULTS.append(stats)
    print(
        f"  {label:<44} n={stats['n']:>3}  min={stats['min_ms']:>9.3f}ms"
        f"  median={stats['median_ms']:>9.3f}ms  p95={stats['p95_ms']:>9.3f}ms"
        f"  mean={stats['mean_ms']:>9.3f}ms"
    )
    return stats


def count_queries(fn) -> int:
    with CaptureQueriesContext(connection) as ctx:
        fn()
    return len(ctx)


def endpoint_queries(client: APIClient, path: str) -> int:
    def call():
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)

    return count_queries(call)


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------
def seed_analyses(owner, count: int) -> None:
    candles = screenshot_candles(uptrend_prices())
    for _ in range(count):
        make_analysis(owner, candles=candles)


def seed_trades(owner, count: int) -> None:
    base = now_floor()
    for index in range(count):
        JournalTrade.objects.create(
            owner=owner,
            trade_type="demo" if index % 2 == 0 else "real",
            instrument="EURUSD",
            market_type="regular",
            direction="call" if index % 3 else "put",
            entry_timestamp=base,
            entry_quote=Decimal("1.1000"),
            settlement_quote=Decimal("1.1005") if index % 3 else Decimal("1.0995"),
            stake=Decimal("10.00"),
            payout_percent=Decimal("80.00"),
            result="win" if index % 3 else "loss",
        )


def candle_dicts(prices: list[Price]) -> list[dict]:
    return [
        {"open": p.open, "high": p.high, "low": p.low, "close": p.close, "complete": True}
        for p in prices
    ]


def evaluation_input(prices: list[Price]) -> dict:
    return {
        "instrument": "EURUSD",
        "timeframe": "M1",
        "market_type": "regular",
        "sync_status": "VERIFIED_ALIGNMENT",
        "timing_validity": "valid",
        "candles": candle_dicts(prices),
    }


def make_task_screenshot(owner, png: bytes) -> ChartScreenshot:
    screenshot = ChartScreenshot.objects.create(
        owner=owner,
        original_filename="chart.png",
        content_type="image/png",
        image_format="png",
        size_bytes=len(png),
        width=800,
        height=400,
        status="accepted",
    )
    screenshot.image.save("chart.png", ContentFile(png), save=True)
    return screenshot


def max_screenshot_id() -> int:
    return ChartScreenshot.objects.aggregate(value=Max("id"))["value"] or 0


def delete_screenshots(screenshots) -> None:
    for screenshot in screenshots:
        screenshot.refresh_from_db()
        if screenshot.image:
            screenshot.image.delete(save=False)
        screenshot.delete()


def delete_screenshots_after(owner, pk_floor: int) -> None:
    """Remove screenshots created after ``pk_floor`` (never touching seeded rows)."""
    delete_screenshots(ChartScreenshot.objects.filter(owner=owner, id__gt=pk_floor))


# ---------------------------------------------------------------------------
# Environment report
# ---------------------------------------------------------------------------
def print_environment() -> None:
    import sqlite3

    from django.utils import timezone

    info = {
        "timestamp_utc": timezone.now().isoformat(),
        "python": platform.python_version(),
        "django": django.get_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "db_vendor": connection.vendor,
        "db_name": str(connection.settings_dict.get("NAME")),
        "sqlite": sqlite3.sqlite_version,
        "debug": settings.DEBUG,
        "celery_always_eager": getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False),
        "vision_llm_provider": getattr(settings, "VISION_LLM_PROVIDER", "?"),
        "reasoning_llm_provider": getattr(settings, "REASONING_LLM_PROVIDER", "?"),
    }
    print("=== Runtime context ===")
    for key, value in info.items():
        print(f"  {key}: {value}")
    print("  note: INFO-level request/task logs suppressed during measurement")
    print()


# ---------------------------------------------------------------------------
# Main benchmark run
# ---------------------------------------------------------------------------
def main() -> int:
    import logging

    # Keep console output readable: per-request INFO logs and eager-Celery task
    # INFO traces are suppressed (warnings and errors still log).
    logging.disable(logging.INFO)

    print("Running migrations on the in-memory test database...")
    call_command("migrate", verbosity=0)
    connection.ensure_connection()

    print_environment()

    User = get_user_model()
    user = User.objects.create_user(username="bench-operator", password="x")

    client = APIClient()
    client.force_login(user)
    client.credentials(HTTP_ACCEPT="application/json")

    prices = uptrend_prices()
    eval_input = evaluation_input(prices)
    png = png_bytes()
    payload = full_payload()

    # -- Seed one aligned MT5 scenario + extra historical candles -----------
    symbol, _prices, aligned_analysis, anchor = build_aligned_scenario(user)
    extra_base = anchor - timedelta(minutes=13 + EXTRA_CANDLES)
    for index in range(EXTRA_CANDLES):
        make_candle(
            symbol, "M1", extra_base + timedelta(minutes=index), prices[index % len(prices)]
        )
    total_candles = MarketCandle.objects.filter(symbol=symbol, timeframe="M1").count()
    print(f"Seeded: 1 aligned analysis, {total_candles} M1 candles for {symbol.canonical}\n")

    # =======================================================================
    # Stage 1 - screenshot upload + image validation (POST /api/vision/...)
    # =======================================================================
    print("=== Stage 1: screenshot upload + image validation (API) ===")
    upload_floor = max_screenshot_id()

    def upload_once():
        response = client.post(
            "/api/vision/screenshots/", {"image": uploaded_file(png)}, format="multipart"
        )
        assert response.status_code == 201, response.content

    bench(
        "upload+validate POST /api/vision/screenshots/",
        upload_once,
        pre=cache.clear,  # reset throttle counters outside the timed region
        note="Pillow 800x400 PNG; validation + private storage write",
    )
    delete_screenshots_after(user, upload_floor)
    print()

    # =======================================================================
    # Stage 2 - vision analysis task (MOCK provider)
    # =======================================================================
    print("=== Stage 2: vision analysis task (MOCK provider, eager Celery) ===")
    task_screenshots: list[ChartScreenshot] = []

    def run_vision_task():
        screenshot = make_task_screenshot(user, png)
        task_screenshots.append(screenshot)
        analysis, _created = get_or_create_analysis(screenshot)
        result = analyze_screenshot_task.apply(args=[analysis.pk])
        assert result.successful(), result.result
        assert result.result["status"] == "completed", result.result

    with mock.patch(
        "apps.chart_vision.services.screenshot_analyzer.get_vision_provider",
        return_value=StaticVisionProvider(payload=payload),
    ):
        bench(
            "analyze_screenshot_task (mock LLM)",
            run_vision_task,
            note="MOCK provider: real image IO + Pillow + validation + DB, no live LLM",
        )
    delete_screenshots(task_screenshots)
    print()

    # =======================================================================
    # Stage 3 - market-data retrieval (stored candles; no live MT5)
    # =======================================================================
    print("=== Stage 3: market-data retrieval (stored candles) ===")
    window_qs = MarketCandle.objects.filter(
        symbol=symbol, timeframe="M1", is_complete=True
    ).order_by("-open_time")[:60]

    def candles_orm():
        rows = list(window_qs)
        assert rows, "no candles returned"

    bench("ORM last-60 completed candles", candles_orm, reps=CANDLE_REPS)

    def candles_api():
        response = client.get("/api/market/candles/?symbol=EURUSD&timeframe=M1&limit=60")
        assert response.status_code == 200, response.content
        assert response.json()["count"] > 0

    candles_api_queries = count_queries(candles_api)
    bench(
        "GET /api/market/candles/?limit=60",
        candles_api,
        reps=REPS,
        pre=cache.clear,
        note="stored candles only; live MT5 retrieval not measurable here",
    )
    print(f"  /api/market/candles/ query count: {candles_api_queries} per request")
    print()

    # =======================================================================
    # Stage 4 - synchronization verification
    # =======================================================================
    print("=== Stage 4: synchronization (POST /api/sync/verify/) ===")

    def sync_verify_once():
        response = client.post("/api/sync/verify/", {"analysis_id": aligned_analysis.pk})
        assert response.status_code == 201, response.content
        assert response.json()["outcome"] == "verified_alignment", response.content

    bench(
        "POST /api/sync/verify/",
        sync_verify_once,
        pre=cache.clear,
        note="screenshot candles vs stored MT5 candles; DB-only comparison",
    )
    print()

    # =======================================================================
    # Stage 5 - strategy evaluation (pure compute)
    # =======================================================================
    print("=== Stage 5: strategy evaluation (EvaluationService) ===")
    evaluator = EvaluationService()

    def evaluate_once():
        outcome = evaluator.evaluate(eval_input)
        # Raw decisions use lowercase enum values: up / down / no_trade.
        assert outcome["direction"] in ("up", "down", "no_trade"), outcome["direction"]

    bench(
        "EvaluationService().evaluate()",
        evaluate_once,
        reps=REPS + 5,
        note="price-action engine + strategy decision; no DB writes",
    )
    print()

    # =======================================================================
    # Stage 6 - assistant explanation (MOCK reasoning provider)
    # =======================================================================
    print("=== Stage 6: assistant explanation (MOCK reasoning provider) ===")
    # NOTE: .env configures REASONING_LLM_PROVIDER=google; the benchmark
    # explicitly forces the mock provider so no external configuration leaks in.
    reasoning = ReasoningProvider(provider="mock", model="bench-mock")
    assert reasoning.provider == "mock"
    request = ReasoningRequest(
        messages=({"role": "user", "content": "Why did you return that decision?"},),
        context={"direction": "UP", "explanation": "Deterministic engines reported UP."},
    )

    def reasoning_once():
        reply = reasoning.complete(request)
        assert reply.success

    bench(
        "ReasoningProvider().complete() (mock)",
        reasoning_once,
        reps=REASONING_REPS,
        note="MOCK provider: string formatting only, no live LLM round trip",
    )

    def assistant_pipeline_once():
        result = AssistantService().analyze_screenshot(user, evaluation_input=eval_input)
        assert "response" in result

    bench(
        "AssistantService().analyze_screenshot() (full)",
        assistant_pipeline_once,
        reps=10,
        note="evaluation + explanation + conversation/session persistence (mock LLM)",
    )
    print()

    # =======================================================================
    # Stage 7 - dashboard overview service
    # =======================================================================
    print("=== Stage 7: dashboard overview service ===")

    def overview_once():
        overview = OverviewService(user).build()
        assert "counts" in overview

    overview_queries = count_queries(overview_once)
    bench("OverviewService().build()", overview_once, reps=REPS)
    print(f"  OverviewService query count: {overview_queries} per build")
    print()

    # =======================================================================
    # Stage 8 - query-count analysis across seeded rows (N+1 detection)
    # =======================================================================
    print("=== Stage 8: endpoint query counts at two data volumes ===")
    seed_analyses(user, SEED_ROUND_1)
    seed_trades(user, SEED_ROUND_1)
    for _ in range(5):
        evaluator.evaluate_and_persist(eval_input, owner=user)

    endpoints = [
        ("GET /dashboard/", "/dashboard/"),
        ("GET /dashboard/analyses/", "/dashboard/analyses/"),
        ("GET /api/vision/history/", "/api/vision/history/"),
        ("GET /api/journal/trades/", "/api/journal/trades/"),
        ("GET /api/journal/performance/", "/api/journal/performance/"),
    ]

    def pass_queries(round_label: str) -> dict[str, int]:
        counts = {}
        for name, path in endpoints:
            counts[name] = endpoint_queries(client, path)
        analyses = ScreenshotAnalysis.objects.filter(owner=user).count()
        trades = JournalTrade.objects.filter(owner=user).count()
        evaluations = StrategyEvaluation.objects.filter(owner=user).count()
        QUERY_ROWS.append(
            {
                "pass": round_label,
                "analyses": analyses,
                "trades": trades,
                "evaluations": evaluations,
                "queries": dict(counts),
            }
        )
        print(
            f"  [{round_label}] analyses={analyses} trades={trades}"
            f" evaluations={evaluations} -> queries={counts}"
        )
        return counts

    counts_round_1 = pass_queries(f"seed {SEED_ROUND_1}")

    seed_analyses(user, SEED_ROUND_2)
    seed_trades(user, SEED_ROUND_2)
    for _ in range(5):
        evaluator.evaluate_and_persist(eval_input, owner=user)

    counts_round_2 = pass_queries(f"seed {SEED_ROUND_1 + SEED_ROUND_2}")

    # Latency of the same endpoints at the larger data volume.
    print()
    print(f"=== Stage 9: endpoint latency at {SEED_ROUND_1 + SEED_ROUND_2} seeded rows ===")
    for name, path in endpoints:

        def call(path=path):
            response = client.get(path)
            assert response.status_code == 200, (path, response.status_code)

        bench(name, call, reps=REPS, pre=cache.clear)
    print()

    # =======================================================================
    # Stage 10 - raw task throughput (eager; NOT queue latency)
    # =======================================================================
    print("=== Stage 10: background task raw execution throughput (eager Celery) ===")
    task_ids: list[int] = []
    throughput_screenshots: list[ChartScreenshot] = []
    for _ in range(20):
        screenshot = make_task_screenshot(user, png)
        throughput_screenshots.append(screenshot)
        analysis, _created = get_or_create_analysis(screenshot)
        task_ids.append(analysis.pk)

    with mock.patch(
        "apps.chart_vision.services.screenshot_analyzer.get_vision_provider",
        return_value=StaticVisionProvider(payload=payload),
    ):
        start = time.perf_counter()
        for pk in task_ids:
            result = analyze_screenshot_task.apply(args=[pk])
            assert result.successful(), result.result
        total_ms = (time.perf_counter() - start) * 1000.0
    throughput = {
        "stage": "task throughput (20 sequential analyses)",
        "total_ms": round(total_ms, 1),
        "mean_per_task_ms": round(total_ms / len(task_ids), 3),
        "tasks_per_second": round(len(task_ids) / (total_ms / 1000.0), 1),
        "note": "eager Celery: raw task execution only, no broker/queue latency",
    }
    print(
        f"  20 tasks in {throughput['total_ms']}ms"
        f" (mean {throughput['mean_per_task_ms']}ms/task, {throughput['tasks_per_second']}/s)"
    )
    delete_screenshots(throughput_screenshots)
    print()

    # =======================================================================
    # N+1 assessment + summary
    # =======================================================================
    n1_assessment = []
    for name, _path in endpoints:
        q1 = counts_round_1[name]
        q2 = counts_round_2[name]
        delta = q2 - q1
        if delta == 0:
            verdict = "constant"
        elif delta <= 2:
            verdict = "near-constant"
        else:
            verdict = f"grows by {delta} queries for +{SEED_ROUND_2} rows (possible N+1)"
        n1_assessment.append(
            {"endpoint": name, "queries_small": q1, "queries_large": q2, "verdict": verdict}
        )

    summary = {
        "environment": {
            "python": platform.python_version(),
            "django": django.get_version(),
            "db": f"{connection.vendor} ({connection.settings_dict.get('NAME')})",
        },
        "stages": RESULTS,
        "overview_queries": overview_queries,
        "candles_api_queries": candles_api_queries,
        "query_passes": QUERY_ROWS,
        "n1_assessment": n1_assessment,
        "task_throughput": throughput,
    }
    print("=== JSON SUMMARY ===")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
