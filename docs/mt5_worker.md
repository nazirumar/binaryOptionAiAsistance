# MT5 Market-Data Worker

The MT5 worker is the only component that talks to a MetaTrader 5 terminal.
It collects candles and ticks for analysis. **It is strictly read-only market
data: there is no order-execution code anywhere in this repository (audited).
No setting, token, or configuration makes this system place a trade.**

## 1. Why it runs separately

- The `MetaTrader5` Python package is **Windows-only** and binds to a running
  MetaTrader 5 terminal process. It cannot run inside the Linux Docker
  container; adding it to the `Dockerfile` is impossible by design.
- The terminal requires a GUI session on Windows. Isolating it on its own
  host also limits blast radius: a terminal crash cannot affect the web
  stack, and the web stack holds no MT5 credentials.

The worker is a Django management command, run from a checkout (or a copy of
the app code) on the Windows host:

```powershell
python manage.py mt5_worker --symbols EURUSD,XAUUSD --timeframes M1,M5
# options: --once (single cycle), --interval N, --count N, --collector ID,
#          --profile ID, --push-url https://host, --worker-token ...
```

## 2. Two operating modes

- **Direct mode** (no `--push-url`): the worker writes candles/ticks straight
  into the database it is configured with and upserts `WorkerHeartbeat`
  locally. Use when the Windows host can reach the same PostgreSQL.
- **Push mode** (`--push-url https://api-host`): the worker POSTs candles,
  ticks, and heartbeats to the server's ingest API using
  `RemoteIngestClient`, authenticated with the worker token (§3). This is the
  recommended production topology: only HTTPS to the public API, no database
  exposure.

## 3. Network and authentication

- Transport: **HTTPS only** in push mode (terminate TLS at the reverse
  proxy). Never send the worker token over plain HTTP.
- Auth: `X-Worker-Token` header on every ingest request, checked by
  `apps/market_data/permissions.py::IsWorkerToken` with
  `hmac.compare_digest` (constant-time).
- **Fail closed**: if `MT5_WORKER_TOKEN` is unset on the server, the ingest
  endpoints deny every request. An empty token disables ingestion; it never
  enables it.
- The token is a shared secret: generate a long random value, set it
  identically in the server `.env` and on the Windows host, and rotate it on
  any suspected exposure (restart both sides).
- Throttling: `market_ingest` rate limit (default 1200/minute) applies to the
  ingest endpoints; size limits apply to payloads.

## 4. Identity

- Worker identity = `--collector` value, defaulting to `worker-<PID>` (see
  `mt5_worker.py`). Set a stable, meaningful id in production, e.g.
  `--collector win-vps1-mt5` — it appears in heartbeats, health events, and
  `/healthz/detail/`.
- Connection profile: `MT5ConnectionProfile` stores **non-secret** identifiers
  (broker server name, login, terminal path, symbol mappings) plus a
  `credential_ref` naming where the secret lives. **The MT5 password is never
  stored in the database.** Credentials come from the worker host's
  environment (`MT5_PATH`, `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`).

## 5. Heartbeat monitoring

Every completed cycle upserts a `WorkerHeartbeat` row (status
`online`/`degraded`/`error`, plus symbols/timeframes detail). Failures also
write `HealthEvent` rows (connection, disconnect, mapping, etc.).

Server-side view: `GET /healthz/detail/` (staff only) reports
`checks.mt5_worker` with `worker_id`, `heartbeat_age_seconds`, and
`stale_threshold_seconds`.

Thresholds:

- Normal cadence: `MT5_WORKER_POLL_INTERVAL_SECONDS` (default 15 s).
- Heartbeat TTL: `MT5_WORKER_HEARTBEAT_TTL_SECONDS` (default 90 s).
- "Stale" in health diagnostics: `max(180 s, 2 × TTL)` — one missed beat
  never pages anyone; sustained staleness does.
- Market-data freshness (separate check): newest candle older than 900 s ⇒
  `data_freshness: error`; individual ticks older than
  `MT5_STALE_TICK_SECONDS` (120) are treated as stale by sync logic.

Alerting: watch for `heartbeat_age_seconds` climbing past the threshold, or
the `health_check.mt5_worker_stale` warning in the JSON logs.

## 6. Reconnection policy

