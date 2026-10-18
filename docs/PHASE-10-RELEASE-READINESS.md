# PHASE 10 — FINAL RELEASE READINESS REPORT

**Project:** Nazbeen Academy Binary Ai Asisstance
**Date:** October 18, 2026
**Scope:** full-repository audit (Phases 1–9), security hardening, secrets, production
settings, database/queue/worker reliability, integration and failure testing, performance,
observability, deployment configuration, CI, backup, documentation and UAT.

**Basis of assessment:** executed evidence only. Every number below came from a command run
in this repository. Nothing is reported as complete without a test, a script output, or a
code reading supporting it.

---

## 1. Readiness classification

# ➤ READY FOR CONTROLLED PAPER TESTING

**Explicitly NOT:**
- ~~NOT READY~~ — the system is not broken; 664 tests pass and the end-to-end workflow works.
- ~~READY FOR PRODUCTION RESEARCH USE~~ — blocked by the critical unresolved issues in §5.

**Why controlled paper testing is justified now**

| Requirement | Evidence |
|---|---|
| Complete workflow functions end to end | 16-step E2E test passes (`test_phase10_integration_e2e.py`) |
| Failure modes fail closed, not misleadingly | 64 tests across 19 failure classes, all green |
| User data isolation holds across the stack | Cross-user isolation tests (API + pages) pass |
| No automatic trading exists anywhere | Audited: no `order_send` / `ORDER_TYPE_*` / `positions_get` anywhere |
| Critical security issues resolved | IDOR, cross-tenant FK, CSV injection, secrets, isolation (§4) |
| Quality gates green | tests / lint / format / secret scan / migrations / `check --deploy` |

**What blocks the next tier (production research use)** — see §5. In short: two core REST
endpoints are stubs, the reasoning provider has no live implementation, and no live MT5 or
live LLM round trip has been verified. (The PostgreSQL restore drill was executed on
2026-10-18 and passed — §12.)

---

## 2. Completed functionality (verified by phase)

| # | Phase | Status | Verification |
|---|---|---|---|
| 1 | Django foundation | **Complete** | settings (dev/test/prod), `manage.py check` clean, health probes |
| 2 | MT5 market-data integration | **Complete (offline)** | models/services/tasks tested; **no live terminal available** |
| 3 | Screenshot vision | **Complete** | upload validation, schema validation, mock provider; real HTTP path present, not exercised live |
| 4 | Screenshot/MT5 synchronization | **Complete (offline)** | `verified_alignment`, `incompatible_feed`, staleness paths tested |
| 5 | Price-action knowledge engine | **Complete** | 13 detectors verified, incl. rejection/SBR-RBS/sweeps |
| 6 | Strategy decision engine | **Core complete, API incomplete** | `EvaluationService` works and is used internally; **`POST /api/strategies/evaluate/` returns 501** |
| 7 | Backtesting & calibration | **Services complete, API stubbed** | replay/metrics/calibration services tested; **`apps/research/views.py` is entirely stubs** |
| 8 | Conversational AI assistant | **Complete with limitation** | orchestrator, safety/response validators, evidence-grounded follow-ups; **reasoning provider has no live HTTP path** |
| 9 | Dashboard, analytics, journal | **Complete** | 14 templates, CSV/PDF exports, journal provenance segmentation |
| 10 | Security, integration, deployment | **Complete** | this report |

---

## 3. Automated test results

```
689 passed, 2 skipped        (56–110 s, config.settings.test)
```

*Baseline at end of Phase 9: **576 passed, 2 skipped** → Phase 10 (incl. the post-report
`.env`-connectivity follow-up) added **113 tests**.*

| Suite | Tests | Purpose |
|---|---|---|
| `test_phase10_failures.py` | 64 | Critical failure scenarios, 19 classes (Step 10) |
| `test_phase10_uat.py` | 14 | UAT scenarios (Step 18) |
| `test_phase10_backtest_reliability.py` | 8 | Backtest execution, authorization, honesty rules |
| `test_phase10_integration_e2e.py` | 2 | Full 16-step workflow + cross-user isolation |
| `test_phase10_env_wiring.py` | 23 | `.env` connectivity: log redaction, Sentry, reasoning-fallback flag, coverage scanner + guards (findings 10–14) |
| `test_phase10_performance.py` | 3 | N+1 query-regression guards for the candles endpoint |

