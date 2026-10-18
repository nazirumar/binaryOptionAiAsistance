# MetaTrader 5 Integration Guide (Phase 2)

This guide covers installing and running the MT5 market-data integration. The
Django web tier never imports the Windows-only `MetaTrader5` package; a separate
**worker** running on Windows collects data and either writes to the shared
database or pushes it to the server over an authenticated API.

> The application is analysis/research software. It never places orders, and this
> integration deliberately exposes **no** order-execution capability.

---

## 1. Windows requirements

- **Windows 10/11** (the `MetaTrader5` Python package is Windows-only).
- **MetaTrader 5 terminal** installed and able to log in to your broker account.
- **Python 3.12+** (64-bit) — the interpreter bitness must match the terminal (64-bit).
- A broker account (demo is fine) whose server name is known exactly.

## 2. Python package setup

The MT5 package is **not** part of `requirements/base.txt` (it would break Linux
deploys). Install it on the worker host only:

```powershell
python -m pip install -r requirements/mt5-windows.txt
# or explicitly:
python -m pip install MetaTrader5 numpy
```

Verify:

```powershell
python -c "import MetaTrader5 as mt5; print(mt5.__version__)"
```

If the import fails, the application still runs: MT5 calls raise a clear
`MT5UnavailableError`, the worker exits with a message, and the API/reporting
layer continues to serve stored data.

## 3. Environment variables

Set these on the **worker host** (see `.env.example`). Never commit real values.

| Variable | Purpose |
| -------- | ------- |
| `MT5_PATH` | Optional full path to `terminal64.exe`. |
| `MT5_LOGIN` | Account number. |
| `MT5_PASSWORD` | Account password. |
| `MT5_SERVER` | Broker server name, e.g. `Acme-Demo`. |
| `MT5_TIMEOUT_MS` | Initialization timeout (default 60000). |
| `MT5_PORTABLE` | Use portable terminal mode. |
| `MT5_MAX_RETRIES` | Connection attempts before failing (default 3). |
| `MT5_RETRY_BACKOFF_SECONDS` / `MT5_RETRY_BACKOFF_MAX_SECONDS` | Exponential backoff bounds. |
| `MT5_FEED_DELAY_SECONDS` | Grace period before a bar is considered completed (default 5). |
| `MT5_MAX_CANDLE_RANGE` / `MT5_MAX_TICK_RANGE` | Bounded query limits. |
| `MT5_STALE_TICK_SECONDS` | Age beyond which a tick is reported stale (default 120). |
| `MT5_TICK_RETENTION_DAYS` | Tick retention window (default 7). |
| `MT5_WORKER_TOKEN` | Shared secret for the ingest API (leave unset to disable ingest). |
| `MT5_WORKER_POLL_INTERVAL_SECONDS` | Worker cycle interval (default 15). |
| `MT5_WORKER_HEARTBEAT_TTL_SECONDS` | Heartbeat staleness threshold (default 90). |
| `MT5_SYNC_SYMBOLS` / `MT5_SYNC_TIMEFRAMES` | Default collection scope. |

### Credential storage policy

- The **password is never stored in the database.** A `MT5ConnectionProfile`
  stores only non-secret identifiers (`server`, `login`, `terminal_path`) and an
  optional `credential_ref`, which is the *name of an environment variable* that
  holds the password at runtime (resolved by `resolve_secret`).
- Logins are masked everywhere they are displayed (`******21`).

## 4. Connecting a broker account

1. Log in to the terminal once manually so the broker server list is populated.
2. Set `MT5_SERVER`, `MT5_LOGIN`, `MT5_PASSWORD` in the worker environment.
3. (Optional) create an `MT5ConnectionProfile` in the Django admin for the
   account and set its `credential_ref` to the password's env-var name; pass
   `--profile <id>` to the worker.

## 5. Worker startup

### Direct mode (worker has database access)

```powershell
python manage.py mt5_worker --symbols EURUSD,XAUUSD --timeframes M1,M5
```

### Push mode (worker only reaches the server over HTTP)

```powershell
$env:MT5_WORKER_TOKEN = "<shared-secret>"
python manage.py mt5_worker `
  --push-url https://your-server.example `
  --worker-token $env:MT5_WORKER_TOKEN `
  --symbols EURUSD --timeframes M1,M5 --interval 15
```

Options: `--once` (single cycle), `--count` (candles per fetch), `--collector`
(worker id), `--profile` (connection profile id). The worker writes heartbeats,
records health events, reconnects with bounded backoff and shuts down cleanly on
Ctrl+C / SIGTERM.