- On connection loss the worker records a `disconnect` health event, sets
  heartbeat status to `error`, sleeps the poll interval, and retries via
  `MT5ConnectionManager.ensure_connected()`.
- Bounded backoff: `MT5_MAX_RETRIES` (3), doubling from
  `MT5_RETRY_BACKOFF_SECONDS` (2.0 s) capped at
  `MT5_RETRY_BACKOFF_MAX_SECONDS` (30 s); terminal timeout
  `MT5_TIMEOUT_MS` (60 s).
- `--once` mode exits after a failed cycle instead of retrying (useful for
  cron-style runs and smoke tests).
- Shutdown is graceful: SIGINT/SIGTERM sets a flag, the loop finishes within
  ~1 s, and the terminal session is disconnected.
- After reconnecting, candles are re-synced idempotently (upsert by
  symbol/timeframe/time), so an outage is backfilled automatically within
  `--count` candles per symbol.

## 7. Data-freshness validation

- Only candles past `MT5_FEED_DELAY_SECONDS` (5 s) are treated as completed;
  the forming candle is stored separately/marked.
- Ingest carries server-side timestamps; the sync layer refuses comparisons
  when the screenshot or MT5 data is older than its configured freshness
  window (`SYNC_SCREENSHOT_MAX_AGE_SECONDS`, `SYNC_MT5_MAX_CANDLE_AGE_SECONDS`)
  — it fails safe to "stale data" rather than analysing old feeds.
- Bounded queries: `MT5_MAX_CANDLE_RANGE` (5000) and `MT5_MAX_TICK_RANGE`
  (10000) cap per-request volume; ticks are purged daily after
  `MT5_TICK_RETENTION_DAYS` (7).
- **Known gap:** `TimingValidator._parse_time` (market-sync layer) strips UTC
  offsets from timestamps, producing naive datetimes. It fails safe to
  NO TRADE, but the timezone information is silently discarded; do not rely
  on cross-timezone precision until fixed.

## 8. Symbol mapping and broker-server identification

- Canonical codes (e.g. `EURUSD`) are mapped to broker-specific names via
  `SymbolMapper` + per-profile `SymbolMapping` rows, including OTC flags. The
  canonical code is stored with every candle/tick, so data from different
  brokers stays comparable.
- Unmappable symbols are skipped with a WARNING health event — the worker
  keeps running for the remaining symbols. Create the mapping before expecting
  data (a worker with zero valid mappings exits with an error).
- Timeframes must be supported (`M1`, `M5`, … via `timeframe_mapper`); the
  worker refuses unsupported timeframes at startup.
- Broker-server identification: the connection profile pins the expected
  server name and login; the startup banner prints server + **masked** account
  (`mask_account`). Verify after any terminal reconfiguration that the profile
  still matches — feeding data from the wrong broker silently corrupts
  comparisons.
- Seeding: `python manage.py seed_market_symbols` creates canonical symbols
  and default mappings; `python manage.py mt5_integration_check` performs a
  connection sanity check.

## 9. Secure logging

- Account numbers are masked (`mask_account`) in all output.
- Connection errors are logged by exception type, not by dumping payloads or
  credentials; the token is never printed.
- Log lines use the structured event convention
  (`mt5_worker.push.candles_failed`, `mt5_worker.shutdown_requested`, …), so
  they grep cleanly alongside web logs when correlation ids are available.
- Rule for operators: never log `MT5_PASSWORD`, the raw worker token, or full
  request bodies; enable the same log discipline as the server side.

## 10. Hard boundaries

1. **Read-only**: candles and ticks in, heartbeats/health events out. No
   order, position, or balance-management code exists in this repo.
2. **Credentials never reach the frontend**: MT5 settings are not exposed
   through any user-facing API; profiles expose only non-secret identifiers,
   and the web tier does not need `MT5_PASSWORD` at all.
3. **Worker token never leaves the server↔worker channel**: it is not
   rendered in any page or API response.
4. The worker only pushes to the ingest endpoints granted by
   `IsWorkerToken`; those endpoints accept market data only.

## 11. Known limitations (verified)

- No live MT5 terminal was reachable in the build environment, so the
  terminal round trip (connect → symbols → candles) is **untested here**;
  test on your Windows host before relying on the feed.
- The worker host must be kept patched; it holds MT5 credentials and the
  shared ingest token.
- Symbol mappings are per-broker and must be maintained by hand.
