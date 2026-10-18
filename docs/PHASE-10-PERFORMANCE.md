# PHASE 10 — PIPELINE PERFORMANCE MEASUREMENT
**Project:** Nazbeen Academy Binary Ai Asisstance
**Date:** October 18, 2026
**Method:** executed benchmark, two full runs — `.\.venv\Scripts\python.exe scripts\benchmark_pipeline.py`
**Script:** `scripts/benchmark_pipeline.py` (passes `ruff check`; rerunnable by anyone with the venv)

**Scope / honesty notes**
- Every number below comes from an actual run performed on **2026-10-17 23:25 UTC (run 1)** and **2026-10-17 23:27 UTC (run 2)** on this machine. Nothing is estimated or copied from documentation.
- Vision-task and assistant-explanation figures are **MOCK-provider figures** (in-process fakes). **No live LLM was called.** Live-LLM latency is listed under "Not measured here".
- Celery runs **eager** (`CELERY_TASK_ALWAYS_EAGER=True`); task figures are raw task execution time, **not** broker/queue latency.
- The database is **in-memory SQLite** — no network hop, no disk I/O for DB pages, no lock contention. Numbers for PostgreSQL in production will be higher; treat these as a **floor**.
- The machine is a shared 4-logical-CPU Windows 11 workstation. Run-to-run medians varied by up to ~2× on some stages (see the variance column). Query counts, by contrast, were **bit-for-bit identical across both runs and both seed volumes**.

---

## 1. Methodology

| Aspect | Detail |
|---|---|
| Timing | `time.perf_counter()`, per stage: 3 discarded warm-up iterations, then N timed repetitions (25–50 per stage) |
| Statistics | min / median / p95 (nearest-rank) / mean over all repetitions |
| Settings | `config.settings.test` — DEBUG=False, in-memory SQLite (migrations applied at startup), eager Celery, locmem cache, cheap MD5 password hasher |
| Isolation | DRF throttle counters (`ScopedRateThrottle` on the locmem cache) reset via `cache.clear()` **outside** the timed region before every throttled request, so no 429s are measured |
| Logging | INFO-level request/task logs suppressed during measurement (warnings/errors still log); this removes per-request structlog formatting from the timings |
| Data seeded | 212 M1 candles (12-candle aligned scenario + 200 older candles, `tests/sync_fakes.py` helpers); 31 screenshot analyses (13-candle payloads); 30 journal trades (demo+real mix, wins and losses); 23 strategy evaluations |
| Query counts | `django.test.utils.CaptureQueriesContext`, one measured request per endpoint, at **two data volumes** (16→31 analyses, 15→30 trades) to distinguish constant-cost endpoints from N+1 patterns |
| N+1 method | If query count grows when row count grows → per-row queries. Page size is 25, so the second pass renders 25 rows vs 16 in the first — an N+1 in serialization would have shown as growth. None was observed in the five audited endpoints. |
| Authentication | `force_login` session client (DRF `APIClient`), `Accept: application/json` |

**Runtime context (printed by the script):** Python 3.13.14, Django 5.2.18, SQLite 3.50.4 (`:memory:`), Windows-11 AMD64, 4 CPUs, `VISION_LLM_PROVIDER=mock`, `REASONING_LLM_PROVIDER=google` in `.env` (**the benchmark explicitly forces the mock provider** for the reasoning stage so no external configuration leaks into the measurement).

---

## 2. Stage latency results

Run 2 medians are the primary figures; run 1 medians are shown to make the machine's noise visible. **Use the median, not the p95, for budgeting — but note the p95 column honestly.**