### Live verification (manual)

```powershell
python manage.py mt5_integration_check --symbols EURUSD --timeframes M1
```

Prints `SKIPPED` when no terminal/credentials are configured.

## 6. Supported symbols and timeframes

- **Timeframes:** `M1, M2, M3, M5, M15, M30, H1, H4, D1`.
- **Canonical instruments:** EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF,
  NZDUSD, EURGBP, EURJPY, GBPJPY, XAUUSD, XAGUSD, BTCUSD, ETHUSD (plus OTC
  variants for forex/metals, e.g. `EURUSD_OTC`).
- Broker naming differences are handled by **configurable mappings**
  (`MarketSymbol`). Seed development mappings with:

```powershell
python manage.py seed_market_symbols --suffix m   # e.g. EURUSD -> EURUSDm
```

### OTC handling

OTC instruments (IQ Option) have **no** equivalent real-market feed. The system
refuses to treat a regular MT5 EUR/USD feed as an OTC EUR/USD feed (and vice
versa): compatibility checks return `OTC_MISMATCH`, the worker reports a health
event, and ingest requests are rejected with HTTP 400.

## 7. API examples

All read endpoints require authentication; worker ingest endpoints require the
`X-Worker-Token` header.

```bash
# Health
curl -H "Authorization: Token <token>" http://localhost:8000/api/market/health/

# Symbols
curl -H "Authorization: Token <token>" http://localhost:8000/api/market/symbols/

# Candles (bounded)
curl -H "Authorization: Token <token>" \
  "http://localhost:8000/api/market/candles/?symbol=EURUSD&timeframe=M1&limit=200&include_incomplete=false"

# Latest tick
curl -H "Authorization: Token <token>" "http://localhost:8000/api/market/tick/?symbol=EURUSD"

# Connection profiles (masked)
curl -H "Authorization: Token <token>" http://localhost:8000/api/market/connection/

# Trigger a live sync (queued)
curl -X POST -H "Authorization: Token <token>" -H "Content-Type: application/json" \
  -d '{"symbol":"EURUSD","kind":"candles","timeframe":"M5","count":300}' \
  http://localhost:8000/api/market/sync/

# Worker ingest
curl -X POST -H "X-Worker-Token: <secret>" -H "Content-Type: application/json" \
  -d '{"canonical":"EURUSD","broker_symbol":"EURUSD","timeframe":"M1",
       "candles":[{"open_time":"2026-01-05T12:00:00Z","open":"1.1","high":"1.11","low":"1.09","close":"1.105"}]}' \
  http://localhost:8000/api/market/ingest/candles/
```

## 8. Dashboard

`/dashboard/mt5/` shows connection status, broker/server, masked account, selected
symbol, latest quote, spread, last completed candle, last synchronization, worker
heartbeats and recent events. It reads stored data only and makes **no** live MT5
call on the request cycle.

## 9. Troubleshooting

| Symptom | Likely cause / fix |
| ------- | ------------------ |
| `MT5UnavailableError` | Package not installed, or non-Windows host. Install on the worker. |
| `Could not connect ... after N attempts` | Wrong `MT5_SERVER`/`MT5_LOGIN`/`MT5_PASSWORD`, terminal not running, or 32/64-bit mismatch. |
| Empty candle lists | Symbol not enabled in Market Watch (call `symbol_select`), or wrong broker symbol mapping. |
| `OTC_MISMATCH` events | Canonical OTC instrument mapped to a regular broker symbol (or vice versa). |
| Candle marked `incomplete` | Bar hasn't closed yet, or within `MT5_FEED_DELAY_SECONDS`. Increase the delay if the feed lags. |
| Stale tick warnings | No new ticks (market closed) or the worker has stopped; check heartbeats. |
| Ingest returns 403 | `MT5_WORKER_TOKEN` unset (ingest disabled) or header missing/incorrect. |
| Duplicate rows not created | Expected: ingestion is idempotent on `(symbol, timeframe, open_time)`. |

## 10. Security limitations

- Credentials live only in environment variables / a secrets manager; the
  database stores non-secret identifiers and a secret *reference*.
- Push mode must use HTTPS in production; the shared token is a bearer credential
  and grants ingest access only.
- Worker ingest endpoints are **disabled entirely** when `MT5_WORKER_TOKEN` is unset.
- No order execution exists in this layer.
- Live connectivity has **not** been verified in this environment (no terminal),
  so treat results as untested against a real broker until the manual check runs.
