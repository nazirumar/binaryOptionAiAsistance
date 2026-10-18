# Production Checklist

> ## DO NOT SHIP WHILE ANY BOX BELOW IS UNCHECKED
>
> This system is a market **analysis research tool**. It has never been
> production-deployed from this repository, has never been independently
> security-reviewed, and its outputs are **not** statistically validated or
> profit-bearing claims. Nothing here makes it "production-ready"; this
> checklist defines what must be true before calling a deployment
> *operational for internal research use*.

Check each item in the live environment (not in theory) and record who and
when. Paths and commands referenced here are verified against this repository.

## A. Pre-launch

### Secrets & configuration
- [ ] `.env` created from `.env.example` on the server with **no placeholder
      left** (`chmod 600`), outside the image and outside git.
- [ ] `DJANGO_SECRET_KEY` is a freshly generated random value (not the dev
      default).
- [ ] `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` set to the real
      domain (prod settings refuse `localhost`-only hosts).
- [ ] `DATABASE_URL` and `REDIS_URL` point at the internal services; strong
      unique passwords for `POSTGRES_PASSWORD` / `REDIS_PASSWORD`.
- [ ] `MT5_WORKER_TOKEN` set identically on server and Windows worker
      (ingest fails closed otherwise — good — but then nothing works).
- [ ] LLM providers set deliberately to `mock` or to a real provider with
      keys present; remember the reasoning provider has **no real HTTP path**
      (gap §F3).

### TLS & network
- [ ] Nginx + Certbot live; HTTPS redirects working; `X-Forwarded-Proto`
      header set; `certbot renew --dry-run` passes.
- [ ] PostgreSQL and Redis are **not** reachable from any public interface
      (verify with an external port scan, not just the compose file).
- [ ] App publishes no host port in production (traffic only via the proxy).
- [ ] HSTS verified in browser headers; max-age chosen deliberately.

### Backups
- [ ] `docker compose run --rm backup` produces `postgres.dump` +
      `.sha256` + `MANIFEST.txt` (+ screenshot archive) with `go-rwx`
      permissions.
- [ ] Off-host copy configured (rsync/rclone) and encryption handled — note:
      GPG in-script encryption currently **does not work** because `gpg` is
      absent from the image (encrypt off-host or add `gnupg`).
- [ ] `.env` backed up separately (encrypted store).
- [ ] **Restore drill executed against live PostgreSQL** and timed; result
      recorded. (Not yet performed — see `docs/backup_restore.md` §7.)

### Monitoring & access
- [ ] External uptime check on `/healthz/` with alerting.
- [ ] Log aggregation of the JSON logs with alerting on `level: ERROR` spikes
      and `health_check.*` warnings.
- [ ] Staff accounts for `/healthz/detail/` exist; admin access restricted.
- [ ] On-call rotation and `docs/incident_response.md` known to responders.
- [ ] GitHub Environment `production` has **Required reviewers** configured
      (the deploy workflow's only approval gate).

## B. Deploy time
- [ ] CI is green on the exact commit: lint, secret scan, `manage.py check`,
      `check --deploy`, migration check, pytest+coverage, `pip-audit`
      (blocking on `requirements/base.txt`), container verification.
- [ ] Image tag recorded in the change log (it is your rollback key).
- [ ] Pre-deploy backup ran (workflow default; only emergencies skip it).
- [ ] `preflight` (`manage.py check --deploy`) passed on the server before
      `up -d`.
- [ ] Migration reviewed for reversibility; a fresh backup exists in case
      rollback needs it.
- [ ] Deploy executed via the manual `workflow_dispatch` workflow (never
      automatically) with an approver who did not author the change.

## C. Post-deploy verification
- [ ] `docker compose ps`: web + all four workers + beat + db + redis
      healthy/up.
- [ ] `GET /healthz/` → 200 `ok`.
- [ ] `GET /healthz/detail/` (staff) → `ok`, or `degraded` with a known,
      explainable reason.
- [ ] Smoke: register/login, dashboard loads, one screenshot upload + analysis
      (mock provider is acceptable if no real provider is configured), one
      journal entry, one CSV export (confirm formula-injection guard output).
- [ ] `X-Request-ID` present on responses; logs show matching `request_id`
      entries in JSON format.
- [ ] MT5 worker (if deployed): heartbeat fresh, `data_freshness` ok, candles
      arriving for mapped symbols.
- [ ] Statics load with hashed URLs; no 404s in browser console.
- [ ] Error page verified (trigger a 404); no DEBUG leakage, no stack traces.
- [ ] Post-deploy workflow step "health verification" is green.

## D. Standing claims discipline (never ship otherwise)
- [ ] No public-facing text claims the system is profitable, statistically
      validated, or production-grade.
- [ ] No description or demo implies automatic trading — the MT5 integration
      is read-only market data; no order-execution code exists.
- [ ] Probabilities are quoted only from validated, calibrated models; the
      calibration endpoint currently reports `unavailable_uncalibrated`
      (stubs — see §F2/F3).

## E. Documentation
- [ ] `docs/deployment.md`, `docs/security.md`, `docs/operations.md`,
      `docs/backup_restore.md`, `docs/mt5_worker.md`,
      `docs/incident_response.md` reviewed for this deployment's values
      (domain, paths, retention, alert thresholds).
- [ ] Change log entry: image tag, config changes, migrations, approver.

## F. Known gaps that currently block a "production research" classification

These are verified, real, and unresolved. Shipping with any of them open means
the deployment is explicitly **experimental/internal research**, nothing more:

1. `POST /api/strategies/evaluate/` returns HTTP **501 Not Implemented**
   (stub in `apps/strategy_engine/views.py`); the engine works only internally.
2. `apps/research/views.py` is **entirely stubs** (`{"results": []}`, bare
   202, empty model registry) — the research REST API is non-functional.
3. `ReasoningProvider` has **no real HTTP implementation**; non-mock providers
   always return the safe fallback. No live LLM round trip has been verified.
4. `TimingValidator._parse_time` strips UTC offsets (naive datetimes) — fails
   safe to NO TRADE, but silently discards timezone information.
5. No live MT5 terminal and no live hosted LLM were reachable during
   development; those network paths are untested end-to-end.
6. `daphne` is not used; uvicorn is the ASGI server (informational — `compose.yaml`'s
   header comment has been corrected to say uvicorn).
7. PostgreSQL backup/restore **was drilled on 2026-10-18** against a live
   PostgreSQL 16 and passed (`docs/backup_restore.md` §7); repeat quarterly
   and once against the production topology before first production use.
8. Log redaction (`DJANGO_LOG_REDACT_HEADERS`) and Sentry (`SENTRY_DSN`) are wired
   and covered by `tests/test_phase10_env_wiring.py`. After deploy: confirm JSON
   log lines show `***` for header values, and set `SENTRY_DSN` only if error
   tracking is wanted (it then requires `requirements/prod.txt`).
9. No independent security review / penetration test.
10. Backup encryption via GPG is non-functional in the shipped image (`gpg`
    not installed).
11. No cron/scheduler ships with the repo for recurring backups — must be
    configured on the host.

**Until §F items 1–5, 7 and 10 are resolved (or formally accepted in writing
by the operator), this system must be described as an internal research
prototype — never as production software, and never as a trading system.**
