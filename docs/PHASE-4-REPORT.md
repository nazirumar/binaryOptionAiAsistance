# Phase 4 Report — Screenshot and MT5 Market Data Synchronization

**Status:** complete and verified. Implementation is DB-only and deterministic; no live MT5 terminal or real vision provider round trip was exercised.

## Summary

`apps.market_sync` compares a stored Phase 3 `ScreenshotAnalysis.result` (observations) against stored Phase 2 `MarketCandle` rows. The service runs synchronously on the web tier, never mutates the screenshot observations, and never fabricates candle data, prices or probabilities. Only `VERIFIED_ALIGNMENT` counts as a successful dual-source verification.

## Delivered components

### Services (`apps/market_sync/services/`)
| Module | Responsibility |
|---|---|
| `config.py` | SyncConfig with all SYNC_* env-driven thresholds (18 parameters) and `from_settings()` |
| `dto.py` | Immutable DTOs: InstrumentMatch, TimeframeMatch, AlignmentResult, CandleAlignmentRecord, CandleComparison, StructureComparison, PriceComparison, FreshnessAssessment, FeedAssessment, SyncIssue |
| `instrument_matcher.py` | Explicit broker-symbol resolution; case/separator-insensitive; canonical/base fallback; preferring mapping.canonical (OTC support); ambiguity → reject; profile-scoped; records mapping_verified |
| `timeframe_matcher.py` | Parses M1–D1 variants; unreadable → None; detects mismatch; never assumes default timeframe |
| `timestamp_aligner.py` | Anchor priority (user-provided → visible → capture metadata → MT5 last completed fallback); parses naive/aware with tz offset; grid floor/last_completed_open; maps completed candles by positions (excludes rightmost) |
| `candle_comparator.py` | MT5 ratios (body/upper/lower), direction, qualitative size bands; per-candle match; direction_agreement, body_agreement, wick_agreement |
| `structure_comparator.py` | Swing detection (HH/HL/LH/LL, lookback), mt5_trend derivation, structure agreement scoring; requires minimum overlap |
| `price_level_comparator.py` | Parses visible price labels; numeric-axis comparison with offset (not applied) or relative-structure fallback |
| `feed_compatibility.py` | OTC protection logic (screenshot vs reference OTC, mapping_verified gate); produces FeedAssessment |
| `freshness_validator.py` | Checks screenshot age and MT5 candle age against config; flags entry_window_expired; returns FreshnessStatus |
| `mismatch_reporter.py` | Issue codes + messages; `decide_status()` with fixed priority; includes mapping_verified in verified condition |

### Domain (models/admin/permissions/urls/views/dashboard/tasks)
- `models.py`: MarketSyncSession, CandleAlignment, FeedCompatibilityAssessment, MarketSyncIssue, SynchronizationAuditLog. Unique idempotency_key; unique (session,screenshot_index); one-to-one feed_assessment; JSON fields for evidence; status/outcome enums; `is_verified` property (outcome==VERIFIED_ALIGNMENT)
- `serializers.py`: read-only detail/summary + nested alignments/issues/audit/feed_assessment; request serializer validates analysis_id or screenshot_id; timeframe choices
- `views.py`: SyncVerifyAPIView (POST verify) — scoped idempotency key (per-user), 201 new/200 reused; SyncResultAPIView/SyncHistoryAPIView (owner-scoped, paginated, filtered); SyncHealthAPIView (reference data summary). All IsAuthenticated + ScopedRateThrottle
- `urls.py`: /api/sync/verify/, /api/sync/results/<pk>/, /api/sync/history/, /api/sync/health/
- `permissions.py`: accessible_sessions via resolve_session (owner or superuser), owner-scoped
- `dashboard.py`: context builders; disclaimer text emphasizing only verified counts as successful verification
- `tasks.py`: `run_verification_task(session_id)` thin wrapper (service already synchronous; returns pk or None on error)
- `constants.py`: SyncStatus (7), SessionStatus, ComparisonMethod, MappingSource, AlignmentSource, PriceComparisonMethod, StructureAgreement, FeedCompatibilityStatus, FreshnessStatus, Severity, AuditKind, IssueCode, SYNC_CONFIG_VERSION="1.0"
- `exceptions.py`: MissingScreenshotAnalysisError, MarketSyncConfigurationError
- `admin.py`: registration for all models
- `apps.py`: app config

