# Incident Response

For the Nazbeen Academy Binary AI Assistance stack — an **analysis-only
research tool** (no trading, no funds at risk). Incidents therefore concern
data integrity, availability, and confidentiality — not money movement.

## 1. Severity classification

| Sev | Definition | Examples | Response |
|---|---|---|---|
| **S1** | All users blocked, or data confidentiality possibly breached | DB down; `/healthz/` 503 fleet-wide; suspected data leak; exposed secret | Page immediately; mitigate first, explain later |
| **S2** | Major feature degraded with no safe workaround | All Celery workers down; MT5 feed stopped > 15 min; bad deploy shipping wrong results | Same-day, continuous work until resolved |
| **S3** | Partial degradation or single-user impact | One queue backed up; one user's export failing; stale freshness warning | Next business day |
| **S4** | Cosmetic / informational | Log noise; drf-spectacular W001/W002 warnings; doc drift | Backlog |

Because outputs are advisory analysis (fail-safe to NO TRADE / no fabricated
results), **wrong-but-confident output is treated one severity higher** than
the same outage's availability rating.

## 2. On-call first steps (any incident)

1. Acknowledge: note start time (UTC) and the triggering signal.
2. Triage severity (§1) using `/healthz/` and `/healthz/detail/` (staff
   session) — do not skip this; it usually names the failing dependency.
3. Capture evidence before changing anything: recent logs, `docker compose
   ps`, the failing `X-Request-ID` (echoed on every response).
4. Open the matching runbook (§8) and follow it; record every action with
   timestamps.
5. Escalate per severity; declare recovery only after the verification step
   of the runbook passes.

## 3. Detection

- **Health endpoints**: `GET /healthz/` (public, DB-only liveness — used by
  the container HEALTHCHECK) and `GET /healthz/detail/` (staff-only: database,
  cache, Celery worker count, MT5 heartbeat age, market-data freshness).
  Monitor externally (uptime pinger on `/healthz/`) — you cannot alert on
  what you never ask.
- **Log signals** (JSON lines in production; grep by `message`):
  `health_check.database_failed`, `health_check.cache_failed`,
  `health_check.celery_timeout`, `health_check.mt5_worker_stale`,
  `mt5_worker.push.candles_failed`, `mt5_worker.heartbeat_failed`,
  `mt5_worker.disconnect`, plus any `level: ERROR` spike.
- **Deploy workflow**: post-deploy health verification fails the job and dumps
  the last 100 web log lines.
- **Users**: a supplied `X-Request-ID` from a failing response is the fastest
  trace key across web + worker logs.

## 4. Response phases

**Containment** — stop the bleed without destroying evidence:
- Outage: restart only the affected service (`docker compose ... restart <svc>`).
- Suspected compromise: `stop` (not `down`) the affected services to preserve
  containers, and isolate network access; do not delete volumes or logs.
- Bad deploy: roll back (§8.6) rather than hot-patching in place.

**Eradication** — remove the cause:
- Apply the fix (config correction, image rollback, credential rotation,
  dependency patch). Re-run `preflight` (`manage.py check --deploy`) before
  restarting a reconfigured stack.

**Recovery** — restore service and verify:
- Restart services, watch `/healthz/` → 200 and `/healthz/detail/` → `ok` or
  explainable `degraded`.
- Confirm data integrity: newest candle age, one user flow end-to-end, no
  ERROR logs for N minutes.
- Only then declare the incident resolved and start the clock on follow-ups.

## 5. Communication template

```
[INCIDENT] <Sev> — <one-line summary>
Started (UTC):   <time>        Detected via: <healthz|log|user|deploy job>
Impact:          <who/what is affected; what still works>
Status:          INVESTIGATING | CONTAINED | MONITORING | RESOLVED
Actions so far:
  - <hh:mm> <action taken + result>
Next update:     <time or "on status change">
Notes:           <analysis-only system; no trades/funds involved>
```

## 6. Post-mortem template

```
# Post-mortem: <title> (<date>)
Severity: <S1–S4>     Duration: <start→end>     Author: <name>
## Summary            3–5 sentences, user-visible impact first.
## Timeline           UTC timestamps: detection, actions, recovery.
## Root cause         The proximate AND contributing causes.
## What went well     e.g. fail-safe NO TRADE held; token failed closed.
## What went wrong    e.g. no alert on queue depth; untested restore path.
## Action items       Owner + due date each; "none" is not an answer.
## Related gaps       Link known gaps in docs/security.md §13 if implicated.
```

Rule: blameless — the goal is to fix the system, not the person.

## 7. Known gaps that shape response

Carried from `docs/security.md` §13; incidents around these are expected:
strategy-evaluate returns 501; research API is stubs; reasoning provider has
no real HTTP path (fallback only); timestamp parsing drops timezone offsets;
no live MT5/LLM round trip tested; Sentry is wired but a DSN must be supplied
at deploy time (log-scraping remains the fallback); PostgreSQL restore drill
passed on live PostgreSQL 16 (2026-10-18), production-topology run pending.