| # | Stage | n | min (ms) | **median (ms)** | p95 (ms) | mean (ms) | run-1 median (ms) | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | Screenshot upload + image validation `POST /api/vision/screenshots/` | 25 | 20.9 | **26.9** | 30.8 | 30.4 | 28.2 | Pillow 800×400 PNG; format sniffing, sha256, private-storage write |
| 2 | Vision analysis task `analyze_screenshot_task` | 25 | 80.3 | **91.3** | 114.1 | 94.0 | 92.4 | **MOCK vision provider**; real image read + Pillow preprocess + schema validation + DB persistence |
| 3a | MT5/market-data read — ORM last-60 completed candles | 50 | 0.003 | **0.004** | 0.005 | 0.004 | 0.005 | Stored candles only; 212 rows in table |
| 3b | MT5/market-data read — `GET /api/market/candles/?limit=60` | 25 | 224.8 | **238.7** | 263.7 | 241.9 | 278.7 | **64 queries/request — N+1 (see §3)** |
| 4 | Synchronization `POST /api/sync/verify/` | 25 | 117.3 | **126.2** | 153.2 | 142.7 | 144.6 | Screenshot candles vs stored MT5 candles; full comparison + session persistence |
| 5 | Strategy evaluation `EvaluationService().evaluate()` | 30 | 5.5 | **7.1** | 9.9 | 7.2 | 14.4 | Price-action engine + decision; pure compute, no DB writes |
| 6a | AI assistant explanation `ReasoningProvider().complete()` | 50 | 0.008 | **0.010** | 0.016 | 0.013 | 0.010 | **MOCK provider** — string formatting only, **no LLM round trip** |
| 6b | Assistant full pipeline `AssistantService().analyze_screenshot()` | 10 | 30.8 | **34.4** | 37.2 | 33.9 | 63.7 | Evaluation + explanation + conversation/session persistence (mock reasoning) |
| 7 | Dashboard overview `OverviewService().build()` | 25 | 37.3 | **47.6** | 53.6 | 47.9 | 112.3 | **14 queries per build** (constant) |

### Endpoint latency (at 30 seeded rows, full request path incl. auth/session/templates)

| Endpoint | n | min (ms) | **median (ms)** | p95 (ms) | run-1 median (ms) |
|---|---|---|---|---|---|
| `GET /dashboard/` | 25 | 74.8 | **87.0** | 99.8 | 76.2 |
| `GET /dashboard/analyses/` | 25 | 65.9 | **77.8** | 113.1 | 60.7 |
| `GET /api/vision/history/` | 25 | 50.6 | **57.8** | 85.2 | 35.3 |
| `GET /api/journal/trades/` | 25 | 54.5 | **67.1** | 85.9 | 38.0 |
| `GET /api/journal/performance/` | 25 | 15.9 | **20.7** | 23.5 | 11.3 |

### Background task throughput (eager Celery — **not** queue latency)

20 sequential vision analyses: run 2 = **1,529.6 ms total → 76.5 ms/task → 13.1 tasks/s**; run 1 = 1,403.4 ms → 70.2 ms/task → 14.3 tasks/s. With a single worker process this is the throughput ceiling for the vision stage; queueing delay on top of it is unmeasured (see §4).

---

## 3. Query-count table and N+1 assessment

Measured at two data volumes. **Identical counts at both volumes ⇒ no N+1.**

| Endpoint | Queries @ 16 analyses / 15 trades | Queries @ 31 analyses / 30 trades | Growth | Assessment |
|---|---|---|---|---|
| `GET /dashboard/` | 19 | 19 | +0 | No N+1. 19 constant queries (6 separate `COUNT`s in `OverviewService._counts`, aggregates, sync-log/health reads, auth/session) — optimizable but not a correctness issue |
| `GET /dashboard/analyses/` | 6 | 6 | +0 | No N+1 (uses `select_related("screenshot")` and paginated evaluations) |
| `GET /api/vision/history/` | 4 | 4 | +0 | Clean |
| `GET /api/journal/trades/` | 4 | 4 | +0 | Clean (count + page + session/user) |
| `GET /api/journal/performance/` | 3 | 3 | +0 | Clean (segmented aggregates) |
| `GET /api/market/candles/?limit=60` (extra) | **64** | **64** | — | **CONFIRMED N+1 — 1 query per candle row** |

