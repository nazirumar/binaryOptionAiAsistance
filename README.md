# Nazbeen Academy Binary Ai Asisstance

An AI-powered **analysis and research** assistant for binary-option chart study.
Upload an IQ Option candlestick screenshot, and the system cross-checks it against a
MetaTrader 5 reference feed, applies the Nazbeen Academy price-action knowledge base,
and produces an evidence-based, honestly-caveated analysis.

> **This application is an analysis and research tool. It never places trades and does
> not guarantee outcomes. It will not report UP/DOWN probabilities until a statistical
> model has been calibrated on sufficient, chronologically separated data.**

---

## Status

Phases are delivered incrementally and only after their checks pass.

| Phase | Name | Status |
| ----- | ---- | ------ |
| 1 | Foundation | ✅ Complete |
| 2 | MT5 integration | ✅ Complete — live terminal verified 2026-10-18 (MetaQuotes-Demo, read-only) |
| 3 | Screenshot vision | ✅ Complete — live provider verified 2026-10-18 (daily free-tier quota limited) |
| 4 | Data synchronization | ✅ Complete (screenshot/MT5 verification) |
| 5 | Price-action knowledge engine | ✅ Complete |
| 6 | Strategy evaluation | ✅ Complete |
| 7 | Backtesting & probability calibration | ✅ Complete |
| 8 | AI assistant | ✅ Complete |
| 9 | Dashboard & analytics | ✅ Complete |
| 10 | Security, integration testing & deployment | ✅ Complete — **READY FOR CONTROLLED PAPER TESTING** (not production) |
| 11 | Critical integration remediation & live validation | ✅ Complete — pipeline end-to-end, real APIs, durable jobs, reasoning LLM live-verified |

See [`docs/PHASE-1-REPORT.md`](docs/PHASE-1-REPORT.md),
[`docs/PHASE-2-REPORT.md`](docs/PHASE-2-REPORT.md),
[`docs/PHASE-3-REPORT.md`](docs/PHASE-3-REPORT.md),
[`docs/PHASE-4-REPORT.md`](docs/PHASE-4-REPORT.md),
[`docs/PHASE-5-REPORT.md`](docs/PHASE-5-REPORT.md),
[`docs/PHASE-6-REPORT.md`](docs/PHASE-6-REPORT.md),
[`docs/PHASE-7-REPORT.md`](docs/PHASE-7-REPORT.md),
[`docs/PHASE-8-REPORT.md`](docs/PHASE-8-REPORT.md),
[`docs/PHASE-9-REPORT.md`](docs/PHASE-9-REPORT.md),
[`docs/PHASE-10-RELEASE-READINESS.md`](docs/PHASE-10-RELEASE-READINESS.md) and
[`docs/PHASE-11-COMPLETION-REPORT.md`](docs/PHASE-11-COMPLETION-REPORT.md) for
completion reports. Phase 10 evidence:
[`docs/PHASE-10-AUDIT.md`](docs/PHASE-10-AUDIT.md) (repository audit),
[`docs/PHASE-10-UAT.md`](docs/PHASE-10-UAT.md) (13/13 UAT scenarios) and
[`docs/PHASE-10-PERFORMANCE.md`](docs/PHASE-10-PERFORMANCE.md) (latency/query
measurements). Phase 11 evidence:
[`docs/PHASE-11-LIVE-VALIDATION.md`](docs/PHASE-11-LIVE-VALIDATION.md) (live /
mocked / not-executed status buckets). Open launch-blocking items are listed in
§5 of the readiness report. (The PostgreSQL restore drill was executed and
passed on 2026-10-18.)
The **MT5 integration** was exercised live against a real MetaTrader 5
terminal (MetaQuotes-Demo, strictly read-only) on 2026-10-18: connection, 14
symbol mappings seeded, and a worker cycle persisting 600 real EURUSD candles
plus an online heartbeat — see §4a of the live-validation report.
**Screenshot vision** completed real hosted-model round trips (Gemini
`gemini-3.8-flash` via its OpenAI-compatible endpoint) on 2026-10-18; the final
schema-validated persisted run is gated only by the free-tier daily request
quota (20 requests/day, resets nightly).
The **reasoning LLM** integration was exercised live against Google Gemini and
passed on 2026-10-18 (Phase 11 CP4); it was re-verified live against **Groq**
(`qwen/qwen3.8-27b`, user-supplied key) the same day.
Phase 5 implements the price-action knowledge engine as deterministic detectors +
`PriceActionEngine` (in-memory, no live data); see
[`docs/PRICE-ACTION-KNOWLEDGE-BASE.md`](docs/PRICE-ACTION-KNOWLEDGE-BASE.md).
See [`docs/MT5-INTEGRATION.md`](docs/MT5-INTEGRATION.md),
[`docs/CHART-VISION.md`](docs/CHART-VISION.md) and
[`docs/MARKET-SYNC.md`](docs/MARKET-SYNC.md) for setup and usage.