The 2 skips are PostgreSQL-specific constraint-semantics tests (pre-existing, intentional).

**Quality gates**

| Gate | Result |
|---|---|
| `ruff check .` | ✅ clean |
| `ruff format --check .` | ✅ 348 files formatted |
| `scripts/scan_secrets.py` | ✅ no possible secrets |
| `scripts/check_env_coverage.py` | ✅ all hard sections 0 (missing-required / undocumented / config-undocumented / unquoted-`$`) |
| `manage.py makemigrations --check` | ✅ no changes detected |
| `manage.py check` | ✅ no issues |
| `manage.py check --deploy` (prod) | ✅ **0 `security.*` warnings**; 28 remaining are drf-spectacular W001/W002 doc-naming warnings only |
| Container build | ✅ executed, image smoke-tested — see §11.1 |

---

## 4. Security audit findings

### 4.1 Fixed in Phase 10 (each with a regression test)

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | **IDOR**: `POST /dashboard/backtests/run/` accepted *any* `dataset_id` with no owner check | Critical | Owner-scoped lookup (`apps/dashboard/page_views.py`) |
| 2 | **Shared-dataset bug**: `owner__in=[user, None]` never matches NULL rows (SQL `IN` ignores NULL), so ownerless shared datasets were invisible *and* the IDOR fix would have over-blocked | High | Explicit `Q(owner=user) \| Q(owner__isnull=True)` — fixed in **both** the list view and the run view |
| 3 | **Missing module**: `apps/research/tasks.py` did not exist → every backtest submit raised `ImportError` (HTTP 500) | Critical | Real `run_backtest_task` implemented with idempotency, validation and no fabricated metrics |
| 4 | **Data-loss bug**: backtest `results` contained `datetime` objects → `TypeError: Object of type datetime is not JSON serializable` on save, losing the whole run | High | Recursive `_json_safe()` normalisation |
| 5 | **CSV formula injection**: user text in journal/evaluation exports could execute as a spreadsheet formula | High | `safe_cell()` / `write_row()` in `reporting_service.py` (string cells only, so `-10.00` losses stay numeric) |
| 6 | **Cross-tenant FK**: `JournalTradeSerializer` validated `screenshot` and `strategy_evaluation` but **not** `analysis`, allowing a journal entry linked to another user's analysis | High | `validate_analysis()` added |
| 7 | **Container would not boot**: image `CMD` used `daphne`, which is in no requirements file | Critical | Switched to `uvicorn`, which ships in `requirements/prod.txt` |
| 8 | **Retention never ran**: purge tasks existed but no `CELERY_BEAT_SCHEDULE` was configured | Medium | Beat schedule added (daily tick purge, daily screenshot purge, minutely health probe) |
| 9 | **Secret scanning gap**: no automated secret scanning | Medium | `scripts/scan_secrets.py` wired into CI |
| 10 | **Security control was documentation only**: `DJANGO_LOG_REDACT_HEADERS` had no code behind it | Medium | `RedactHeadersFilter` (`apps/core/logging.py`) wired into the `console` handler — masks `Authorization`/`Cookie`/`X-API-Key` values (incl. `HTTP_AUTHORIZATION`, `Set-Cookie`, `Bearer <jwt>`) in messages and structured extras, both formatters |
| 11 | **Error tracking unwired**: `SENTRY_DSN` documented and `sentry-sdk` shipped, but nothing initialized it | Medium | `init_sentry()` (`apps/core/observability.py`) called only by `prod.py`: empty DSN = off; DSN without SDK = refuse to boot; `send_default_pii=False`, `traces_sample_rate=0.0` |
| 12 | **Setting ignored**: `REASONING_FALLBACK_ON_FAILURE` was read by nothing | Low | `ReasoningProvider._failure()` honours it; default behaviour unchanged (engine explanation + `success=False`) |
| 13 | **Phantom feature**: `VISION_DAILY_REQUEST_BUDGET` advertised a vision cost guard that was never implemented | Low | Key removed from `.env` / `.env.example` instead of pretending it works |
| 14 | **Host/container secret mismatch**: the `DJANGO_SECRET_KEY` value contained an unquoted `$…` — django-environ keeps it literal, but docker compose's dotenv interpolation replaces `$name` with empty, so containers ran with a **silently corrupted** key (plus a warning on every `compose config`) | High | Value single-quoted (both parsers then agree byte-for-byte: host digest `2bcdd3bc6298 len=50` unchanged, compose warnings → 0); permanent `UNQUOTED-DOLLAR` gate added to `scripts/check_env_coverage.py` |
| 15 | **Never-passing healthchecks**: the image-level `HEALTHCHECK` probes `:8000/healthz/`, which only `web` serves — all 4 Celery workers and `beat` reported **permanently unhealthy** in `docker compose ps` while actually running fine | Medium | Both compose files override it: workers/beat use a PID-1 process-liveness check (`grep -q worker\|beat /proc/1/cmdline`), one-shots disable it; verified all 8 services healthy on a live stack |

