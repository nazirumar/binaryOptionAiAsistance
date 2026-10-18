# Deployment Guide

Operational deployment documentation for the Nazbeen Academy Binary AI
Assistance stack. This application is a **market ANALYSIS research tool**. It
never places trades and contains no order-execution code.

> Status: the container/Compose infrastructure below exists and is CI-verified,
> but **no production deployment has been performed from this repository as of
> this writing**. Treat this as the intended, tested-in-CI procedure — not a
> claim of a running production system.

## 1. Architecture

| Layer | Technology | Notes |
|---|---|---|
| TLS / reverse proxy | Nginx + Certbot (on the Linux VPS host) | Terminates HTTPS, sets `X-Forwarded-Proto` |
| App server | `uvicorn config.asgi:application` (ASGI) | Runs in the container; `daphne` is **not** used or required |
| Framework | Django + Django REST Framework | `config.settings.prod` refuses insecure config |
| Database | PostgreSQL 16 (`postgres:16-alpine`) | Internal Docker network only — never published |
| Cache / broker | Redis 7 with `requirepass` (`redis:7-alpine`) | Internal Docker network only — never published |
| Task workers | Celery, one container per queue | `market`+`default`, `vision`, `backtest`, `assistant` |
| Scheduler | Celery beat | Retention purges + minutely health probe |
| Static files | WhiteNoise (manifest storage) | `collectstatic` runs at container start |
| Private media | `private_media/screenshots` volume/dir | Never served from a public URL |
| Market-data feed | **Separate Windows host** running `manage.py mt5_worker` | MetaTrader 5 is Windows-only; see §8 and `docs/mt5_worker.md` |

One image (`nazbeen-academy:latest`) serves every Linux role; the per-service
`command:` in the compose files selects web vs. worker vs. migrate.

## 2. Prerequisites (Linux VPS)

1. Ubuntu 22.04+ (or equivalent) with Docker Engine and the Compose plugin.
2. A DNS name pointing at the VPS.
3. Outbound HTTPS from the VPS (image pulls, apt, Certbot).
4. A Windows host with MetaTrader 5 terminal + the `MetaTrader5` Python
   package for the market-data worker (optional; the app degrades to
   "no fresh data" without it).

**MT5 cannot run inside the Linux container.** The `MetaTrader5` package binds
to a running Windows terminal. Never attempt to add it to the Dockerfile; the
worker runs on its own Windows machine and pushes to the API over HTTPS.

## 3. First deployment (step by step)

All commands run on the VPS as a non-root user in `/opt/nazbeen-academy`
(this is the directory `.github/workflows/deploy.yml` uses).

```sh
# 1. Clone
git clone <YOUR_REPO_URL> /opt/nazbeen-academy
cd /opt/nazbeen-academy

# 2. Environment file (compose reads .env from this directory)
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(50))"  # -> DJANGO_SECRET_KEY
# Edit .env: set at minimum
#   DJANGO_SETTINGS_MODULE=config.settings.prod
#   DJANGO_SECRET_KEY=<YOUR_SECRET_KEY>
#   DJANGO_ALLOWED_HOSTS=<your-domain.example>
#   DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-domain.example>
#   DATABASE_URL=postgres://<user>:<password>@db:5432/<dbname>
#   REDIS_URL=redis://:<password>@redis:6379/0
#   POSTGRES_PASSWORD=<YOUR_DB_PASSWORD>
#   REDIS_PASSWORD=<YOUR_REDIS_PASSWORD>
#   MT5_WORKER_TOKEN=<YOUR_WORKER_TOKEN>
#
# IMPORTANT: if any value contains a `$` (e.g. a Django secret key), wrap the
# whole value in SINGLE quotes:  DJANGO_SECRET_KEY='abc$def'
# Reason: the app's django-environ keeps values literal, but `docker compose`
# interpolates unquoted/double-quoted `$name` in .env to an empty string — the
# container would otherwise run with a different secret than intended.
# `python scripts/check_env_coverage.py` fails if it finds such a value.
chmod 600 .env

# 3. Build
docker compose -f compose.prod.yaml build

# 4. One-shot services, in order
docker compose -f compose.prod.yaml run --rm migrate
docker compose -f compose.prod.yaml run --rm collectstatic
docker compose -f compose.prod.yaml run --rm preflight   # manage.py check --deploy

# 5. Start the stack
docker compose -f compose.prod.yaml up -d

# 6. Verify
curl -fsS http://127.0.0.1:8000/healthz/   # requires proxy loopback; see §4
docker compose -f compose.prod.yaml ps
```

For local development use `compose.yaml` instead (dev settings, loopback port
`127.0.0.1:8000`):

```sh
cp .env.example .env   # dev defaults are fine
docker compose up --build
```

## 4. Nginx reverse proxy + TLS

`compose.prod.yaml` publishes **no host ports**. Traffic reaches the app only
through Nginx. Because the web service publishes nothing to the host, run Nginx
as a container attached to the same Docker network (`nazbeen-academy-prod`
joins `internal`; the compose file notes the proxy joins this network), and
proxy to `http://web:8000`. Certbot runs on the VPS host.

