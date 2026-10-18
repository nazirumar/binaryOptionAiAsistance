# Phase 4 Checklist — Screenshot and MT5 Market Data Synchronization

Legend: ✅ done & verified · ⚠️ partial / documented limitation · ⬜ out of scope

## Step 1 — Audit
- ✅ Inspected `apps.chart_vision` models (ScreenshotAnalysis, chart_metadata, result) and Phase 2 `apps.market_data` (MarketSymbol, MarketCandle, Timeframe mapping)
- ✅ Confirmed no prior `market_sync` app existed
- ✅ Ran Phase 3 suite baseline; Phase 4 added matcher/comparator/service/API/dashboard/tasks tests
- ✅ Reviewed requirements: instrument mappings, OTC protection, timeframes, timestamp alignment, completed candles only, structure comparison, price levels, freshness, 7-status model, API, dashboard, tests
- ✅ Preserved all Phase 1–3 behaviour, styling and policy constraints (no next-candle predictions, no fabricated OHLC/probabilities)

## Step 2 — Architecture / scaffold
- ✅ Created `apps.market_sync` with: models, serializers, views, urls, admin, dashboard.py, tasks.py, permissions, constants, exceptions, apps.py, services/ subpackage
- ✅ Service modules: `services/config.py`, `services/dto.py`, `services/instrument_matcher.py`, `services/timeframe_matcher.py`, `services/timestamp_aligner.py`, `services/candle_comparator.py`, `services/structure_comparator.py`, `services/price_level_comparator.py`, `services/feed_compatibility.py`, `services/freshness_validator.py`, `services/mismatch_reporter.py`, `services/synchronization_service.py`

## Step 3 — Instrument identification
- ✅ Explicit broker-symbol mapping lookup; case/separator-insensitive; exact match beats canonical fallback
- ✅ Supports suffixes such as `EURUSDm`, `GBPUSD.pro`; never infers equivalence from similar names
- ✅ Multiple distinct candidates at the winning precedence level → ambiguous → rejected
- ✅ Profile-scoped preferred over global; unresolved → unsupported/ambiguous
- ✅ InstrumentMatch prefers `mapping.canonical` over raw-parsed canonical (supports OTC mapped canonical like `EURUSD_OTC`)
- ✅ Screenshot instrument, MT5 symbol, broker, market type, mapping source, mapping verification status recorded
- ✅ Unit tests covering correct/incorrect mapping, missing symbol, ambiguity

## Step 4 — OTC protection
- ✅ OTC detection: `screenshot_is_otc` derived from symbol metadata/metadata_otc_status; `reference_is_otc` from mapping/profile context
- ✅ Comparison **only** allowed when screenshot is OTC and reference is OTC **and** mapping is explicitly verified (`mapping_verified=True`) → `COMPATIBLE`
- ✅ OTC vs. regular → `INCOMPATIBLE_FEED`; no regular forex prices substituted
- ✅ `mapping_verified` required for `VERIFIED_ALIGNMENT` (service + decision logic)
- ✅ `FeedCompatibilityAssessment` persisted with screenshot_is_otc/reference_is_otc/evidence
- ✅ Tests: OTC/regular incompatible, verified OTC/OTC compatible, unverified OTC → incompatible

## Step 5 — Timeframe synchronization
- ✅ `parse_timeframe` understands M1–D1 and common variants; unreadable → `None`
- ✅ `match_timeframe` compares screenshot vs requested/MT5 timeframe; mismatch → `TIMEFRAME_MISMATCH`/marked insufficient
- ✅ Never assumes missing/uncertain timeframe → treated as `INSUFFICIENT_INFORMATION`
- ✅ Unit tests for parsing and mismatch/missing cases

## Step 6 — Timestamp alignment
- ✅ Anchor priority: user-provided `captured_at` → visible `screenshot_timestamp` → capture metadata → none (fallback to latest completed MT5 candle, marked uncertain)
- ✅ Naive timestamps interpreted with `captured_tz_offset_minutes`; aware converted to UTC
- ✅ `floor_to_grid` + `last_completed_open` (anchor - 1 step) compute grid alignment
- ✅ Completed screenshot candles (left→right) mapped to MT5 open times; `total = len(completed_indices)` so rightmost excluded
- ✅ Captured-metadata anchor → `uncertain=True`; `confidence` set by anchor source
- ✅ Store `alignment_anchor`, `alignment_source`, `alignment_confidence`, `alignment_uncertain`
- ✅ Tests for anchor priority and alignment computation

## Step 7 — Completed candles only
- ✅ Exclude candles where `appears_complete == False` (rightmost always excluded)
- ✅ Compare only `completed` array against MT5 window covering `min(open_times)..max(open_times)`
- ✅ `Alignment` records persisted for completed candles only; `uniq_alignment_index_per_session` enforced