### 4.2 Verified already sound

- **MT5 worker auth**: `hmac.compare_digest` constant-time comparison, **fails closed** when
  `MT5_WORKER_TOKEN` is unset; worker is read-only with no order-execution capability.
- **Ownership scoping** across screenshots, analyses, evaluations, conversations, journal.
- **Private screenshot storage** outside public `MEDIA_ROOT`.
- **Secrets**: `.env` is gitignored (confirmed absent from `git status`), `.env.example`
  holds placeholders only, `prod.py` refuses to boot without required secrets.
- **Honesty guards**: `NO TRADE` cannot be overridden by the LLM; uncalibrated probability
  is withheld; OTC is never substituted with regular forex; real/demo/backtest/hypothetical
  provenance is never blended.

### 4.3 Remaining accepted risks (documented, not fixed)

1. No automated test asserts CSRF or rate-limit behaviour (coverage gap, not a known defect).
2. API docs are off in production, but the schema endpoint must be verified off after deploy.

> **Closed in the `.env` connectivity follow-up** (findings 10–13 above): every variable
> the code reads now has a supplier, is documented in `.env.example`, and is actually
> consumed — enforced by `scripts/check_env_coverage.py` (exit 0 required) and
> `tests/test_phase10_env_wiring.py`. The only intentionally-unset key is
> `DJANGO_CORS_ALLOWED_ORIGINS`, documented empty in the template so the code default
> `[]` applies (same-origin deployment; no CORS needed).

---

## 5. Critical unresolved issues

These are real, verified, and **deliberately not fixed** — each belongs to an earlier phase's
scope or would require a design decision with data-integrity risk.

| # | Issue | Impact | Why not fixed in Phase 10 |
|---|---|---|---|
| **C1** | `POST /api/strategies/evaluate/` returns **HTTP 501** (stub in `apps/strategy_engine/views.py`) | Public evaluate endpoint unusable; a test currently asserts the 501 | Wiring it correctly requires re-deriving `sync_status`/feed-compatibility/timing inputs that the orchestrator already builds. Guessing risks weakening verification guards. **Phase 6 scope decision.** |
| **C2** | `apps/research/views.py` is **entirely stubs** (`{"results": []}`, bare 202) | Phase 7 REST API returns empty data while docs claim it works | Implementing the research API is Phase 7 work; Phase 10 is audit/secure/deploy. **Documentation discrepancy must be corrected.** |
| **C3** | `ReasoningProvider` has **no real HTTP implementation** — a non-mock provider always returns the safe fallback | No live reasoning-LLM round trip has ever run | Fails safe (never fabricates an explanation), so it is a completeness gap, not a safety defect. |
| **C4** | `TimingValidator._parse_time` **strips UTC offsets**, returning naive datetimes | If inputs carry `Z`/`+00:00` timestamps, subtraction can raise; the orchestrator catches it and degrades to `NO TRADE` | Fails safe (abstains), but silently discards timezone info — should be fixed before trusting timing-sensitive results. |
| **C5** | No live MT5 terminal and no hosted LLM available in this environment | Those round trips remain unverified | Environment limitation, not fixable in code. |
| **C6** | ~~PostgreSQL restore drill not executed~~ → **drilled 2026-10-18, PASSED** | Production backup tooling + process now proven on live PostgreSQL 16 (§12); one production-topology run still recommended before first launch | Drill record: `docs/backup_restore.md` §7 |
| **C7** | `PHASE-6-REPORT.md` / `PHASE-7-REPORT.md` overstate API completeness | Misleading documentation | Should be corrected to match C1/C2. |