```nginx
# /etc/nginx/sites-available/nazbeen-academy  (host-level config)
server {
    listen 80;
    server_name <your-domain.example>;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name <your-domain.example>;

    ssl_certificate     /etc/letsencrypt/live/<your-domain.example>/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/<your-domain.example>/privkey.pem;

    # Request-size ceiling (matches the app's 10 MiB default + headroom).
    client_max_body_size 12m;

    location /static/ {
        # Optional: serve collected statics straight from disk via WhiteNoise
        # headers, or proxy everything — WhiteNoise handles caching either way.
        proxy_pass http://web:8000;
        proxy_set_header Host $host;
    }

    location / {
        proxy_pass http://web:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        # Required: config/settings/prod.py trusts X-Forwarded-Proto for the
        # SSL redirect / secure-cookie decision.
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

```sh
sudo certbot --nginx -d <your-domain.example>
# Confirm auto-renewal:
sudo certbot renew --dry-run
```

Uvicorn is started with `--proxy-headers --forwarded-allow-ips *` (image CMD),
so it also honours `X-Forwarded-*` from the proxy.

## 5. Zero-downtime deploy

Production deploys go through `.github/workflows/deploy.yml`
(`workflow_dispatch` only). One-time setup: configure the GitHub Environment
`production` with **Required reviewers** — that is the human approval gate the
workflow relies on. Repository secrets required: `IMAGE_TAG`, `DEPLOY_HOST`,
`DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`.

The workflow, in order:
1. Verifies the secrets are present.
2. Runs a **pre-deploy backup** (`docker compose run --rm backup`) unless
   `skip_backup` is set.
3. Pulls the new image on the server, runs `preflight` (`check --deploy`),
   then `up -d --remove-orphans` (rolling restart per service).
4. Polls `docker compose ps web` for `healthy` (up to ~150 s) and fails the
   job, dumping the last 100 log lines, if the health check does not pass.

Runtime secrets are **never transferred by the workflow**; they live on the
server. The workflow header specifies `/etc/nazbeen-academy/.env`, while
compose reads `.env` from its own directory (`/opt/nazbeen-academy`) — point
one at the other (symlink or copy) and keep both root-only (`chmod 600`).

Manual equivalent, on the server:

```sh
cd /opt/nazbeen-academy
printf 'IMAGE_TAG=<tag>\n' > .deploy.env
set -a; . ./.deploy.env; set +a
docker compose -f compose.prod.yaml run --rm backup
docker compose -f compose.prod.yaml pull web worker-market worker-vision \
    worker-backtest worker-assistant beat
docker compose -f compose.prod.yaml run --rm preflight
docker compose -f compose.prod.yaml up -d --remove-orphans
docker compose -f compose.prod.yaml ps   # all healthy
```

## 6. Rollback

1. Identify the previous good `IMAGE_TAG` (record every tag deployed in your
   change log).
2. Re-run the deploy workflow with that tag (this is the documented rollback
   path in `deploy.yml`), or run the manual sequence in §5 with the old tag.
3. Verify `/healthz/` returns 200 and `/healthz/detail/` (staff session) shows
   `status: ok` or an explainable `degraded`.
4. If the bad deploy included a migration, restoring the pre-deploy backup may
   be required — see `docs/backup_restore.md`. Do **not** blindly run
   `migrate` backwards in production without a backup in hand.

## 7. Static and media handling

- Statics: `manage.py collectstatic --noinput` runs via the compose
  `collectstatic` service (or `RUN_COLLECTSTATIC=1` at start); WhiteNoise
  serves them from `/app/staticfiles` with hashed filenames and a 30-day max-age
  in production.
- Public media (`MEDIA_ROOT`) is only served when `DEBUG=True`; production
  serves none of it.
- **Private screenshots** live under `VISION_SCREENSHOT_ROOT`
  (default `<BASE_DIR>/private_media/screenshots`) and are streamed only
  through an authenticated, ownership-checked endpoint. They are included in
  backups (`docs/backup_restore.md`) and purged by the daily
  `chart_vision.purge_screenshots` beat task after
  `VISION_SCREENSHOT_RETENTION_DAYS` (default 30).

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `web` container restarts immediately; log: `ImproperlyConfigured` | Missing `DJANGO_SECRET_KEY` / `DJANGO_ALLOWED_HOSTS` / `DATABASE_URL` / `REDIS_URL` | `prod.py` refuses to boot insecurely — set all four in `.env` |
| Users get 301 redirect loops | TLS terminates upstream but `X-Forwarded-Proto` is not set, or `DJANGO_SECURE_SSL_REDIRECT` misconfigured | Add `proxy_set_header X-Forwarded-Proto $scheme;` (§4) |
| `preflight` fails; only drf-spectacular `W001`/`W002` warnings are shown otherwise | Warnings are expected; an actual `security.*` error means real misconfiguration | Only fail on `ERROR`s; zero `security.*` warnings is the verified prod baseline |
| Celery tasks stay `PENDING` | Workers down, wrong `REDIS_URL`, or worker not consuming the right queue | `docker compose ps`, `docker compose logs worker-*`, `docker compose exec redis redis-cli -a <pass> ping` |
| Static 404s after a deploy | `collectstatic` not run for the new image | `docker compose -f compose.prod.yaml run --rm collectstatic` |
| `/healthz/detail/` shows `mt5_worker: error` with growing `heartbeat_age_seconds` | Windows worker down or cannot reach the API | See `docs/mt5_worker.md` and `docs/incident_response.md` |
| `502` from Nginx | App container not running / wrong network attach | `docker compose ps`; confirm Nginx is on the `internal` network |
| Postgres auth failures | `.env` password changed after the volume was initialised | Reset the DB password to match `.env`, or recreate the volume and restore from backup |
