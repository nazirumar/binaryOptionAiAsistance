# PHASE 11 IMPLEMENTATION CHECKLIST

Project: Nazbeen Academy Binary Ai Asisstance
Baseline: `e77bbb0` — 689 passed / 2 skipped, ruff clean, Django check clean,
makemigrations clean, env-coverage OK, secrets scan clean.

Every defect below was **verified against the current code** before any edit
(Checkpoint 0). Where a Phase 10 commit already fixed an issue (e.g.
`apps/research/tasks.py` now exists and works), that is recorded as VERIFIED-
FIXED and no redundant change is made.

## Verified defect register (Checkpoint 0)

| # | Checkpoint | Finding (file:line) | Status |
|---|---|---|---|
| D1 | 2 | `apps/strategy_engine/views.py:26-33` — `EvaluateAPIView.post` returns HTTP 501; test `tests/test_strategy_engine_conflicts.py:68-71` bakes the stub | **FIXED** — real owner-scoped evaluate via `TrustedInputBuilder`; stub-baking test updated |
| D2 | 3 | `apps/research/views.py` — every view is a stub (list `{"results": []}`, POST `202`, detail `{"id": pk}` with **no owner filter**, empty metrics/models) | **FIXED** — real, paginated, owner-scoped research APIs (IDOR closed) |
| D3 | 3 | `apps/research/tasks.py` missing → dashboard backtest 500 (Phase 10 audit) | **VERIFIED FIXED** by Phase 10; task is real and honest |
| D4 | 4 | `apps/ai_assistant/services/reasoning_provider.py:81` — configured non-mock provider always returns `_failure("provider_unavailable")`; no HTTP path exists | **FIXED** — real OpenAI/Gemini HTTP adapters; **LIVE AND PASSED** 2026-10-18 |
| D5 | 5 | `apps/strategy_engine/services/timing_validator.py:62-75` — `_parse_time` strips `+00:00`/`Z` → naive datetimes; expiry only checked for M1 | **FIXED** — `apps/core/timeutils.py` UTC parsing, generalised expiry windows |
| D6 | 5 | `apps/strategy_engine/services/evaluation_service.py:188-198` — `_parse_dt` strips `Z`, stores naive datetimes | **FIXED** — UTC-aware `_parse_dt` |
| D7 | 6 | `apps/ai_assistant/services/probability_presenter.py:28` — `not model.get("brier_score")` rejects a valid 0.0 score; no finite/0-1/sample-size/compatibility checks | **FIXED** — strict presenter with full gate set (0.0 accepted) |
| D8 | 1 | `apps/ai_assistant/views.py:96-103` — `AnalyzeView` never passes a screenshot; `AnalyzeRequestSerializer.screenshot_id` is ignored; no upload path | **FIXED** — CP1 pipeline (multipart or owned `screenshot_id`, private storage, durable job) |
| D9 | 1 | `apps/ai_assistant/services/analysis_orchestrator.py:57-77` — trusts caller-supplied `sync_status` / `timing_validity` / `market_type` (client-forgery risk once wired) | **FIXED** — server-derived `TrustedInputBuilder`; forged-field tests |
| D10 | 8 | `apps/ai_assistant/tasks.py:16` — duplicate prevention is an in-process `_IN_FLIGHT` dict (useless across workers) | **FIXED** — `AIAnalysisJob` + atomic claim CAS (migration `0002`) |
| D11 | 7 | educational mode appends a warning but still returns `direction: UP/DOWN` (`analysis_orchestrator.py:101-116`) | **FIXED** — `EDUCATIONAL` direction on all paths incl. early exits |
| D12 | 4 | `config/settings/base.py` — no `REASONING_LLM_MAX_TOKENS` / cost bounds | **FIXED** — `REASONING_LLM_MAX_TOKENS`/`REASONING_LLM_TEMPERATURE` + env coverage |
| D13 | 2 | `StrategyRulesAPIView` returns `{"rules": []}` although `StrategyRuleConfiguration` exists | **FIXED** — returns the real configuration |

## Reusable services (no second engine will be built)

| Service | Reuse in Phase 11 |
|---|---|
| `chart_vision.services.upload.create_screenshot_from_upload` | CP1 upload validation + private storage |
| `chart_vision.services.screenshot_analyzer.{get_or_create_analysis, ScreenshotAnalyzer}` | CP1 vision extraction (mock or real provider) |
| `market_sync.services.synchronization_service.SynchronizationService.verify` | CP1/CP2 **server-derived** sync_status, feed compatibility, freshness |
| `market_sync.services.instrument_matcher.resolve_instrument` | CP1/CP2 symbol mapping (OTC detection included) |
| `market_data.models.MarketCandle` + `candle_service.{is_candle_complete, split_completed_and_forming}` | CP1/CP2 reference candles, completeness |
| `strategy_engine.services.evaluation_service.EvaluationService` | CP1/CP2 evaluation (already enforces `VERIFIED_ALIGNMENT` gate in `InvalidationEngine`) |
| `price_action.services.engine.PriceActionEngine` | CP1 (via EvaluationService) |
| `research.tasks.run_backtest_task` + Phase 7 services | CP3 backtest execution, metrics honesty |
| `research.services.model_registry`, `probability_calibrator` | CP3/CP6 approved-model lookup |
| `ai_assistant.services.{conversation_manager, context_manager, evidence_retriever, explanation_generator, response_validator, safety_validator}` | CP1/CP7 |

