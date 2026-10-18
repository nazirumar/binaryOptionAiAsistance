# Phase 2 Report — MT5 Live Market Data Integration

**Status: implementation complete and verified with a mocked MT5 gateway.**
**Live connection to a real MetaTrader 5 terminal/broker account is PENDING** (no
terminal or credentials were available in this environment). Per the phase rules,
this is **not** claimed as live-verified.

---

## 1. What was delivered

A new Django app, **`apps.market_data`** (label `market_data`), plus dashboard and
documentation integration. Phase 1 behaviour and styling were preserved.

### Domain / service layer (`apps/market_data/services/`)
| Module | Responsibility |
| ------ | -------------- |
| `exceptions.py` | `MarketDataError` hierarchy (`MT5UnavailableError`, `MT5ConnectionError`, `MT5DataError`, `UnsupportedTimeframeError`, `SymbolMappingError`, `OTCFeedMismatchError`, `WorkerAuthError`) |
| `dto.py` | Immutable `Candle`, `Tick`, `SymbolInfo`, `AccountInfo`, `TerminalInfo` |
| `timeframe_mapper.py` | M1…D1 ↔ MetaTrader5 constants, durations, validation |
| `symbol_mapper.py` | Canonical instrument registry (incl. OTC twins), resolve/validate, OTC compatibility |
| `mt5_client.py` | `MT5Gateway` protocol + lazy `MetaTrader5Client` (imports the package only when used) |
| `connection_manager.py` | Terminal init/auth, health checks, bounded retry + exponential backoff, graceful shutdown, `mask_account`, `resolve_secret` |
| `data_validator.py` | Missing/duplicate/non-monotonic candles, invalid OHLC, non-positive prices, missing/stale/crossed ticks, mapping issues |
| `candle_service.py` | Retrieval, **completeness detection**, completed/forming split, idempotent persistence |
| `tick_service.py` | Latest/range ticks, staleness, spread helpers, idempotent persistence, retention purge |
| `sync_service.py` | Orchestrates fetch → validate → persist → sync log → health event |
| `health.py` | Health-event and worker-heartbeat persistence helpers |
| `remote_ingest.py` | Optional token-authenticated HTTP push client for workers without DB access |

### Data model (`apps/market_data/models.py`)
`MT5ConnectionProfile`, `MarketSymbol`, `MarketCandle`, `MarketTick`,
`MarketDataSyncLog`, `MarketDataHealthEvent`, `WorkerHeartbeat` — with uniqueness
constraints, indexes and quality/source/collection fields. Passwords are **never**
stored: profiles keep a non-secret `credential_ref` only.

### API (`/api/market/`)
| Method | Path | Auth |
| ------ | ---- | ---- |
| GET | `health/` | session/token |
| GET | `symbols/` | session/token |
| GET | `candles/` | session/token (bounded range/limit) |
| GET | `tick/` | session/token |
| GET | `connection/` | session/token (masked) |
| POST | `sync/` | session/token (queues Celery work) |
| POST | `ingest/candles/` | `X-Worker-Token` |
| POST | `ingest/ticks/` | `X-Worker-Token` |
| POST | `worker/heartbeat/` | `X-Worker-Token` |

Rate limiting uses `ScopedRateThrottle` (`market_read`, `market_ingest`).

### Worker & tooling
- `manage.py mt5_worker` — Windows host worker; direct-DB and token push modes;
  heartbeat, retry, structured logs, clean SIGINT/SIGTERM shutdown, idempotent ingestion.
- `manage.py mt5_integration_check` — optional manual live check (prints `SKIPPED` when unconfigured).
- `manage.py seed_market_symbols` — seed global broker-symbol mappings.
- Celery tasks: `market_data.check_connection`, `market_data.sync_candles`,
  `market_data.sync_ticks`, `market_data.purge_ticks`.
- Dashboard page `/dashboard/mt5/` (status, broker/server, masked account, symbol,
  latest quote + spread, last completed candle, last sync, workers, recent events).

---

## 2. Verification results

Environment: Windows, Python 3.13.14, `MetaTrader5==5.0.6231`, `numpy==2.5.4` installed.