### N+1 problem found (not in the 5 audited endpoints)

**`GET /api/market/candles/` issues 64 queries to return 60 candles.** Cause: `MarketCandleListAPIView` (`apps/market_data/views.py`) fetches candles with `list(query.order_by("-open_time")[:limit])` **without** `select_related("symbol")`, while `MarketCandleSerializer` (`apps/market_data/serializers.py`) reads `symbol.canonical` and `symbol.broker_symbol` per row — Django then lazily loads the FK once per candle (60 + 4 baseline = 64).
**Fix:** add `.select_related("symbol")` to the queryset in `MarketCandleListAPIView.get` → drops to ~4 queries. This scales badly today: at the allowed `MT5_MAX_CANDLE_RANGE` (5000) a single request would issue ~5000 queries.

---

## 4. Not measured here (and why)

| Not measured | Reason |
|---|---|
| **Live MT5 retrieval** | No MT5 terminal/worker is available on this host; the `MT5Gateway` is read-only and Windows-terminal-bound. Only **stored-candle** reads were measured (ORM + API). The worker's `copy_rates_from` round trip over the MT5 IPC/broker path is unmeasured. |
| **Live vision LLM** | Test settings force `VISION_LLM_PROVIDER=mock`; the benchmark patches a deterministic in-process provider. A hosted vision model typically adds **seconds** per call — unverified here. |
| **Live reasoning/explanation LLM** | `.env` sets `REASONING_LLM_PROVIDER=google`; the benchmark explicitly forces the **mock** provider. (Note: the current `ReasoningProvider.complete()` implementation performs **no network I/O** in any branch — non-mock providers return a safe fallback — so a live figure requires both real credentials and a real adapter.) |
| **Real Redis broker + Celery workers** | Celery is eager in tests. Queue dispatch, worker wake-up, prefetching, retry backoff (`VISION_LLM_BACKOFF_SECONDS=1.5` × 2^attempt, up to 3 attempts) and result-backend writes are all **excluded** from the task numbers. |
| **Concurrent-user load** | Single sequential client, single process, in-memory SQLite (no lock contention), locmem cache. Multi-user behavior with production Postgres + Redis is untested. |
| **PostgreSQL / disk-backed storage** | All DB numbers are in-memory SQLite. Production adds network round trips, planning, and locking; storage here is local `FileSystemStorage`, not network/object storage. |

---

## 5. Performance budgets for a 1-minute (M1) workflow

**Honest framing:** an M1 binary-option signal is only useful if the *entire* pipeline — screenshot capture through displayed decision — completes **before the target candle opens**. With ~30–45 s of realistic processing time left after a human captures the chart, the budget below assumes the decision must be on screen ≥ 5 s before candle open, i.e. an end-to-end budget of **≤ 5,000 ms** for the machine-side pipeline. Anything that pushes past the candle open is worthless regardless of accuracy.

| Stage | Budget (M1) | Measured median (mock / stored data) | Measured p95 | Verdict |
|---|---|---|---|---|
| Upload + image validation | ≤ 1,000 ms | 26.9 ms | 30.8 ms | ✅ **Fits** |
| Vision analysis (task) | ≤ 2,000 ms | 91.3 ms *(MOCK)* | 114.1 ms | ✅ Fits **under mock only**; live LLM unmeasured |
| Market-data read (stored candles, API) | ≤ 500 ms | 238.7 ms | 263.7 ms (run 1 p95: 792 ms) | ⚠️ **Fits at median; marginal tail; N+1 scales badly** |
| Synchronization verify | ≤ 1,000 ms | 126.2 ms | 153.2 ms (run 1 p95: 504 ms) | ✅ Fits |
| Strategy evaluation | ≤ 500 ms | 7.1 ms | 9.9 ms | ✅ Fits |
| Assistant explanation | ≤ 2,000 ms | 0.01 ms *(MOCK)* | 0.016 ms | ✅ Fits **under mock only**; live LLM unmeasured |
| **Sum of machine-side stages (mock LLMs)** | **≤ 5,000 ms** | **≈ 490 ms** | — | ✅ Fits with mock providers |
| Dashboard / journal pages (not on signal path) | ≤ 1,000 ms | 20.7–87.0 ms | ≤ 113 ms | ✅ Fits |