---

## 6. MT5 connectivity status

| Aspect | Status |
|---|---|
| Client / connection management | ✅ Implemented, tested with fakes |
| Read-only enforcement | ✅ Verified — no order-execution code exists in the repository |
| Worker authentication | ✅ `X-Worker-Token`, constant-time, fail-closed |
| Heartbeat / identity | ✅ `WorkerHeartbeat` model + `mt5_worker` command |
| Symbol mapping / broker server | ✅ Modelled and tested |
| **Live terminal connection** | ❌ **NOT VERIFIED** — no terminal reachable in this environment |
| Data freshness on live feeds | ⚠️ Code paths tested with fixtures only |

**Net:** the integration is code-complete and safe, but a live connection has not been proven.

## 7. AI provider status

| Provider | Implementation | Live verified | Failure behaviour |
|---|---|---|---|
| Vision | Real OpenAI-compatible HTTP client, timeout, bounded retries, rate-limit backoff, prompt/schema versioning | ❌ not exercised live | Typed exceptions; analysis fails, **never fabricates observations** |
| Reasoning | Deterministic mock + fallback only (**C3**) | ❌ no live path exists | Returns a safe stub; **never invents an explanation**, cannot override `NO TRADE` |

**Net:** both providers fail safe. Neither has completed a real round trip here.

## 8. Probability calibration status

- **No calibrated model exists in this deployment.** `ProbabilityPresenter().present(None)`
  → `available: False`, and UAT-09 confirms no success probability is quoted.
- Confluence scores are never presented as probabilities; directional, binary-settlement and
  confluence outputs are kept strictly separate.
- Backtests now report `accuracy_status: "not_evaluated"` with `directional_accuracy: null`
  when no forward outcome was settled — **a run can no longer imply an accuracy figure it
  did not measure.**
- **No held-out evaluation has been completed**, therefore **no statistical validity claim
  is made anywhere in this project.**

## 9. Historical validation limitations

- Replay records **decisions only**; forward settlement is not simulated, so win rate is
  structurally unavailable (by design, reported as "not evaluated").
- Datasets smaller than `MIN_HISTORY + 2` (22 candles) **fail the run explicitly** rather
  than emitting a sample-less report.
- MT5 backtests are **not** claimed to reproduce IQ Option settlement — different broker,
  different feed, different settlement rules.
- Walk-forward/baseline services exist but have **not** been run against a real, sufficiently
  large dataset in this environment.

---

## 10. Performance measurements

Measured on this workstation by `scripts/benchmark_pipeline.py` (25–50 iterations per
stage, two runs). Full tables, methodology, query analysis and budgets:
`docs/PHASE-10-PERFORMANCE.md`. **Vision and reasoning stages ran against the mock
providers — these are not live-LLM latencies.**

| Stage | Median | p95 | Queries | M1 budget | Verdict |
|---|---|---|---|---|---|
| Upload + image validation | 26.9 ms | 30.8 ms | — | ≤ 1,000 ms | ✅ fits |
| Vision analysis (**mock provider**) | 91.3 ms | 114.1 ms | — | ≤ 2,000 ms | ✅ fits **under mock only** |
| Market candles API `GET /api/market/candles/?limit=60` | 238.7 ms | 263.7 ms | 64 → constant ≤10 after fix | ≤ 500 ms | ✅ median fits; N+1 fixed |
| Synchronization verify | 126.2 ms | 153.2 ms | — | ≤ 1,000 ms | ✅ fits |
| Strategy evaluation | 7.1 ms | 9.9 ms | — | ≤ 500 ms | ✅ fits |
| Dashboard overview build | 47.6 ms | 53.6 ms | 14 (constant) | ≤ 1,000 ms | ✅ fits |
| Assistant explanation (**mock provider**) | 0.010 ms | 0.016 ms | — | ≤ 2,000 ms | ✅ fits **under mock only** |

- Machine-side stage sum with mock LLMs ≈ **490 ms** against an end-to-end M1 signal
  budget of ≤ 5,000 ms (`PHASE-10-PERFORMANCE.md` §5).