| Check | Command | Result |
| ----- | ------- | ------ |
| Django checks | `manage.py check` | ✅ no issues |
| Deploy checks | `manage.py check --deploy --settings=config.settings.prod` | ✅ no issues |
| Migrations | `manage.py makemigrations --check --dry-run` | ✅ no changes detected |
| Lint | `ruff check .` | ✅ all checks passed |
| Format | `ruff format --check .` | ✅ 99 files already formatted |
| Tests | `pytest -q --cov` | ✅ **138 passed, 2 skipped** (85% coverage) |

The 2 skips are PostgreSQL-specific constraint tests that skip on the SQLite test
database (see `tests/test_market_data_postgres_integration.py`).

Migration created and applied: `apps/market_data/migrations/0001_initial.py`.

> Note: a benign `django-environ` warning ("Engine not recognized from url") is
> emitted because the local `.env` intentionally leaves `DATABASE_URL=` empty
> (documented "leave unset for SQLite" pattern). It is pre-existing and harmless.

---

## 3. Acceptance criteria

| # | Criterion | Status |
| - | --------- | ------ |
| 1 | Terminal connects (init/auth/server id/health) | ✅ code + mocked test · ⏳ live pending |
| 2 | Worker retrieves live ticks + historical candles | ✅ code + mocked test · ⏳ live pending |
| 3 | Completed vs. forming candles distinguished | ✅ verified |
| 4 | Symbol mappings configurable + validated | ✅ verified |
| 5 | No duplicate storage (idempotent ingest) | ✅ verified |
| 6 | API authenticated + input-validated | ✅ verified |
| 7 | Stale data / disconnections reported | ✅ verified |
| 8 | OTC incompatibility handled | ✅ verified |
| 9 | Unit tests pass | ✅ 138 passed |
| 10 | Ruff passes | ✅ |
| 11 | Docs updated | ✅ |

---

## 4. Tests added (95 → 107 new cases)

`tests/marketdata_fakes.py` (fake gateway + factories) and:

- `test_market_data_timeframes.py` — supported set, durations, MT5 constant mapping.
- `test_market_data_symbols.py` — registry, OTC twins, compatibility, resolve/validate.
- `test_market_data_validator.py` — all documented invalid-data cases.
- `test_market_data_candles.py` — completeness, forming split, idempotency, no fabrication.
- `test_market_data_ticks.py` — staleness, spread, idempotency, retention purge.
- `test_market_data_connection.py` — connect, retry/backoff, exhausted retries, health, shutdown, secret masking.
- `test_market_data_mt5_client.py` — DTO/timestamp conversion via injected fake module.
- `test_market_data_models.py` — constraints and masking.
- `test_market_data_api.py` — authorization, scoping, validation, ingest auth/idempotency, OTC rejection, heartbeat.
- `test_market_data_worker.py` — direct mode, disconnection handling, missing mapping, push mode.
- `test_market_data_tasks.py` — Celery task wiring.
- `test_market_data_remote_ingest.py` — push client payloads/headers.
- `test_market_data_postgres_integration.py` — optional PostgreSQL constraint checks.

The standard suite requires **no** live credentials and **no** terminal.

---

## 5. Known limitations / follow-ups

1. **Live MT5 verification is pending.** Run on a Windows host with a terminal:
   ```powershell
   python manage.py mt5_integration_check --symbols EURUSD --timeframes M1
   python manage.py mt5_worker --symbols EURUSD --timeframes M1,M5 --once
   ```
2. The web tier intentionally cannot make live MT5 calls; collection happens via
   the worker/Celery. `GET` endpoints serve **stored** data.
3. `remote_ingest` push mode and Celery tasks are unit-tested with fakes; a real
   end-to-end network round trip is untested here.
4. Optional PostgreSQL constraint tests require a Postgres `DATABASE_URL`.

## 6. Security notes

- Passwords live only in environment/secrets-manager values; the DB stores
  non-secret identifiers and a secret *reference*.
- Worker endpoints are **disabled** (403) unless `MT5_WORKER_TOKEN` is set; token
  comparison is constant-time.
- Logins are masked; `repr(ConnectionConfig)` and manager `repr` omit passwords.
- Push mode must use HTTPS in production; the token grants ingest access only.
- No trade/order execution exists anywhere in this layer.