**Is a one-minute signal timely? — Honest answer: the *measured* pipeline is; the *real* pipeline is not yet proven.**
- With mock LLMs and no queue, capture→decision is **well under 1 second** — comfortably inside the M1 window.
- The two unmeasured stages (live vision LLM, live reasoning LLM) are precisely where a real deployment spends seconds. Two hosted calls at a typical 1–10 s each, plus queueing and up to 3 attempts with exponential backoff, could realistically total **10–40 s**. That still *plausibly* fits a 60-second window if the screenshot is captured near candle open, **but it has not been measured, so it must not be claimed.**
- **Do not represent this as a real-time one-minute signal until an end-to-end run with the live vision provider and live reasoning provider is measured on deployment hardware.**

---

## 6. Conclusions and top optimization opportunities

**Conclusions**
1. All local computation is fast: strategy evaluation (median 7–14 ms), upload/validation (~27 ms), sync verification (~126–145 ms), overview dashboard (~48–112 ms). The deterministic engine core is not a latency risk.
2. The five audited dashboard/journal endpoints show **no N+1 patterns** — query counts are constant (3–19) and identical across data volumes and runs.
3. One real N+1 was found and root-caused: **`GET /api/market/candles/` = 64 queries for 60 candles**.
4. Timeliness of a live M1 signal is **gated entirely by the unmeasured external services** (LLM providers, real queue, live MT5), not by the measured code.

**Top optimization opportunities (specific)**
1. **`apps/market_data/views.py` → `MarketCandleListAPIView.get`:** add `.select_related("symbol")` to the candle queryset (64 queries → ~4). Highest-value fix; also protects the 5000-candle worst case.
2. **`apps/dashboard/services/overview_service.py` → `OverviewService._counts`:** 6 separate `COUNT` queries + 2 more aggregates; a single `aggregate()` with `Count(filter=...)` would cut `/dashboard/` from 19 queries toward ~13. Low urgency (19 constant queries ≈ few ms).
3. **`OverviewService._performance`:** loads all settled real trades into Python (`sum((t.profit_loss or 0) …)`) — replace with a DB `Sum` aggregate to avoid O(rows) memory as the journal grows.
4. **Tail latency:** run-1 p95 for `/api/market/candles/` hit 792 ms and sync verify 504 ms on this noisy workstation. Re-benchmark on deployment hardware before publishing latency SLOs; add an index check (`MarketCandle(symbol, timeframe, open_time)`) if PostgreSQL shows slow window reads there.
5. **Before any "real-time M1" claim:** wire a live-provider benchmark (vision LLM + reasoning LLM + real broker/worker) and measure end-to-end capture→decision on the production stack.

**Failures encountered and fixed during this benchmarking work (documented, not hidden):**
- The first run's stage-2 cleanup deleted the seeded aligned screenshot (FK cascade removed its analysis), causing `/api/sync/verify/` to 404; fixed by deleting only benchmark-created screenshots (ID floor / tracked rows).
- The first two runs aborted in stage 5 because raw `EvaluationService` decisions use lowercase `up`/`down`/`no_trade` (the assistant layer uppercases for display); the assertion was corrected to the real enum values.
- `.env` configures `REASONING_LLM_PROVIDER=google`; the benchmark forces `ReasoningProvider(provider="mock")` so the measured figure is honestly labelled as mock.