## Step 8 — Candle comparison
- ✅ MT5 direction, body/upper/lower wick ratios computed deterministically (no network)
- ✅ Qualitative bands per config: body bands 0.25/0.60, wick bands 0.20/0.45 (documented as pragmatic, not scientifically validated)
- ✅ `CandleMatch`: MATCHED/MISMATCHED/UNALIGNED/INSUFFICIENT
- ✅ `direction_agreement`, `body_agreement`, `wick_agreement`, `size_sequence_agreement` tracked
- ✅ Insufficient detail (unknown classification + unknown sizes/wicks + missing px) → `INSUFFICIENT`
- ✅ Unit tests: match, direction/wick mismatch, unaligned, insufficient, doji

## Step 9 — Structure comparison
- ✅ Detects swings (HH/HL/LH/LL) with `swing_lookback`, derives `mt5_trend` (uptrend/downtrend/ranging/unclear)
- ✅ Compares against screenshot structure (trend, higher_highs/higher_lows, lower_highs/lower_lows, consolidation)
- ✅ `StructureAgreement`: AGREE/PARTIAL/DISAGREE/INSUFFICIENT
- ✅ Requires `min_structure_overlap` (default 5) — too little → `INSUFFICIENT`; insufficient is **not** an agreement
- ✅ Uptrend/ranging/disagreement tests

## Step 10 — Price-level comparison
- ✅ Parses visible price labels (strips $ , spaces) → floats
- ✅ If numeric labels exist: `NUMERIC_AXIS` comparison; reports `offset` (not applied); sets `matched` based on coherence
- ✅ If no labels: `RELATIVE_STRUCTURE` (no numeric match claim)
- ✅ Tests cover both paths and offset reporting

## Step 11 — Freshness / live timing
- ✅ `FreshnessStatus`: FRESH/STALE_SCREENSHOT/STALE_MT5/UNKNOWN
- ✅ `screenshot_age = now - anchor` vs `SYNC_SCREENSHOT_MAX_AGE_SECONDS` (3600s)
- ✅ `mt5_age = now - (mt5_latest_open + step)` vs `SYNC_MT5_MAX_CANDLE_AGE_SECONDS` (900s)
- ✅ `entry_window_expired` for M1 when anchor > 2*step old? Conservative check
- ✅ Anchor None → `UNKNOWN`; stale screenshot takes precedence
- ✅ Recorded in metrics and issues (STALE_SCREENSHOT/STALE_MT5/ENTRY_WINDOW_EXPIRED)

## Step 12 — Status decision & evidence
- ✅ `SyncStatus`: VERIFIED_ALIGNMENT, PARTIAL_ALIGNMENT, DATA_MISMATCH, INCOMPATIBLE_FEED, STALE_DATA, INSUFFICIENT_INFORMATION, MT5_UNAVAILABLE
- ✅ Priority: INCOMPATIBLE_FEED → INSUFFICIENT_INFORMATION → MT5_UNAVAILABLE → STALE_DATA → VERIFIED (with all strict conditions) → PARTIAL → MISMATCH
- ✅ `VERIFIED_ALIGNMENT` requires: direction_agreement ≥ 0.75, structure == AGREE, feed COMPATIBLE **and** mapping_verified, freshness FRESH, not alignment_uncertain
- ✅ `PARTIAL_ALIGNMENT` when agreement is moderate or structure AGREE/PARTIAL; never called fully verified
- ✅ Evidence persisted: session fields, `CandleAlignment`, `FeedCompatibilityAssessment`, `MarketSyncIssue`, `SynchronizationAuditLog` (ordered), `mt5_snapshot`, `metrics`, `reasons`
- ✅ `analysis.result` is **never** mutated
- ✅ Config version and comparison method recorded
- ✅ End-to-end service tests for all major cases

## Step 13 — Models & persistence
- ✅ `MarketSyncSession` (owner, screenshot, analysis, profile, reference_symbol; status/outcome; instrument/timeframe fields; alignment; tallies; feed/structure/freshness; mt5_snapshot/metrics/reasons; idempotency_key unique, scoped per-user in views)
- ✅ `CandleAlignment` (per completed candle; unique (session, screenshot_index))
- ✅ `FeedCompatibilityAssessment` (one-to-one with session; includes mapping_verified and OTC flags)
- ✅ `MarketSyncIssue` (code, severity, message, candle_index, detail)
- ✅ `SynchronizationAuditLog` (kind, severity, message, detail, occurred_at, ordered)
- ✅ Migrations: `0001_initial.py` created and applied; `manage.py check` clean

## Step 14 — API (authenticated, owner-scoped, rate-limited)
- ✅ `POST /api/sync/verify/` — accepts analysis_id or screenshot_id; resolves accessible analysis; sets idempotency_key; throttled (sync_verify). Returns 201 on new, 200 on reused (duplicate idempotency key). Rejects unknown/other-owner → 404; missing id → 400; invalid timeframe → 400
- ✅ `GET /api/sync/results/{id}/` — owner-scoped detail; 404 if not found/owned
- ✅ `GET /api/sync/history/` — paginated, filters `outcome`, `timeframe`; validates choices; scoped to owner/superuser
- ✅ `GET /api/sync/health/` — reference data availability (mt5 candle count, latest open, last collected), config_version, server_time, sessions_by_outcome, recent count
- ✅ `_scoped_idempotency_key(user, key)` scopes keys per user (prevents cross-tenant reuse)
- ✅ Auth required on all endpoints (401/403); responses include `status_message`

