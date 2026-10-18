# Phase 2 Checklist — MT5 Live Market Data Integration

Legend: ✅ done & verified · ⚠️ partial / documented limitation · ⬜ out of scope

## Step 1 — Audit
- ✅ Inspected existing structure (settings split, apps, models, services, API conventions)
- ✅ Confirmed Phase 1 migrations and tests pass (31 tests green before starting)
- ✅ Checked dependencies; reused `TimeStampedModel`, DRF pagination/error envelope, existing settings patterns
- ✅ Preserved Phase 1 functionality and styling

## Step 2 — Market data application
- ✅ `apps.market_data` created with `models`, `serializers`, `views`, `urls`, `admin`, `tasks`, `permissions`, `dashboard`, `services/` and `management/commands/`
- ✅ Service modules: `mt5_client`, `connection_manager`, `candle_service`, `tick_service`,
  `symbol_mapper`, `timeframe_mapper`, `data_validator`, `sync_service`, `remote_ingest`, `health`

## Step 3 — Connection management
- ✅ Terminal initialization (optional configured path, portable mode)
- ✅ Account authentication from environment / profile `credential_ref`
- ✅ Broker/server identification, terminal & account status
- ✅ Health checks
- ✅ Reconnection with bounded retry and exponential backoff
- ✅ Clear error reporting; graceful shutdown; context-manager support
- ✅ Passwords never logged (repr excludes them)
- ✅ Order placement not implemented (and not possible via this layer)

## Step 4 — Market data retrieval
- ✅ List symbols; symbol metadata
- ✅ Historical OHLC candles (`copy_rates_from_pos`, `copy_rates_range`)
- ✅ Latest completed candles vs. currently forming candle (separated)
- ✅ Latest tick; bounded tick ranges
- ✅ Broker spread and quote timestamps
- ✅ Timeframes M1, M2, M3, M5, M15, M30, H1, H4, D1
- ✅ UTC used internally throughout
- ✅ Completeness derived from timeframe duration + feed delay (never assumed)

## Step 5 — Symbol mapping
- ✅ Configurable canonical ↔ broker mappings (`MarketSymbol`), global and per-profile
- ✅ Mapping validation (`SymbolMapper.validate`, `validate_symbol_mapping`)
- ✅ Manual selection via API/Admin; validation status persisted
- ✅ Regular vs. OTC distinguished; OTC and regular feeds explicitly non-interchangeable
- ✅ Never substitutes regular MT5 data for IQ Option OTC

## Step 6 — Database models
- ✅ `MT5ConnectionProfile` (no secrets stored; `credential_ref` only)
- ✅ `MarketSymbol`
- ✅ `MarketCandle` (unique `symbol+timeframe+open_time`)
- ✅ `MarketTick` (bounded retention; unique `symbol+time+source`)
- ✅ `MarketDataSyncLog`
- ✅ `MarketDataHealthEvent`
- ✅ `WorkerHeartbeat` (liveness)
- ✅ Indexes + uniqueness constraints; source/quality fields; collection timestamps

## Step 7 — Data validation
- ✅ Missing candles · ✅ duplicate timestamps · ✅ non-monotonic ordering
- ✅ Invalid OHLC · ✅ non-positive prices · ✅ negative spread
- ✅ Missing ticks · ✅ stale quotes · ✅ incorrect mappings · ✅ unsupported timeframes
- ✅ Broker disconnection reported · ✅ incomplete current candles
- ✅ Original values preserved; gaps never fabricated/interpolated

## Step 8 — Secure API
- ✅ `GET /api/market/health/`
- ✅ `GET /api/market/symbols/`
- ✅ `GET /api/market/candles/` (bounded range + limit)
- ✅ `GET /api/market/tick/`
- ✅ `GET /api/market/connection/`
- ✅ `POST /api/market/sync/` (async trigger)
- ✅ Worker ingest: `POST /api/market/ingest/candles/`, `ingest/ticks/`, `worker/heartbeat/`
- ✅ Authentication + per-user scoping; credentials never exposed
- ✅ Rate limiting via `ScopedRateThrottle`

## Step 9 — Windows worker
- ✅ `manage.py mt5_worker` (Windows host), direct-DB and token-authenticated push modes
- ✅ Worker authentication (shared token, constant-time compare)
- ✅ Configurable collection intervals
- ✅ Heartbeat monitoring
- ✅ Retry handling and structured logs
- ✅ Clean shutdown (Ctrl+C / SIGTERM)
- ✅ Idempotent candle ingestion
- ✅ Run instructions documented (`docs/MT5-INTEGRATION.md`)

## Step 10 — Connection dashboard
- ✅ `/dashboard/mt5/` with connection status, broker/server, masked account, symbol,
  latest quote, spread, last completed candle, last sync, workers, recent events
- ✅ Uses existing Tailwind/HTMX stack; unrelated pages unchanged

## Step 11 — Testing
- ✅ Connection failure, mocked success, retry/backoff, graceful shutdown
- ✅ Symbol mapping and OTC mismatch protection
- ✅ OHLC retrieval, timestamp conversion, incomplete candle detection
- ✅ Stale data, duplicate ingestion, invalid market data
- ✅ API authorization, worker-token auth, ingest idempotency
- ✅ Worker disconnection handling
- ✅ MT5 fully mocked in the standard suite (no live credentials required)
- ✅ Optional live check command `manage.py mt5_integration_check`
- ⚠️ No real MT5 terminal was available — **live integration is PENDING**

## Step 12 — Documentation
- ✅ `docs/MT5-INTEGRATION.md` (install, env, worker, symbols, API, troubleshooting, security)
- ✅ `docs/PHASE-2-REPORT.md`
- ✅ README, ARCHITECTURE and `.env.example` updated
- ✅ PostgreSQL integration test for the market-data models (skips without Postgres)

## Phase 2 acceptance criteria
1. ✅ Connects to a *configured* MT5 terminal (verified with mocked gateway; live pending)
2. ✅ Worker retrieves live ticks and historical candles (code path tested with mocks)
3. ✅ Completed and forming candles clearly distinguished
4. ✅ Symbol mappings configurable and validated
5. ✅ Data stored without duplicates
6. ✅ API endpoints authenticated and validated
7. ✅ Stale data and disconnections reported
8. ✅ OTC incompatibility explicitly handled
9. ✅ Unit tests pass
10. ✅ Ruff checks pass
11. ✅ Documentation updated