### Configuration & wiring
- `config/settings/base.py`: added `apps.market_sync` to LOCAL_APPS; 18 `SYNC_*` env vars with defaults; `SYNC_VERIFY_THROTTLE="60/minute"`, `SYNC_READ_THROTTLE="240/minute"`; assignments to settings
- `config/urls.py`: mounted `api/sync/`
- `apps/dashboard/urls.py`: sync, sync-verify, sync-detail
- `apps/dashboard/views.py`: sync() overview, sync_detail(), sync_verify() POST; Phase 4 marked complete; added Sync nav link in base template
- Migrations: `apps/market_sync/migrations/0001_initial.py` created and applied

### Templates
- `templates/dashboard/sync.html`: verification picker, history table, disclaimer
- `templates/dashboard/sync_detail.html`: full session detail, alignment table, reasons/issues/audit, badges; shows "Not verified" when not verified, never claims unverified as successful

### Tests & fakes
- `tests/sync_fakes.py`: deterministic fixtures (uptrend/flat, screenshot_candles derivation with flip_direction, build_aligned_scenario with shift_minutes, OTC params, make_symbol/make_candle/make_analysis)
- `tests/test_market_sync_matchers.py` (23)
- `tests/test_market_sync_comparators.py` (26)
- `tests/test_market_sync_service.py` (22)
- `tests/test_market_sync_api.py` (22)
- `tests/test_market_sync_dashboard.py` (10)
- `tests/test_market_sync_tasks.py` (2)
- **Total Phase 4 tests: 105 passed**

## Verification results
| Check | Result |
|---|---|
| `manage.py check` | no issues |
| `manage.py makemigrations --check --dry-run` | no changes |
| `ruff check .` | all passed |
| `ruff format --check .` | all formatted |
| `pytest` (full suite) | **361 passed, 2 skipped** (the 2 PostgreSQL-only skips unchanged) |
| `scripts/check.ps1` | all checks passed |

## Status decision rules (enforced)
1. `INCOMPATIBLE_FEED` — incompatible feed (e.g. OTC vs regular) → early return (never compares)
2. `INSUFFICIENT_INFORMATION` — missing symbol/timeframe/anchor or < min_overlap_candles or insufficient detail; checked before MT5 availability
3. `MT5_UNAVAILABLE` — no stored MT5 candles for reference
4. `STALE_DATA` — screenshot or MT5 outside freshness window
5. `VERIFIED_ALIGNMENT` — direction ≥ 0.75, structure AGREE, feed COMPATIBLE **and mapping_verified**, freshness FRESH, not uncertain → only successful verification
6. `PARTIAL_ALIGNMENT` — moderate agreement or structure AGREE/PARTIAL → never fully verified
7. `DATA_MISMATCH` — sufficient overlap but disagree

## API summary
- POST `/api/sync/verify/` — verify analysis_id or screenshot_id; idempotency_key scoped per-user (f"u{user.pk}:{key}"); returns 201 new, 200 reused; throttled 60/min
- GET `/api/sync/results/{id}/` — full detail (owner-scoped); includes status_message
- GET `/api/sync/history/` — paginated owner-scoped; filters outcome/timeframe (validated); throttled 240/min
- GET `/api/sync/health/` — reference availability, config_version, server_time, outcome counts

## Security & integrity notes
- Owner-scoped on all reads; superuser override via accessible_sessions for management surfaces
- Idempotency keys never cross tenants; duplicate same key returns existing session
- Screenshot analysis never mutated; no prices/probabilities fabricated
- Only completed MT5 candles used; rightmost screenshot candle excluded; timestamps never assumed from upload time
- OTC protection is strict (verified OTC↔OTC only)
- Broker feed differences treated as expected, not errors; thresholds documented as pragmatic defaults

## Known limitations
- Live MT5 terminal and real hosted vision-model round trip remain pending (no credentials/terminal available). Implementation is fully DB-only with deterministic fixtures.
- `SYNC_*` thresholds are pragmatic, not scientifically validated. Re-run matcher/comparator tests if tuned.
- `analysis.quality` references `screenshot_quality.rating` which `make_analysis` doesn't populate → returns UNKNOWN (harmless for Phase 4).
- Celery task exists but API runs synchronously (cheap DB comparison).

## Files added/changed
Added: `apps/market_sync/*` (app, models, services, api, dashboard, tasks, templates) — 30+ files. Tests: `tests/sync_fakes.py`, 6 test files (105 tests). Changed: `config/settings/base.py`, `config/urls.py`, `apps/dashboard/views.py`, `apps/dashboard/urls.py`, `templates/base.html`, `.env.example`, `README.md`, `docs/ARCHITECTURE.md`, Phase 4 docs.

Phase 4 complete. No regressions to Phase 1–3; full suite green.
