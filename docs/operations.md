# Operations Guide

Day-2 operations for the Nazbeen Academy Binary AI Assistance stack
(analysis-only; no trading). Companion docs: `deployment.md`,
`incident_response.md`, `backup_restore.md`.

## 1. Service map

Run from `/opt/nazbeen-academy` (production) or the repo root (dev). Compose
file: `compose.prod.yaml` (prod) or `compose.yaml` (dev/staging).

| Service | Role | Key command |
|---|---|---|
| `web` | Django ASGI via uvicorn, port 8000 (internal in prod) | `uvicorn config.asgi:application` |
| `worker-market` | Celery, queues `market,default` (concurrency 2) | market-data ingestion & sync |
| `worker-vision` | Celery, queue `vision` (concurrency 1) | screenshot analysis (CPU/memory-heavy) |
| `worker-backtest` | Celery, queue `backtest` (concurrency 1) | long-running research jobs |
| `worker-assistant` | Celery, queue `assistant` (concurrency 2) | AI assistant tasks |
| `beat` | Celery beat | scheduled purges + health probe |
| `db` | PostgreSQL 16, loopback/internal only | volume `postgres_data` |
| `redis` | Redis 7, password-protected, internal only | broker + cache + results |
| `backup` | one-shot (`tools` profile) | `docker/backup.sh` |
| MT5 worker | **separate Windows host** | `python manage.py mt5_worker` |

## 2. Starting / stopping

```sh
cd /opt/nazbeen-academy
set -a; . ./.deploy.env; set +a          # if using the deploy env convention

docker compose -f compose.prod.yaml up -d          # start everything
docker compose -f compose.prod.yaml ps             # expect all "healthy"
docker compose -f compose.prod.yaml stop           # graceful stop
docker compose -f compose.prod.yaml restart web    # single service restart
docker compose -f compose.prod.yaml down           # full stop (keeps volumes)
```

Order matters on cold start: `db`/`redis` healthy → `migrate` →
`collectstatic` → `preflight` → `web`/workers. The compose `depends_on`
conditions encode this; `docker compose up -d` respects them.

## 3. Logs

- Containers log to stdout; production uses the `json-file` driver with
  rotation (`max-size: 10m`, `max-file: 5`) on the web service.

```sh
docker compose -f compose.prod.yaml logs --tail=200 web
docker compose -f compose.prod.yaml logs -f worker-market
```

- In production (`config.settings.prod`), every line is one JSON object:

```json
{"timestamp": "2026-10-18T09:15:04+00:00", "level": "WARNING",
 "logger": "apps.core.views", "message": "health_check.mt5_worker_stale",
 "request_id": "6f1c...", "age_seconds": 320}
```

Useful fields: `level`, `logger`, `message` (dotted event name),
`request_id`, plus structured extras (e.g. `error` exception type names).
In development the `verbose` formatter prints
`[time] LEVEL logger rid=<id> message {extras}`.

## 4. Correlation-ID tracing

1. Every request gets an `X-Request-ID` (inbound header honoured if the proxy
   sends one; otherwise a UUID4) via `apps/core.middleware.RequestIDMiddleware`.
2. The id is stored in a contextvar, attached to every log record
   (`apps.core.logging.RequestIDFilter`), and **echoed in the response
   header** `X-Request-ID`.
3. Web logs and any task logs emitted during that request carry the same
   `request_id`, so `grep <id>` across `docker compose logs` reconstructs the
   flow.

To trace: get the id from the failing response's `X-Request-ID` header (or ask
the user), then:

```sh
docker compose -f compose.prod.yaml logs web worker-vision worker-market \
  2>/dev/null | grep "<request-id>"
```

Configure Nginx to forward/regenerate `X-Request-ID` so it survives the proxy.

## 5. Health endpoints

| Endpoint | Auth | Meaning |
|---|---|---|
| `GET /healthz/` | none | Liveness: DB `SELECT 1` only. 200 `ok` / 503 `degraded`. Cheap; used by container HEALTHCHECK (every 30 s) |
| `GET /healthz/detail/` | **staff login required** (403 otherwise) | Full diagnostics; 200 unless the DB is down (then 503) |

`/healthz/detail/` checks and how to read them:

- `database` — critical. `error` ⇒ app is down; do not proceed.
- `cache` — Redis ping with a 2 s bound. `error` ⇒ broker/cache trouble
  (tasks stall, sessions may fail).
- `celery` — bounded `control.ping`; reports reachable worker count. `skipped`
  when no broker is configured (dev). `error, workers: 0` ⇒ all workers down.