## Implementation order (dependency-driven)

- [x] **CP5** timing: tz-aware parsing (Z/+hh:mm/−hh:mm), UTC normalisation, reject
      ambiguous naive timestamps, generalise expiry beyond M1, completed vs forming,
      delayed-analysis expiry. Tests: UTC/+01:00/−05:00/midnight/rollover/stale/
      future/incomplete/delayed.
- [x] **CP6** probability: strict validation (approved, version, target, calibration
      metadata, held-out sample size, finite 0<p<1, instrument/timeframe/target
      compatibility); fix `brier_score` truthy bug; keep the three probability types
      distinct; exact unavailable message.
- [x] **CP4** reasoning provider: real OpenAI-compatible HTTP adapter (stdlib urllib,
      connect/read timeouts, bounded retries, 429 backoff, max-token/cost caps,
      prompt+model version tracking, context redaction, safe fallback, direction
      guardrail: LLM can never flip NO TRADE). Mocked-HTTP tests + optional live
      smoke test gated on explicit API key. New `REASONING_LLM_MAX_TOKENS` setting.
- [x] **CP8** durable jobs: `AIAnalysisJob` model (unique idempotency key, atomic
      status transitions, attempts, terminal-state guard, cancellation, heartbeat)
      replacing the in-process dict; Celery task with retries/timeouts; migration.
- [x] **CP2** strategy evaluate API: real implementation — owner-scoped
      screenshot/sync lookups, server-derived trusted fields (client-supplied
      `sync_status` etc. are ignored), candle completeness + timestamp validation,
      mandatory NO TRADE via `InvalidationEngine`, persistence, consistent errors;
      `rules/` returns the real configuration. Forged-field bypass tests.
- [x] **CP1** screenshot pipeline: `AnalyzeView` accepts multipart upload (or owned
      `screenshot_id`), validates, stores privately, creates conversation + attachment
      + durable job, runs vision → instrument/timeframe extraction (uncertainty
      preserved) → symbol mapping → stored MT5 reference candles → sync verification →
      price-action + strategy evaluation → timing → calibrated probability (server
      lookup only) → explanation → persistence → structured response; dashboard access.
- [x] **CP7** educational mode: no UP/DOWN trade assessment in fields, text or
      dashboard; observations + concepts only; hypotheticals labelled; tests prove no
      actionable prediction leaks.
- [x] **CP3** research APIs: datasets (list/create with provenance + chronological
      validation), backtest list/create/status/results (owner-scoped, background,
      paginated), performance (real stored metrics with honesty flags), calibration
      report, model registry; update tests that expected stubs.
- [x] **CP9** compatibility scenarios A–J as integration tests (dual-source policy →
      NO TRADE when unverifiable; educational allowed).
- [x] **CP10** end-to-end integration tests (login→journal) + optional live suite
      gated on explicit env config (never silently mocked).
- [x] **CP11** `docs/PHASE-11-LIVE-VALIDATION.md` with status buckets
      (MOCKED AND PASSED / LIVE AND PASSED / LIVE FAILED / NOT EXECUTED).
- [x] **CP12** frontend integration: verify/fix upload → status → result → evidence →
      NO TRADE reasons → calibration → MT5 verification → conversation flow; no
      rebuild, preserve design.
- [x] **CP13** security regression tests (ownership, CSRF, throttling, private
      screenshots, file validation, key protection, prompt injection, worker auth,
      redaction, research access, cross-user journal).
- [x] **CP14** quality gates (pytest, ruff check/format, manage.py check,
      makemigrations check, secret scan, env coverage).
- [x] **CP15** `docs/PHASE-11-COMPLETION-REPORT.md` + accurate README update.

## Phase 11 close (2026-10-18)

- Full suite: **872 passed, 3 skipped** (baseline `e77bbb0`: 689 / 2 → +183 tests).
- Skips: 2 PostgreSQL-specific (SQLite test DB) + 1 gated live reasoning smoke
  (`REASONING_LLM_LIVE_TEST=1`).
- Gates: ruff check ✓ · ruff format ✓ · `manage.py check` ✓ ·
  `makemigrations --check` ✓ · secret scan ✓ · env coverage OK ✓.
- Live: reasoning provider against Google Gemini **LIVE AND PASSED**
  (2026-10-18). MT5 terminal live tests **NOT EXECUTED** (terminal unavailable).
- Report: [`PHASE-11-COMPLETION-REPORT.md`](PHASE-11-COMPLETION-REPORT.md) ·
  Live buckets: [`PHASE-11-LIVE-VALIDATION.md`](PHASE-11-LIVE-VALIDATION.md).
- **STOPPED for approval. No deployment, no new phase.**

## Non-negotiables (carried from Phase 10)

- No automatic trading; no fabricated data/probabilities/outcomes.
- Real and simulated results never mixed; only `VERIFIED_ALIGNMENT` counts as verified.
- OTC is never substituted with a regular forex feed.
- No production deployment; no credentials committed.
- Live tests are NOT EXECUTED unless real credentials are explicitly configured.