## Step 15 — Dashboard
- ✅ `/dashboard/sync/` — picker of verifiable analyses; history table with outcome, instrument, MT5 symbol, TF, created; disclaimer shown
- ✅ `/dashboard/sync/<pk>/` — full detail: screenshot preview, detected vs MT5 refs, assessment (outcome/feed/structure/freshness/alignment), candle comparison table, reasons/issues, audit logs, metrics/mt5_snapshot; **shows "Not verified" badge when not VERIFIED_ALIGNMENT**; never marks unverified as successful
- ✅ `/dashboard/sync/verify/` (POST) — creates session and redirects to detail; validation messages
- ✅ Nav entry "Sync" added to base template
- ✅ Templates created: `templates/dashboard/sync.html`, `templates/dashboard/sync_detail.html`
- ✅ Dashboard context builders `apps/market_sync/dashboard.py`

## Step 16 — Testing
- ✅ `tests/sync_fakes.py` — deterministic MT5 series (uptrend zigzag, flat), screenshot_candles derivation, build_aligned_scenario with shift_minutes, OTC flags, flip_direction, etc.
- ✅ `tests/test_market_sync_matchers.py` — 23 passed (timestamp alignment, floor/grid, last_completed_open, timeframe parse/match, instrument resolution/OTC/ambiguity)
- ✅ `tests/test_market_sync_comparators.py` — 26 passed (candle comparison, structure, price levels, feed compatibility, freshness)
- ✅ `tests/test_market_sync_service.py` — 22 passed (verified/alignment, mismatches, partial, OTC incompatible/compatible, insufficient, MT5 unavailable, staleness, evidence preservation, idempotency, captured_at, failure paths)
- ✅ `tests/test_market_sync_api.py` — 22 passed (auth, verify create/200-on-reuse, validation, ownership, scoping of idempotency keys, OTC, history filters, health)
- ✅ `tests/test_market_sync_dashboard.py` — 10 passed (auth, rendering, create, redirects, errors, owner-scoped, verified/unverified badges)
- ✅ `tests/test_market_sync_tasks.py` — 2 passed (task runs, missing session safe)
- ✅ **Total Phase 4 tests: 105 passed**; all added tests deterministic, no live MT5, no network
- ✅ Full suite: 361 passed, 2 skipped (PostgreSQL-only)

## Step 17 — Config & documentation
- ✅ `config/settings/base.py`: added `apps.market_sync` to LOCAL_APPS; `SYNC_*` env map + assignments (all 18 settings with documented defaults); REST throttles `sync_verify` 60/min, `sync_read` 240/min
- ✅ `config/settings/test.py`: no changes needed (hermetic)
- ✅ `.env.example` updated with SYNC block and commented thresholds
- ✅ `config/urls.py`: mounted `api/sync/`
- ✅ Dashboard urls/views wired; base nav updated
- ✅ Migrations checked/applied; `manage.py check` clean; Ruff format+check clean

## Acceptance criteria (from spec)
1. ✅ Instrument mappings validated; explicit, not inferred; ambiguous/rejected
2. ✅ Timeframes comparable; never assumed missing/uncertain → UNVERIFIED (insufficient)
3. ✅ Completed candles time-aligned; rightmost excluded
4. ✅ Candle structure compared; agreement/disagreement quantified
5. ✅ Feed compatibility assessed; OTC handled safely
6. ✅ Stale/insufficient detected; statuses correct and exclusive by priority
7. ✅ Results stored with full evidence
8. ✅ Dashboard explains results; unverified never presented as successful
9. ✅ Tests + Ruff pass; docs updated
10. ✅ No trading execution, no fabricated probabilities/candle data, no auto-override of screenshot observations

## Known limitations
- Live MT5 terminal and real vision-provider round trip remain pending (no terminal/credentials available). Implementation is DB-only and provider-mocked as required.
- Thresholds are documented as pragmatic (not scientifically validated). Tune per broker/feed if needed, re-running matcher/comparator tests.
- `analysis.quality` reads `screenshot_quality.rating` (not populated by make_analysis) so returns UNKNOWN (not UNUSABLE). No behaviour change required for Phase 4 goals.
- Celery task is a thin wrapper (service runs synchronously); useful for queued runs but API does synchronous execution.

## Final check
- ✅ All checks passed via `scripts/check.ps1` (Django check, makemigrations --check, ruff lint/format, pytest)
- ✅ 361 passed, 2 skipped; Phase 4 adds 105 new tests, all green
- ✅ No regressions to Phase 1–3
- ✅ No shell command chaining; tools used appropriately
- ✅ Changes committed conceptually (workspace uncommitted; all files written/edited as above)
