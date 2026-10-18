# PHASE 6 — IMPLEMENTATION CHECKLIST: Strategy Evaluation and Next-Candle Decision Engine

**Project:** Nazbeen Academy Binary Ai Asisstance
**Phase:** 6 (Strategy Evaluation and Next-Candle Decision Engine)
**Status:** In Progress
**Owner:** Developer

## OBJECTIVE
Implement a professional strategy evaluation engine that combines screenshot observations, verified MT5 market data, and the complete Nazbeen Academy price-action knowledge engine. The engine evaluates next-candle directional hypotheses and returns one of: UP, DOWN, NO_TRADE. Every decision must include supporting evidence, conflicting evidence, invalidation conditions, data-quality information, and an explanation. No fabricated numerical probabilities.

---

## STEP 1 — AUDIT THE EXISTING APPLICATION ✅
- [x] Inspect Django repository structure and conventions
- [x] Verify Phases 1–5 are complete (468 tests pass, 2 skipped)
- [x] Run existing automated tests (baseline confirmed)
- [x] Check database migrations (no pending migrations)
- [x] Inspect screenshot vision, MT5, sync, and price-action interfaces
- [x] Identify reusable services and models
- [x] Preserve existing functionality (no regressions)

---

## STEP 2 — CREATE THE STRATEGY EVALUATION MODULE
- [ ] Create `apps/strategy_engine/` Django app
- [ ] Create app structure:
  - [ ] `models.py`
  - [ ] `serializers.py`
  - [ ] `views.py`
  - [ ] `urls.py`
  - [ ] `admin.py`
  - [ ] `apps.py`
  - [ ] `constants.py`
  - [ ] `exceptions.py`
  - [ ] `schemas/` directory
  - [ ] `services/` directory
  - [ ] `rules/` directory
  - [ ] `tests/` directory (or use top-level `tests/`)
- [ ] Register app in `INSTALLED_APPS` (`config/settings/base.py`)
- [ ] Follow existing repository conventions

---

## STEP 3 — STANDARDIZED EVALUATION INPUT
- [ ] Define versioned input schema in `apps/strategy_engine/schemas/`
  - [ ] Input DTOs for evaluation request (StrategyInput)
  - [ ] Fields: screenshot_analysis_id, screenshot metadata, instrument/timeframe, OTC status, MT5 data snapshot, sync status, data freshness, completed candles, price-action evidence registry, detected patterns, market structure, S/R zones, market cycle, liquidity, volume, session context
  - [ ] Validation logic to reject invalid/incomplete input
  - [ ] Never manufacture missing observations
- [ ] Constants for schema versions and config versions

---

## STEP 4 — MARKET CONTEXT EVALUATION
- [ ] Create `services/context_evaluator.py`
- [ ] Classify market context: bullish trend, bearish trend, range, transition, uncertain
- [ ] Consider HH/HL, LH/LL, structure breaks, buyer/seller failures, consolidation, cycle, volatility
- [ ] Keep context classification separate from final direction

---

## STEP 5 — CORE STRATEGY FAMILIES
- [ ] `services/setup_classifier.py` — identify candidate setups across strategies
- [ ] Strategy A — Support/Resistance Rejection (`services/bullish_evaluator.py`, `services/bearish_evaluator.py` or split)
  - [ ] Bullish: established support zone, seller failure to break support, confirmed bullish recovery, compatible structure, no stronger contradictory evidence
  - [ ] Bearish: established resistance, buyer failure to break resistance, confirmed bearish recovery, compatible structure
  - [ ] Optional 2-failure confirmation (configurable)
- [ ] Strategy B — SBR/RBS Breakout-Retest
  - [ ] Bullish RBS (resistance becomes support)
  - [ ] Bearish SBR (support becomes resistance)
  - [ ] Track source-failure confluence separately
  - [ ] Do not assume every breakout retests
- [ ] Strategy C — Liquidity Sweep and Rejection
  - [ ] Bullish sweep low + recovery
  - [ ] Bearish sweep high + rejection
  - [ ] No institutional intent inference

---

## STEP 6 — COURSE KNOWLEDGE INTEGRATION
- [ ] Incorporate Phase 5 evidence: buyer/seller source failure, reference/similar sequences, lonely candles, psych sequences, market cycles, candle strength, wick rejection, engulfing/reversal patterns, OBs, FVGs, opening gaps, volume effort/result, session context, regime filters
- [ ] Evidence available as confirmations/contradictions/research hypotheses
- [ ] Do not require every concept present
- [ ] Avoid double-counting correlated evidence

---

## STEP 7 — EVIDENCE DEPENDENCY AND CONFLUENCE
- [ ] `services/confluence_engine.py`
- [ ] Build evidence-dependency registry (identify independent vs correlated groups)
- [ ] Configurable experimental confluence scores (must NOT be displayed as probabilities)
- [ ] Handle correlations: engulfing + body strength, sweep + wick rejection, SBR/RBS + breakout-retest, cycle reversal + BSF overlap

---

## STEP 8 — BULLISH AND BEARISH EVALUATION
- [ ] Evaluate bullish and bearish hypotheses independently
- [ ] For each candidate record: strategy family, direction, supporting, contradictory, required, missing, invalidation, candle refs, price levels, signal/analysis timestamps, rule versions
- [ ] Do not accept based solely on count of bullish vs bearish

---

## STEP 9 — MANDATORY NO TRADE CONDITIONS
- [ ] `services/invalidation_engine.py`
- [ ] NO_TRADE when: screenshot/MT5 compatibility not verified per dual-source policy, instrument/timeframe uncertain, required signal candle unfinished, stale data, next-candle entry window passed, ambiguous structure, missing required strategy conditions, strong contradictory evidence, setup invalidated, required news filter cannot be evaluated (fail-closed), insufficient data quality
- [ ] Explicit reason codes
- [ ] Never guess missing info

