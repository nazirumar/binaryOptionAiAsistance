# Phase 13 Checklist - Binary Options Trading Bible Strategy Implementation

**Status**: ✅ COMPLETE (75/75 tests pass)  
**Branch**: main (HEAD 0a11040 + continuation code uncommitted)  
**Date**: 2026-10-19

## Requirements

### R1 - Dataset import with provenance
- [x] `import_ohlc()` validates/sorts/dedupes OHLC; rejects rows with invalid relationships, missing timestamps, duplicates
- [x] Gaps are flagged (never fabricated); rejected rows and gaps recorded
- [x] `metadata.provenance` block includes sha256, source_file, importer, counts, reject_reasons, gap_count
- [x] `is_validated` true only when zero rejects and zero gaps
- [x] Naive timestamps assumed UTC and flagged
- [x] CSV command `import_ohlc_csv` with header aliasing and SHA-256 of file bytes

### R2 - Deterministic leak-free backtesting
- [x] `BookBacktestService.run()` persists `BacktestRun` (kind `book_strategy`) with results/metrics
- [x] `metrics` includes `approved_for_decision_use: False`, `metric_scope="next_candle_direction"`, accuracy_status
- [x] Deterministic across runs (same input → identical results/metrics)
- [x] Signals come from causal replay (`candles[0..i]` only, outcome from `i+1`); prefix property verified
- [x] `advance_research_status()` moves at most to `backtested` (never `oos_validated` or `approved`)

### R3 - Chronological OOS + walk-forward
- [x] `WalkForwardValidation.chronological_folds()` returns chronological, disjoint half-open `[start,end)` with `end <= n-1`; step default window; no shuffling
- [x] `BookWalkForwardService` partitions causal replay signals into fold windows (pooled coverage of scored signals)
- [x] Per-fold + pooled stats with sample sizes, Wilson 95% intervals, unconditional baseline per window
- [x] Explicit insufficient reasons (no signals, below threshold, series too short, no folds)
- [x] `as_dict()` includes `metric_scope`, disclaimer stating NOT binary settlement

### R4 - Detector states and confirmed ≠ trade
- [x] States: FORMING, AWAITING_CONFIRMATION, CONFIRMED_PATTERN, INVALIDATED, INSUFFICIENT_DATA
- [x] confirmed ≠ trade (recognition only; probability unavailable/uncalibrated)

### R5 - Comparison/ranking
- [x] `BookComparisonService.compare()` ranks only strategies with sufficient validation AND sufficient walk-forward
- [x] Ranking order: OOS margin desc (accuracy minus baseline), ties broken by sample size
- [x] Unranked sorted by key only (never by accuracy)
- [x] Tiers: `candidate_for_further_research`, `ranked_but_below_baseline`, `insufficient_evidence_unranked`
- [x] `approved_for_decision_use` always False for every row
- [x] `BacktestRun` kind `book_comparison` persisted

### R6 - Recognition-vs-prediction separation
- [x] `RECOGNITION_METRIC_SCOPE="pattern_recognition"`, prediction `next_candle_direction`
- [x] `assert_recognition_scope()` blocks prediction keys; `assert_prediction_scope()` blocks recognition keys
- [x] `recognition_accuracy` always `None` with `NOT_COMPUTABLE_NO_GROUND_TRUTH`
- [x] `verify_reproducibility()` runs detector twice, states recognition scope (not predictive)

### R7 - Binary settlement evaluation
- [x] `BookSettlementService.evaluate()` returns explicit states (win/loss/tie/unverifiable/refused)
- [x] Missing quotes → `UNVERIFIABLE`, no win rate
- [x] OTC + MT5 source → `refused` with `INCOMPATIBLE_FEEDS` (never coerced)
- [x] `summarize()` counts only verified settlements; unverifiable/refused reported separately with warning
- [x] Wilson interval + min-signals threshold; scope `binary_settlement`

### R8 - Immutable paper forward predictions
- [x] `PaperForwardPrediction` with `payload_digest`, `PROTECTED_FIELDS` frozen at creation
- [x] `save()` guard prevents changing protected fields; status transitions only via `resolve()` (with `_resolution_in_progress` flag)
- [x] `resolve()` requires complete outcome candle opening exactly at signal close time
- [x] Settlement fields frozen once verified (WIN/LOSS/TIE); unverifiable may be re-evaluated
- [x] `verify_integrity()` detects tampering
- [x] Service: `record()` dedupes, requires closed candle, fresh signal, recognition-enabled only
- [x] Commands: `record_paper_predictions`, `resolve_paper_predictions` with source labels (`mt5:SYM:TF` or `historical_import:<name>`)

### R9 - Decision-engine integration (gated by approval)
- [x] `StrategyFamily.BOOK_PATTERN` added; migration updated
- [x] `book_strategy_candidates()` requires `decision_use_approved AND recognition_enabled AND fresh CONFIRMED` on latest closed candle
- [x] Appended after engine candidates; exceptions degrade to empty (no propagation)
- [x] `EvaluationService.evaluate()` hook placed after PA candidates; candidates include book entries only when gated
- [x] `has_unfinished` logic preserved; `last_candle_forming` blocks book candidates
- [x] Book evidence never overrides NO TRADE safeguards (tested)

### R10 - Research dashboard + regression tests
- [x] `book_research` view, URL registered before `<str:key>/`, template rendered with honest markers
- [x] Shows recognition scope (`pattern_recognition`, `NOT_COMPUTABLE_NO_GROUND_TRUTH`), paper summary, comparison, backtests, datasets with provenance
- [x] "Research metrics →" link added to catalog list page
- [x] Admin: `PaperForwardPrediction` registered read-mostly (`has_add_permission=False`)
- [x] 75 regression tests in `tests/test_phase13_research.py` (R1–R10 + commands)

## Gates
- [x] `ruff check apps tests --fix` → clean
- [x] Django `check` passes (no system check issues)
- [x] `makemigrations --check --dry-run` → "No changes detected"
- [x] Full test suite subset: `tests/test_phase13_research.py` 75/75 pass
- [x] No Phase 14 started

## Documentation
- [x] Create `docs/PHASE-13-CHECKLIST.md`
- [x] Update `docs/BINARY-TRADING-BIBLE-STRATEGY-CATALOG.md`
- [x] Update `docs/BOOK-STRATEGY-IMPLEMENTATION-REPORT.md`
- [x] Update `docs/BOOK-STRATEGY-VALIDATION-REPORT.md`

## Notes
- No `.env` secrets committed/printed
- No MT5 substitution as expiry; OTC+MT5 refused
- Nothing fabricates historical performance
- decision_use_approved remains False in default/test data
- `docs/artifacts/` remains gitignored

**Phase 13 is complete.**