- Endpoint medians (full request path incl. auth/session/templates): dashboard 87.0 ms,
  analyses 77.8 ms, journal trades 67.1 ms, vision history 57.8 ms, performance 20.7 ms.
- **N+1 found and fixed**: `MarketCandleListAPIView` issued 64 queries for 60 candles
  (`symbol.canonical`/`symbol.broker_symbol` sourced per row without `select_related`);
  now a small constant. `tests/test_phase10_performance.py` fails if query count grows
  with row volume, and re-checks the response shape and auth requirement.
- **Honest limits:** mock figures are *not* live-LLM figures (a hosted call adds
  network RTT + generation time — unmeasured here); tail latencies are noisy on this
  shared workstation (run-1 p95 for the candles endpoint was 792 ms) — re-benchmark on
  deployment hardware before publishing any latency SLO.

## 11. Deployment readiness

| Item | Status |
|---|---|
| `Dockerfile` (non-root, no embedded credentials, healthcheck) | ✅ |
| `compose.yaml` / `compose.prod.yaml` (Postgres & Redis loopback/internal only) | ✅ |
| `docker/entrypoint.sh` (wait → migrate → collectstatic → exec) | ✅ |
| CI (`.github/workflows/ci.yml`) — lint, tests, deploy checks, migration validation, `pip-audit`, container verification | ✅ |
| Deploy gate (`deploy.yml`) — manual `workflow_dispatch` + `production` environment approval | ✅ configured; **Required reviewers must be set in GitHub** |
| Production settings validated (`check --deploy`) | ✅ 0 security warnings |
| Container build executed here | ✅ **EXECUTED** — `docker build` → `nazbeen-academy:phase10` (423 MB); see §11.1 |
| Live deployment | ❌ **Not performed — no authorization granted** |

### 11.1 Container build and image verification (executed)

Executed on 2026-10-18 with Docker 29.8.2 (earlier drafts reported this blocked
while Docker Desktop was paused; the block was lifted):

| Check | Result |
|---|---|
| `docker build -f Dockerfile -t nazbeen-academy:phase10 .` | ✅ exit 0 (all 8 stages) |
| Image size | 423 MB |
| **No `.env` inside the image** | ✅ `test -f /app/.env` → absent (`.dockerignore` effective) |
| Healthcheck binary | ✅ `curl` present (`HEALTHCHECK CMD` can pass) |
| Runtime user | ✅ `uid=10001(app)` — non-root |
| Runtime imports | ✅ `django 5.2.18`, `uvicorn`, `sentry-sdk` import cleanly |
| Entrypoint chain | ✅ migrate (30 migrations OK) → collectstatic (156 copied / 147 post-processed) → `manage.py check` → **exit 0** |
| `docker compose -f compose.yaml config --quiet` | ✅ exit 0, **0 interpolation warnings** |
| `docker compose -f compose.prod.yaml config --quiet` | ✅ exit 0 (deploy-time values supplied) |
| **Full dev stack boot** (`docker compose up -d`) | ✅ exit 0 — all 8 services **healthy** (db, redis, web, beat, 4 workers); one-shots migrate + collectstatic **Exited (0)**; PostgreSQL migrations applied to a real postgres:16; host `POSTGRES_PORT` moved to 55432 via the documented knob (host already runs its own PostgreSQL on 5432) |
| Host → container HTTP | ✅ `GET http://127.0.0.1:8000/healthz/` → 200 `{"status": "ok", … "checks": {"database": {"status": "ok", "vendor": "postgresql"}}}` |
| PostgreSQL restore drill | ✅ executed & passing — see §12 |

**Three defects were found and fixed during this step:**

1. `/app` was root-owned (WORKDIR-created), so a standalone
   `docker run … RUN_MIGRATIONS=1` failed with
   `sqlite3.OperationalError: unable to open database file`. The Dockerfile now
   `chown`s `/app` to the runtime user; compose stacks were unaffected (they use
   PostgreSQL, and beat writes its schedule to `/tmp`), but dev-SQLite and
   standalone boots now work.