---

## STEP 10 — TIMING AND NEXT-CANDLE VALIDATION
- [ ] `services/timing_validator.py`
- [ ] Track: signal candle open/close, target candle open/close, screenshot capture/upload times, MT5 snapshot time, analysis completion time, prediction validity
- [ ] Timezone-aware UTC timestamps
- [ ] For M1, reject if target candle started beyond configured entry tolerance
- [ ] Mark expired analyses as EXPIRED/NO_TRADE; never silently shift target

---

## STEP 11 — DECISION OUTPUT
- [ ] `services/decision_engine.py` + output schemas
- [ ] Define strict output: evaluation_id, instrument, timeframe, market type, target candle interval, direction (UP/DOWN/NO_TRADE), strategy family, market context, supporting/contradictory evidence, invalidation, sync status, timing validity, confluence score (if configured), statistical_probability_status, explanation, warnings, rule versions
- [ ] Until Phase 7: `probability_status = UNAVAILABLE_UNCALIBRATED`
- [ ] No invented numerical success probabilities

---

## STEP 12 — EXPLANATION GENERATOR
- [ ] `services/explanation_builder.py`
- [ ] Readable explanations from structured evidence
- [ ] Explain why setup qualifies, why opposing evidence rejected, which conditions invalidate, what info missing, why NO_TRADE when applicable
- [ ] Never claim certainty

---

## STEP 13 — DATABASE MODELS
- [ ] `models.py` with:
  - [ ] `StrategyEvaluation` (main evaluation record)
  - [ ] `StrategyCandidate` (bullish/bearish candidates)
  - [ ] `EvaluationEvidence` (links to evidence items)
  - [ ] `EvaluationConflict` (conflicts)
  - [ ] `DecisionAuditLog` (audit trail)
  - [ ] `StrategyRuleConfiguration` (versioned configs)
- [ ] Store rule/config versions
- [ ] Preserve input snapshot for each decision (reproducible)
- [ ] Create migrations
- [ ] Run migrations

---

## STEP 14 — API ENDPOINTS
- [ ] `serializers.py`, `views.py`, `urls.py`
- [ ] Endpoints:
  - [ ] `POST /api/strategies/evaluate/`
  - [ ] `GET /api/strategies/evaluations/{id}/`
  - [ ] `GET /api/strategies/history/`
  - [ ] `GET /api/strategies/rules/`
- [ ] Authenticated, ownership/permissions enforced
- [ ] Protect global strategy configs (read-only or admin-only for changes)

---

## STEP 15 — DECISION DASHBOARD
- [ ] Create dashboard views/templates for strategy evaluation results
- [ ] Show: uploaded screenshot, instrument/timeframe, MT5 verification, market context, strategy family, UP/DOWN/NO_TRADE, supporting evidence, contradictions, invalidation, signal/target candle times, confluence score (if avail), probability calibration status, data freshness warnings
- [ ] Clearly distinguish research hypotheses from validated probabilities
- [ ] Add routes in dashboard if needed

---

## STEP 16 — TESTING
- [ ] Comprehensive test suite in `tests/test_strategy_engine_*.py` (top-level `tests/`)
- [ ] Test cases:
  - [ ] Bullish S/R rejection
  - [ ] Bearish S/R rejection
  - [ ] Bullish RBS
  - [ ] Bearish SBR
  - [ ] Bullish liquidity sweep
  - [ ] Bearish liquidity sweep
  - [ ] Conflicting evidence
  - [ ] Missing strategy conditions
  - [ ] Double-counted evidence
  - [ ] Stale screenshots
  - [ ] Unfinished candles
  - [ ] Expired entry windows
  - [ ] OTC incompatibility
  - [ ] Missing MT5 data
  - [ ] Incorrect timeframe
  - [ ] Invalidated setups
  - [ ] NO_TRADE reason codes
  - [ ] Deterministic repeated evaluation
  - [ ] API authorization
  - [ ] No fabricated probabilities
- [ ] Use synthetic historical fixtures
- [ ] Ensure engine never accesses candles after evaluation timestamp

---

## ACCEPTANCE CRITERIA
- [ ] All three strategy families implemented
- [ ] Course evidence incorporated
- [ ] Bullish and bearish candidates evaluated independently
- [ ] Mandatory invalidation rules work
- [ ] Conflicting evidence handled
- [ ] NO_TRADE decisions include clear reasons
- [ ] Next-candle timing explicit
- [ ] Evaluation results reproducible
- [ ] Reports explain detected setup
- [ ] No fabricated probabilities appear
- [ ] All tests pass (new + existing)
- [ ] Ruff check passes
- [ ] Ruff format check passes
- [ ] Documentation updated
- [ ] Migrations created and applied successfully

---

## DOCUMENTATION
- [ ] Update `README.md` (Phase 6 status)
- [ ] Update `docs/ARCHITECTURE.md` (add strategy_engine app, Phase 6 section)
- [ ] Create `docs/PHASE-6-REPORT.md` (completion report)
- [ ] Update other relevant docs as needed

---

## VERIFICATION COMMANDS
- [ ] `.\.venv\Scripts\python.exe manage.py check`
- [ ] `.\.venv\Scripts\python.exe manage.py makemigrations --check`
- [ ] `.\.venv\Scripts\python.exe -m pytest -v` (all tests)
- [ ] `.\.venv\Scripts\ruff.exe check .`
- [ ] `.\.venv\Scripts\ruff.exe format --check .`

---

## FINAL STEPS
- [ ] Run full test suite and all checks
- [ ] Produce detailed completion report
- [ ] Stop after Phase 6 and wait for approval before Phase 7