## 8. Runbooks

### 8.1 Database outage (S1)
1. Confirm: `/healthz/` 503; `docker compose ps db` unhealthy; web logs show
   `health_check.database_failed`.
2. `docker compose -f compose.prod.yaml logs --tail=100 db` — look for
   auth failures, disk full, OOM.
3. Fix in order of likelihood: restart db; free disk (`docker system df`,
   old backups); correct `DATABASE_URL`/`POSTGRES_PASSWORD` mismatch after an
   `.env` change (password must match the initialised volume).
4. Workers will retry (bounded retries, late acks); after DB recovery verify
   task states drain.
5. If corruption is suspected: stop writers, take a fresh backup, follow
   `backup_restore.md` §5 — restoring an *older* dump loses data, so prefer
   repair when possible.
6. Verify: `/healthz/` 200; one user flow; no new DB errors for 10 min.

### 8.2 Redis / Celery outage (S2)
1. Confirm: `checks.cache` or `checks.celery` = error; tasks stuck PENDING.
2. `docker compose logs --tail=100 redis` and the `worker-*` services.
3. Restart order: redis → workers → beat. Redis keeps `appendonly yes`, so
   broker state survives restarts.
4. Suspected password mismatch after `.env` edit: `REDIS_URL` and the
   `redis-server --requirepass` value in compose must match.
5. Disk/memory pressure: Redis is capped (256–512 MB, LRU); results expire in
   24 h — no manual flush needed.
6. Verify: `redis-cli ping` → PONG; health detail shows workers > 0; a test
   task flows (e.g. re-trigger a screenshot analysis).

### 8.3 MT5 worker down (S2)
1. Confirm: `checks.mt5_worker` = error, `heartbeat_age_seconds` rising;
   `data_freshness` degrades after ~15 min.
2. On the Windows host: is the terminal running and logged in? Is
   `manage.py mt5_worker` running? Check its log for
   `mt5_worker.disconnect` / mapping warnings.
3. If push mode: verify HTTPS reachability to the API and that
   `MT5_WORKER_TOKEN` matches the server exactly (mismatch = silent 403s).
4. Restart the worker command; watch a fresh heartbeat appear and the health
   check return to `ok`. Backfill of missed candles happens automatically.
5. If mappings broke (broker renamed symbols): fix `SymbolMapping` rows; the
   worker logs a WARNING and health event per unmapped symbol.

### 8.4 AI provider failure (S3, S2 if prolonged)
1. Confirm: vision runs failing with provider transport errors in logs;
   assistant answers missing explanations.
2. Behaviour is **fail-safe by design**: vision runs fail rather than
   fabricate; reasoning falls back to the safe non-fabricating response. No
   incorrect output is produced — the impact is missing analysis, not wrong
   analysis.
3. Check provider status, `VISION_LLM_*` / `REASONING_LLM_*` env, quota, and
   the bounded retries/rate-limit backoff in the logs.
4. Note: the reasoning provider currently has **no real HTTP path** (known
   gap) — a non-mock provider always returns the fallback; do not chase a
   "reasoning outage" that is actually the stub.

### 8.5 Suspected data leak (S1)
1. Contain first: stop the exposed service (`docker compose ... stop <svc>`),
   revoke the implicated credential (worker token, user session secret,
   `DJANGO_SECRET_KEY` if exposed), and rotate.
2. Preserve evidence: keep containers/volumes/logs intact; export relevant
   logs (JSON lines) before anything else.
3. Scope it: which data (screenshots, analyses, credentials), which tenant,
   how accessed (grep the relevant `X-Request-ID`s and token auth failures).
4. If the worker token leaked: rotate on server + Windows host, restart both
   sides, review `market_ingest` request patterns.
5. If `DJANGO_SECRET_KEY` leaked: rotate (invalidates sessions — expected),
   and review anything signed with it.
6. Communication: this template plus legal/privacy obligations as applicable;
   the post-mortem is mandatory for every S1.

### 8.6 Bad deployment (S2, S1 if data-mutating)
1. The deploy job's health check failed, or users report wrong behaviour
   shortly after a deploy.
2. Roll back immediately — re-run the deploy workflow (or the manual sequence
   in `docs/operations.md` §9) with the previous good `IMAGE_TAG`. Do not
   debug in production while users are affected.
3. If the release ran migrations: do **not** blindly `migrate` backwards.
   Stop writers, take a fresh backup, and assess with the migration list in
   hand; restore from the pre-deploy backup only when rollback is unsafe.
4. Verify after rollback: `/healthz/` 200, `/healthz/detail/` ok/degraded,
   one full user flow.
5. Keep the bad image tag for inspection; attach findings to the post-mortem
   and add a regression test before re-deploying.