- `mt5_worker` — age of the newest `WorkerHeartbeat` vs. threshold
  `max(180s, 2 × MT5_WORKER_HEARTBEAT_TTL_SECONDS)`. `error` with growing
  `heartbeat_age_seconds` ⇒ Windows worker dead/disconnected.
- `data_freshness` — age of the newest stored candle vs. 900 s. `error`
  ⇒ the feed has stopped; analyses will start failing freshness gates.

Overall: `ok` / `degraded` (non-critical check failing) / `down` (DB failing).

## 6. Celery queue monitoring

```sh
# Is a worker attached and consuming?
docker compose -f compose.prod.yaml exec redis \
  redis-cli -a "<YOUR_REDIS_PASSWORD>" llen market
docker compose -f compose.prod.yaml exec redis \
  redis-cli -a "<YOUR_REDIS_PASSWORD>" llen vision

# Worker-side view (from any container with the app):
docker compose -f compose.prod.yaml run --rm --no-deps web \
  celery -A config inspect active
```

Queue → service routing is fixed in `config/settings/base.py`
(`CELERY_TASK_ROUTES`): `chart_vision.*`→vision, `research.*`→backtest,
`market_data.*`/`market_sync.*`→market, `ai_assistant.*`→assistant,
everything else→default.

Reliability settings to remember when interpreting stuck work:
`task_acks_late=True` + `reject_on_worker_lost=True` mean a killed worker
re-delivers its task (tasks are idempotent); `prefetch_multiplier=1` bounds
memory; soft/hard time limits (240/300 s default) kill runaway jobs;
`result_expires=86400` bounds Redis growth. Scheduled jobs: daily tick purge
(`market_data.purge_ticks`), daily screenshot purge
(`chart_vision.purge_screenshots`), minutely `core.health_probe`.

## 7. Common failure modes

| Symptom | Diagnosis | Fix |
|---|---|---|
| Web 503s; `/healthz/` degraded | DB down or unreachable | `docker compose ps db`; `docker compose logs db`; see incident runbook |
| Tasks stuck `PENDING` | No worker on that queue, or Redis down | Restart the matching `worker-*`; check `redis` health |
| Tasks failing with `TimeLimitExceeded` | Job too heavy or provider hang | Check `CELERY_TASK_TIME_LIMIT`; check vision provider logs |
| Duplicate-ish results after a crash | Late-ack redelivery (by design) | Expected; tasks are idempotent by PK + status guards |
| `mt5_worker: error` in health | Windows worker offline, token mismatch, or push URL wrong | `docs/mt5_worker.md`; check `MT5_WORKER_TOKEN` equality on both sides |
| `data_freshness: error` | Feed stopped > 900 s | Restart MT5 worker; verify symbol mappings and broker server |
| Vision runs fail closed with provider errors | LLM provider down or key invalid | Runs fail rather than fabricate; check `VISION_LLM_*` env |
| `check --deploy` shows W001/W002 only | drf-spectacular naming warnings | Informational; zero `security.*` warnings is the verified baseline |
| Disk filling up | Old images/backups/logs | Backups in `./backups`; rotate/remove old stamps; check Docker log sizes |

## 8. Routine maintenance

- **Daily**: glance at `/healthz/detail/` status; confirm the deploy/backup
  logs from any overnight job.
- **Weekly**: verify a backup completed with a valid `MANIFEST.txt` and digest
  (`backup_restore.md`); review container disk usage.
- **Monthly**: `docker compose ... pull` to pick up base-image security
  updates; `pip-audit` runs in CI — triage new advisories; rotate the
  `MT5_WORKER_TOKEN` if any host handling it may have been exposed.
- **Quarterly**: run the restore drill (`backup_restore.md`) and record the
  result; review HSTS max-age and throttle limits against real traffic.

## 9. Rollback

1. Fetch the last known-good image tag from your change log.
2. Re-run the manual deploy sequence with that tag (or re-run the deploy
   workflow with it as the `image_tag` input):

```sh
cd /opt/nazbeen-academy
printf 'IMAGE_TAG=<previous-good-tag>\n' > .deploy.env
set -a; . ./.deploy.env; set +a
docker compose -f compose.prod.yaml pull web worker-market worker-vision \
    worker-backtest worker-assistant beat
docker compose -f compose.prod.yaml up -d --remove-orphans
```

3. Verify `/healthz/` is 200 and `/healthz/detail/` is `ok`/explainable.
4. If the bad release ran migrations, restoring the pre-deploy backup is the
   safe path (`backup_restore.md`). Only use `migrate` rollbacks with a fresh
   backup in hand and knowledge of which migrations were applied.
5. Post-mortem: keep the bad image tag available for inspection; do not delete
   it until the incident is written up (`incident_response.md`).
