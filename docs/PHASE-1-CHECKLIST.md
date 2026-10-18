# Phase 1 — Foundation · Implementation Checklist

Legend: `[x]` done & verified · `[ ]` pending.

## 1. Repository & tooling
- [x] Repository scaffolding (`.gitignore`, `.editorconfig`, `.env.example`, `README.md`, `docs/`)
- [x] `pyproject.toml` with Ruff, pytest, coverage configuration
- [x] Dependency sets (`requirements/base|dev|prod.txt`) + resolved `requirements/lock.txt`
- [x] `manage.py` with dev settings default
- [x] Convenience quality-gate script (`scripts/check.ps1`)

## 2. Django configuration
- [x] Split settings: `base`, `dev`, `test`, `prod`
- [x] 12-factor configuration via `django-environ` + `.env`
- [x] Production fail-fast guards (secret, hosts, PostgreSQL, Redis)
- [x] Static/media configuration (WhiteNoise via `STORAGES`)
- [x] Structured logging (console + JSON formatters, request-id filter)

## 3. Core app
- [x] Abstract base models (`TimeStampedModel`, `UUIDModel`)
- [x] Request-id middleware (generate / echo `X-Request-ID`)
- [x] Health-check view (`/healthz/`) with DB probe
- [x] Deployment system check registered in `CoreConfig.ready()` (`core.E001`)
- [x] Context processor (app metadata + theme + debug flag)
- [x] Sample Celery task (`core.health_probe`)

## 4. Accounts app
- [x] Custom `User` model (defined pre-first-migration)
- [x] Login / logout / sign-up
- [x] Admin registration
- [x] Initial migration (`accounts.0001_initial`)

## 5. API app
- [x] DRF configuration (auth, permissions, pagination, schema)
- [x] Consistent error envelope with request id
- [x] Health and current-user endpoints
- [x] OpenAPI schema/docs (drf-spectacular) at `/api/schema/`, `/api/docs/`

## 6. Frontend
- [x] Base layout with Tailwind + HTMX
- [x] Light/dark theme toggle (cookie + localStorage, no flash)
- [x] Landing page, auth pages, dashboard shell, HTMX status fragment

## 7. Async & realtime
- [x] Celery app + Redis/in-memory broker resolution
- [x] Channels ASGI router + channel-layer resolution

## 8. Quality gates (verified)
- [x] `manage.py check` — no issues
- [x] `manage.py check --deploy` (prod settings) — no issues
- [x] `manage.py makemigrations --check` — no changes
- [x] `manage.py migrate` — applied cleanly
- [x] `ruff check .` — all checks passed
- [x] `ruff format --check .` — 53 files formatted
- [x] `pytest` — 31 passed
- [x] Coverage — 89%

## 9. Documentation
- [x] `README.md`, `docs/ARCHITECTURE.md`, `docs/PRICE-ACTION-KNOWLEDGE-BASE.md`
- [x] `docs/PHASE-1-REPORT.md` completion report
