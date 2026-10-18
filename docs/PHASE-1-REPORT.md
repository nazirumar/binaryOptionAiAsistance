# Phase 1 — Foundation · Completion Report

**Status: COMPLETE — all required checks passed.**
Date: 2026-10-17 · Scope: project foundation only (no MT5, AI, or strategy logic yet).

---

## 1. Environment

| Item | Target | Actual in this environment | Notes |
| ---- | ------ | -------------------------- | ----- |
| OS | Windows (MT5 host) | Windows 10/11 | MT5 worker is Windows-only by design |
| Python | 3.12 | **3.13.14** | 3.12 not installed on the machine; code targets 3.12+ and runs on 3.13 |
| Django | 5.x | 5.2.18 | |
| DRF | — | 3.18.3 | |
| PostgreSQL | required in prod | 18 installed (service running) | Phase 1 dev/test use SQLite; Postgres wired via `DATABASE_URL` |
| Redis | required in prod | not installed | Celery/Channels fall back to in-memory for dev/test |
| Package manager | pip | **uv** 0.12.19 | PyPI connectivity was unstable; `uv` used to complete installs |

Full resolved dependency set: [`requirements/lock.txt`](../requirements/lock.txt).

### Deviations from the brief (explicit)
1. **Python 3.12 → 3.13.** Python 3.12 is not present and could not be installed
   given the environment's poor network. Everything is written for 3.12+ and verified
   on 3.13. This must be revisited if strict 3.12 parity is required.
2. **SQLite for dev/test; PostgreSQL for production.** `config.settings.prod` refuses to
   start without a PostgreSQL `DATABASE_URL`, and a system check (`core.E001`) forbids
   SQLite outside `DEBUG`. PostgreSQL 18 is installed but no database/role was created
   for this project yet.
3. **Redis/Celery/Channels fall back to in-memory** when `REDIS_URL` is unset, so the
   foundation is fully runnable/testable without external services. Production requires
   `REDIS_URL`.
4. **Tailwind via CDN for the foundation phase.** A compiled Tailwind pipeline (Node or
   the standalone CLI) is planned for a later UI phase; CDN keeps Phase 1 build-free.

---

## 2. What was delivered

- **Split, 12-factor settings** (`base`/`dev`/`test`/`prod`) using `django-environ`.
- **Custom user model** defined from `accounts.0001_initial` (no future `AUTH_USER_MODEL` swap).
- **Core infrastructure:** abstract base models, request-id middleware, structured logging
  (console + JSON), app/theme context processor, health endpoint, deployment system check,
  sample Celery task.
- **REST API surface:** DRF defaults (auth required, paginating, versioned errors with
  `request_id`), `/api/health/`, `/api/me/`, OpenAPI schema + Swagger docs.
- **Frontend:** Tailwind + HTMX base layout, landing page, login/sign-up, authenticated
  dashboard shell with an HTMX-polled status card and a phase roadmap; light/dark theme
  persisted via cookie (server-rendered) and localStorage.
- **Async/realtime wiring:** Celery app autodiscovering tasks; Channels ASGI router with
  an allowed-hosts origin validator ready for later WebSocket progress streaming.
- **Quality infrastructure:** pytest/pytest-django, Ruff, coverage config, and a
  `scripts/check.ps1` gate that runs every check.

---

## 3. Verification results (commands actually run)

| Check | Command | Result |
| ----- | ------- | ------ |
| System check | `manage.py check` | ✅ no issues |
| Deploy check (prod) | `manage.py check --deploy --settings=config.settings.prod` | ✅ no issues |
| Migration drift | `manage.py makemigrations --check --dry-run` | ✅ No changes detected |
| Migrations | `manage.py migrate` | ✅ applied (accounts + Django + authtoken + sessions) |
| Lint | `ruff check .` | ✅ All checks passed |
| Format | `ruff format --check .` | ✅ 53 files already formatted |
| Tests | `pytest` | ✅ **31 passed** |
| Coverage | `pytest --cov=apps --cov=config` | ✅ **89%** |

Test scope: settings/consistency, health (Django + DRF), accounts model & auth flows,
API permissions/error envelope, pages/theme, structured logging & request-id middleware,
Celery eager task, all custom system checks, and ASGI/WSGI/Celery/Channels wiring.

---

## 4. Supported commands

```powershell
.\.venv\Scripts\python.exe manage.py runserver
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```

---

## 5. Unresolved issues & limitations

- **Python 3.12 parity** not verified (environment has 3.13 only).
- **No live PostgreSQL/Redis test** was performed; only configuration + fallbacks were
  validated. A Postgres-integration test is recommended for Phase 2.
- **`structlog` is installed but stdlib structured logging is used** for Django; full
  structlog pipeline is deferred until there is domain logging volume worth the complexity.
- **Tailwind is CDN-based**, not a compiled asset pipeline.
- **No CI pipeline** yet (GitHub Actions etc.).
- **No secret management** beyond environment variables; production must inject a strong
  `DJANGO_SECRET_KEY` (deploy check will warn otherwise).
- MT5, screenshot vision, the price-action engine, strategy evaluation, probability
  calibration, and the AI assistant are intentionally **not started** — they are Phases 2–8.

---

## 6. Recommendation for Phase 2 (MT5 integration)

- Create the PostgreSQL database/role and add a Postgres-backed integration test.
- Add `apps.marketdata`: MT5 worker over a Windows process, symbol mapping, timeframe
  normalization, and feed-health monitoring.
- Add an `MT5_LOGIN`/`MT5_SERVER`/`MT5_PASSWORD` config surface and connection-health task.
- Ensure MT5/library calls never block the request cycle (Celery/worker boundary).

**Awaiting explicit approval before starting Phase 2.**