---

## Technology

- **Backend:** Python 3.12+, Django 5.2, Django REST Framework, Celery, Django Channels
- **Data:** PostgreSQL (production) / SQLite (development, tests), Redis (broker/cache)
- **Frontend:** Django Templates, HTMX, Tailwind CSS (light & dark themes)
- **Quality:** pytest / pytest-django, Ruff, type hints, structured logging
- **Deployment:** Docker (non-root, healthcheck), docker compose (dev & prod),
  GitHub Actions CI + manually-triggered gated deploy, scheduled backups

## Architecture at a glance

```
apps/
  core/        shared infrastructure: base models, logging, middleware, health
  accounts/    custom user model, authentication, user preferences
  dashboard/   authenticated HTMX/Tailwind UI, analytics & reporting services
  api/         Django REST Framework surface
  market_data/ MT5 connection, symbols, candles/ticks, worker, health (Phase 2)
  chart_vision/ screenshot upload, vision extraction, structured observations (Phase 3)
  market_sync/  screenshot-vs-MT5 synchronization, feed compatibility, statuses (Phase 4)
  price_action/ deterministic price-action knowledge engine + evidence/conflicts (Phase 5)
  strategy_engine/ strategy evaluation & persistence (Phase 6)
  research/     backtesting & probability calibration (Phase 7)
  ai_assistant/ conversational analysis assistant (Phase 8)
  trading_journal/ manual journal + provenance-segmented performance (Phase 9)
config/
  settings/    base / dev / test / prod (12-factor, env-driven)
  urls.py, asgi.py, wsgi.py, celery.py
templates/     base + app templates
static/        CSS / JS
tests/         pytest suite
docs/          architecture, checklists, reports
```

Full details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Quickstart (development)

Requires **Python 3.12+**. PostgreSQL/Redis are optional for local development
(SQLite and in-memory fallbacks are used when unset).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements/dev.txt

Copy-Item .env.example .env          # then edit as needed
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/ and create an account.

### Run the checks

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
python manage.py check
python scripts/scan_secrets.py .          # secret scan
python scripts/check_env_coverage.py      # .env <-> code <-> .env.example wiring
```

Or run everything at once:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```

### Run the whole stack (web + Celery workers + beat)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_all.ps1
```

Both launchers also have a thin CMD wrapper, so they can be started from a plain
Command Prompt (`cmd.exe`) — arguments are forwarded unchanged and the exit code
is propagated:

```bat
scripts\run_all.cmd
scripts\run_all.cmd -WithMT5
scripts\check.cmd
```

### Environment notes

- The project targets **Python 3.12+**. This repository was developed and verified on
  **Python 3.13** because 3.12 was not available on the development machine.
- Development and tests run on **SQLite** with in-memory Celery/Channels fallbacks.
  **Production requires PostgreSQL (`DATABASE_URL`) and Redis (`REDIS_URL`)** and refuses
  to start without them.
- A fully-resolved dependency snapshot is available in
  [`requirements/lock.txt`](requirements/lock.txt). Dependencies were installed with
  `uv` due to unstable PyPI connectivity during development.

---

## Configuration

All configuration is environment-driven (see [`.env.example`](.env.example)).
Production (`config.settings.prod`) refuses to start without a secret key,
explicit allowed hosts, a PostgreSQL `DATABASE_URL`, and a `REDIS_URL`.

---

## Data-integrity principles

- IQ Option and MT5 data are never assumed identical.
- Screenshot/MT5 comparisons explicitly detect mismatched symbols, timeframes,
  timestamps, price levels and unsupported OTC instruments.
- When verification is impossible the system reports **UNVERIFIED DATA** or
  **DATA MISMATCH** instead of a confident prediction.
- A successful screenshot/MT5 match validates data consistency, **not** future
  price direction.

---

## License

Proprietary. © Nazbeen Academy.
"# binaryOptionAiAsistance" 
