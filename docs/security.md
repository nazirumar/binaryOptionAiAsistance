# Security Model

Scope: how this application is secured today, what was hardened recently, and
— with equal prominence — what is **not** covered yet. The app is an analysis
research tool; it performs no trading. This document describes only mechanisms
that exist in the codebase.

## 1. Authentication and sessions

- Custom user model `accounts.User` (`AUTH_USER_MODEL`).
- Password validators: user-attribute similarity, minimum length, common
  password, numeric (`config/settings/base.py`).
- DRF defaults: `SessionAuthentication` + `TokenAuthentication`, and
  `IsAuthenticated` as the global default permission — anonymous requests are
  rejected everywhere except `/healthz/` and public page views.
- Session cookies: `SESSION_COOKIE_HTTPONLY=True`; in production
  `SESSION_COOKIE_SECURE=True`.
- `LOGIN_URL = accounts:login`; login/logout/dashboard redirects are named
  routes.

## 2. CSRF

- Django `CsrfViewMiddleware` is enabled globally.
- In production `CSRF_COOKIE_SECURE=True`. `CSRF_COOKIE_HTTPONLY` is
  deliberately `False` because the HTMX frontend reads the token from the
  cookie — acceptable because the token is not a credential by itself.
- Browser POSTs from another origin require the origin in
  `DJANGO_CSRF_TRUSTED_ORIGINS` (e.g. `https://your-domain.example`).

## 3. HTTPS / transport security (`config/settings/prod.py`)

- `DEBUG=False` (hardcoded).
- `SECURE_SSL_REDIRECT=True` by default (HTTP → 301).
- HSTS: `SECURE_HSTS_SECONDS` (default 30 days in code; `.env.example`
  suggests starting at 86400 and raising once HTTPS is confirmed — browsers
  cannot undo HSTS before it expires, so raise deliberately), plus
  `SECURE_HSTS_INCLUDE_SUBDOMAINS=True` and `SECURE_HSTS_PRELOAD=True`.
- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` — only
  meaningful when the reverse proxy sets the header (see `docs/deployment.md`).
- `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` = True.
- The app refuses to boot without `DJANGO_SECRET_KEY`, a real
  `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`, and `REDIS_URL`.

## 4. Security headers

- `SECURE_CONTENT_TYPE_NOSNIFF=True`, `X_FRAME_OPTIONS=DENY` (clickjacking
  middleware also enabled).
- WhiteNoise serves statics with cache-hardening headers.
- Verified result: `manage.py check --deploy` under production settings
  reports **zero `security.*` warnings**; the only output is drf-spectacular
  `W001`/`W002` schema-naming warnings (enum/operationId conventions), which
  are documentation-quality issues, not security findings.

## 5. Rate limiting (DRF throttling)

Configured in `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`, all overridable via
environment (defaults from `.env.example`):

| Scope | Default | Applies to |
|---|---|---|
| `market_read` | 240/minute | Market-data reads |
| `market_ingest` | 1200/minute | MT5 worker ingest endpoints |
| `vision_upload` / `vision_read` | 30/min / 240/min | Screenshot upload & read |
| `sync_verify` / `sync_read` | 60/min / 240/min | Chart-vs-MT5 sync |
| `assistant_upload` / `assistant_read` | 30/min / 240/min | AI assistant endpoints |
| `journal` | 60/min | Trading journal |
| `dashboard` | 120/min | Dashboard API |

No WAF or IP-level limit exists at the app tier; Nginx-level limits
(`limit_req`) are recommended in front but are not shipped in this repo.

## 6. Request-size and upload validation

- Global body limit `MAX_UPLOAD_SIZE_BYTES` (default 10 MiB) enforced via
  `DATA_UPLOAD_MAX_MEMORY_SIZE` / `FILE_UPLOAD_MAX_MEMORY_SIZE`.
- Screenshot uploads additionally bounded by `VISION_MAX_UPLOAD_BYTES`
  (8 MiB default), min/max width/height, `VISION_MAX_PIXELS` (Pillow
  decompression-bomb guard), and re-encoding during preprocessing
  (`VISION_PREPROCESS_MAX_DIMENSION`).
- CSV exports written by `apps/dashboard/services/reporting_service.py` use
  `safe_cell`/`write_row`, which neutralise spreadsheet formula injection
  (leading `=`, `+`, `-`, `@`).

## 7. User-data isolation

- The dominant pattern is **owner scoping**: querysets and serializers filter
  by `owner=request.user`; objects belonging to other tenants return 404/403,
  not the object.
- Screenshots are stored outside public `MEDIA_ROOT` and streamed only through
  an authenticated, ownership-checked endpoint.
- MT5 connection profiles: `apps/market_data/permissions.py`
  `accessible_profiles()`/`resolve_profile()` return a user's own plus
  system-shared (ownerless) profiles; an inaccessible id raises `LookupError`
  (mapped to an error response, not a disclosure).
- Cross-tenant writes are validated: e.g. journal entries validate that the
  referenced analysis belongs to the requesting user
  (`apps/trading_journal/serializers.py::validate_analysis`).
- Health diagnostics (`/healthz/detail/`) are staff-only and expose no
  credentials or connection strings.

## 8. Worker authentication (MT5 ingest)

`apps/market_data/permissions.py::IsWorkerToken` compares the `X-Worker-Token`
header against `MT5_WORKER_TOKEN` using `hmac.compare_digest` (constant-time),
and **fails closed**: when the setting is unset, every worker request is
denied. The token is a shared secret delivered to the Windows worker over TLS
only (see `docs/mt5_worker.md`).

## 9. Secrets management

- No secret is baked into the image (CI verifies the built image contains no
  `.env` and runs as a non-root uid).
- Production reads secrets from `/etc/nazbeen-academy/.env` on the server
  (root-only, `chmod 600`); the deploy workflow never transfers them.
- MT5 credentials live only in the Windows worker environment; connection
  profiles in the database store non-secret identifiers plus a
  `credential_ref` — passwords are never persisted.
- LLM provider keys are read from the environment, never stored in the
  database, and never logged.
- `.env.example` is the authoritative placeholder list; every real value must
  be replaced.

## 10. Secret scanning and CI gates

- `scripts/scan_secrets.py` runs in CI on every push/PR and fails the build on
  anything resembling a committed credential.
- CI also runs `pip-audit` on `requirements/base.txt` (blocking, `--strict`)
  and `requirements/dev.txt` (advisory).
- Container verification: no `.env` in the image, non-root user.
- There is **no deploy job in CI**; production deployment is a separate,
  manually approved workflow (`docs/deployment.md`).

## 11. Logging, correlation IDs, redaction

- Production logs are one JSON object per line (`apps/core/logging.py`), each
  carrying `timestamp`, `level`, `logger`, `message`, and `request_id`.
- `RequestIDMiddleware` accepts or generates `X-Request-ID` and echoes it on
  the response, so a user-reported id can be traced across web + worker logs.
- The documented policy is that credentials, tokens, and payloads are never
  logged; `mt5_worker` masks account numbers (`mask_account`) and connection
  errors are logged by exception type.
- **Header redaction is wired and tested.** `DJANGO_LOG_REDACT_HEADERS` (default
  `Authorization,Cookie,X-API-Key`) drives `apps.core.logging.RedactHeadersFilter`,
  attached to the `console` handler in `LOGGING`, so both the verbose and JSON
  formatters emit masked values (`Authorization: Bearer <jwt>` → `***`), covering
  messages, structured extras, `HTTP_AUTHORIZATION`-style META names and
  `Set-Cookie`. **Scope:** log records only — exception tracebacks are rendered
  after filters run, so secrets must still never be placed into exception
  messages. Regression tests: `tests/test_phase10_env_wiring.py`.
- **Sentry is wired.** `SENTRY_DSN` is read by `config.settings.prod`, which calls
  `apps.core.observability.init_sentry()`. Empty DSN (default) keeps it off; a set
  DSN requires `sentry-sdk` from `requirements/prod.txt`, otherwise the app refuses
  to boot rather than losing reports silently. Initialized with
  `send_default_pii=False` and `traces_sample_rate=0.0` (errors only — no request
  bodies, cookies or headers leave the host). Dev/test settings never initialize it.

## 12. Security fixes applied (this hardening pass)

1. **Backtest dataset IDOR** — `apps/dashboard/page_views.py`: dataset detail
   views now scope to the owner instead of trusting a raw id.
2. **Shared-dataset NULL matching bug** — ownerless (system/shared) datasets
   are matched consistently instead of silently falling through a NULL
   comparison.
3. **CSV formula injection** — `safe_cell`/`write_row` in
   `apps/dashboard/services/reporting_service.py`.
4. **Journal cross-tenant FK** — `validate_analysis` in
   `apps/trading_journal/serializers.py` rejects referencing another user's
   analysis.
5. **MT5 ingest** — fail-closed token permission (above).
6. **Prod boot guard** — `config/settings/prod.py` raises
   `ImproperlyConfigured` on missing/placeholder core secrets.

## 13. Known gaps / accepted risks

These are real and verified; do not describe the system as hardened against
them:

1. `POST /api/strategies/evaluate/` returns **HTTP 501** (stub in
   `apps/strategy_engine/views.py`). The engine service works internally but
   is not exposed.
2. `apps/research/views.py` is entirely stubs (`{"results": []}`, bare 202) —
   the research REST API is not functional.
3. `ReasoningProvider` has **no real HTTP implementation**; any non-mock
   provider returns the safe fallback. No live LLM round trip is verified.
4. `TimingValidator._parse_time` strips UTC offsets (naive datetimes) — it
   fails safe to NO TRADE, but silently discards timezone information.
5. No live MT5 terminal or hosted LLM was reachable in the build environment;
   those network paths are untested end-to-end.
6. `daphne` is not used; uvicorn is the ASGI server (daphne absent from
   requirements).
7. PostgreSQL backup/restore **was drilled against a live PostgreSQL 16 on
   2026-10-18** (dump → scratch-restore → verification → app check, all passing;
   `docs/backup_restore.md` §7). One production-topology run before first
   production use is still recommended.
8. Log redaction and Sentry are **wired** (`DJANGO_LOG_REDACT_HEADERS`,
   `SENTRY_DSN` → `init_sentry()` in `config.settings.prod`) and covered by
   `tests/test_phase10_env_wiring.py`; see §11.
9. No independent third-party security review or penetration test has been
   performed.
10. No dedicated audit trail exists for user/admin actions beyond structured
    application logs.

None of the above implies the app is unsafe for its current research use; all
of them block any claim of production-readiness.