2. The `DJANGO_SECRET_KEY` value contained an unquoted `$…` fragment: django-environ
   keeps it literal while docker compose's dotenv interpolation replaces it with an
   empty string — containers would have run with a **silently different** secret
   than the host (plus warnings on every `compose config`). Single-quoting made
   both parsers agree (host digest verified byte-identical, warnings → 0); a
   permanent `UNQUOTED-DOLLAR` gate now fails `scripts/check_env_coverage.py`
   if such a value reappears.
3. The image-level `HEALTHCHECK` (probe `:8000/healthz/`) is inherited by **every**
   container from the image — worker/beat containers never listen on `:8000`, so
   they showed **permanently unhealthy** in `docker compose ps` even while running
   correctly (beat started fine, authenticated to Redis, and ticked). Both compose
   files now override it: workers/beat use a PID-1 process-liveness check
   (`grep -q worker|beat /proc/1/cmdline`, verified inside live containers) and
   one-shot services disable it. After the fix: **all 8 services report healthy**.

## 12. Backup / restore verification

| Path | Status |
|---|---|
| SQLite development drill | ✅ **VERIFIED** — `scripts/verify_backup_restore.py`: backup → sha256 → per-table content hash → restore → identical (17 tables / 77 rows); negative control proved a modified row **is** detected |
| Finding from the drill | ⚠️ `PRAGMA integrity_check` alone **missed** data-level corruption; the content fingerprint is the real guard |
| PostgreSQL production drill | ✅ **VERIFIED 2026-10-18** — live PostgreSQL 16: `pg_dump` (2.8 s, 217 KB, sha256) → `pg_restore` into scratch DB (45.5 s, exit 0) → identical (1 probe user / 33 migrations / 49 tables) → `manage.py check` on restored DB: 0 issues; full record in `docs/backup_restore.md` §7 |
| Screenshot storage backup | ✅ implemented in `docker/backup.sh` (tar + manifest + optional GPG), **not yet run in a real restore** |

## 13. Remaining operational risks

1. **PostgreSQL recovery** (C6, downgraded) — drill passed 2026-10-18 (tooling + process
   proven on live PostgreSQL 16); residual risk is production-topology specifics (remote
   dump transfer, media restore), which one production run before launch will cover.
2. **Undocumented-in-code stubs** (C1, C2, C7) — operators may believe features exist that
   return empty or 501 responses.
3. **No reasoning provider** (C3) — assistant explanations are non-fabricated but generic.
4. **Timezone handling** (C4) — timing decisions degrade to `NO TRADE` under mixed-tz inputs;
   safe today, but a latent correctness issue.
5. **No security regression tests** for CSRF/rate-limiting.
6. **Live integrations unverified** (C5) — MT5 and LLM behaviour in production is predicted,
   not observed.
7. **`beat` service must be running** or retention purges silently stop (schedule now exists,
   but only if `beat` is up).

---

## 14. Evidence index

| Claim | Where to verify |
|---|---|
| Full test suite | `.\.venv\Scripts\python.exe -m pytest -q` → 689 passed, 2 skipped |
| Repository audit | `docs/PHASE-10-AUDIT.md` |
| UAT outcomes | `docs/PHASE-10-UAT.md`, `tests/test_phase10_uat.py` |
| Failure coverage | `tests/test_phase10_failures.py` (64 tests) |
| `.env` ↔ code ↔ template wiring | `scripts/check_env_coverage.py` (exit 0), `tests/test_phase10_env_wiring.py` (23 tests) |
| Query-efficiency guards | `tests/test_phase10_performance.py` (3 tests) |
| Container build + image verification | `docs/PHASE-10-RELEASE-READINESS.md` §11.1; image `nazbeen-academy:phase10` |
| Restore drill | `scripts/verify_backup_restore.py` |
| Security detail | `docs/security.md` |
| Operations | `docs/operations.md`, `docs/incident_response.md` |
| Deployment | `docs/deployment.md`, `Dockerfile`, `compose*.yaml` |

**Phase 10 status: COMPLETE.** All 15 Phase 10 acceptance criteria are addressed; criteria
backed by unexecuted external prerequisites (live MT5/LLM verification, production-topology
restore run, production deployment) are reported as **open**, not as satisfied.

*Stopped here as instructed. Awaiting approval before any Phase 10 follow-up or Phase 11 work,
and no production deployment will be performed without explicit authorization.*
