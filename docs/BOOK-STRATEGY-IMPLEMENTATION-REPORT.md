# BOOK STRATEGY IMPLEMENTATION REPORT — Phase 13

Date: 2026-10-18. Status: COMPLETE — delivered for review. Nothing was deployed.
Base commit: `4eac705` (Phase 12 push).

Phase 13 extracted, catalogued, implemented, recognized and began validating the
strategies from the supplied Binary Options Trading Bible PDF (30 Sure Shot
patterns + 2 Chapter 7 indicator strategies) inside the existing Django app. It
did **not** rebuild any existing module (vision pipeline, price-action engine,
indicators and knowledge base from Phases 5/12 were reused as-is), did not touch
the decision engine, and did not weaken the NO TRADE policy.

Companion documents:

- `docs/BINARY-TRADING-BIBLE-STRATEGY-CATALOG.md` — the full 32-entry catalog
  with PDF page references and every recorded contradiction/ambiguity.
- `docs/BOOK-STRATEGY-VALIDATION-REPORT.md` — pilot chronological replay over
  genuine MT5 candles, with real numbers and uncertainty.

## What was delivered

### 1. Catalog (`apps/book_strategies/constants.py`)

All 32 entries (SS1–SS30, CH7_S1, CH7_S2) as immutable `BookStrategySpec`
records: stable key, name, chapter, PDF page range, market types, trade type,
requirements in the book's wording, confirmation rule, invalidation rules,
martingale policy text, recorded contradictions, recorded ambiguities,
illustration evidence, detector key, priority flag. Plus the enums
`BookPatternState`, `DataVerification` (incl. `NOT_EVALUATED` for catalogued
entries with no detector) and `ResearchStatus`.

### 2. Deterministic detectors (`apps/book_strategies/services/detectors.py`)

Ten priority strategies implemented as pure functions over candle dicts:

| Detector | Strategy | Notes |
| --- | --- | --- |
| `ss1` | Sequence Breakout Continuation | 1 opposite + back-to-back pair + breakout; level = max high of the pair |
| `ss2` | Magic V | SS1 seed + one waited-for candle in the same direction |
| `ss3` | Magic V Advanced | Trades the breakout candle itself |
| `ss5` | Four-Candle Pullback Hold | Run of 4 + shallow pullback + hold; strict `high > level` invalidation |
| `ss6` | Four-Candle Body Breakout | Wick-only touches are explicitly NOT breakouts |
| `ss19` | Doji-Level Breakout | Doji range edges form the reference zone; dojis terminate colour runs |
| `ss21` | Five-Candle Reference Breakout | 5-run + red reference + closing break above reference high |
| `ss22` | Rising Three Method | 3 greens + 3 contained reds + full-range engulfing green |
| `ss23` | Falling Three Method | Mirror of SS22; implements the mirror-accurate reading of the book typo (recorded) |
| `ch7_s1` | EMA5 + SAR + Stochastic | EMA crossing candle must be "strong" (explicit median-body metric), SAR on side, stochastic %K/%D aligned |

Design decisions (all recorded, none silent):

- **State machine**: every detector returns exactly one of `FORMING`,
  `AWAITING_CONFIRMATION`, `CONFIRMED_PATTERN`, `INVALIDATED`,
  `INSUFFICIENT_DATA`. `CONFIRMED_PATTERN` is a completed *pattern observation*,
  never a trade prediction.
- **Dual-side Magic V**: SS1/SS2/SS3 evaluate BOTH seed sides and pick the most
  advanced state (CONFIRMED > INVALIDATED > AWAITING > FORMING/INSUFFICIENT,
  tie-break most recent seed) — this fixed a real bug where the most-recent
  mirror seed could mask a completed setup on the other side.
- **Forming last candle**: when the caller declares the last candle still
  forming and the completion candle IS that provisional candle, confirmation is
  downgraded to `AWAITING_CONFIRMATION` with an explicit missing condition; a
  completion on an earlier closed candle keeps the confirmed state with a note.
- **Indicators**: reused Phase 2 causal indicators (`ema`, `parabolic_sar`,
  `stochastic`, `stochastic_supported`, `donchian`) — all verified causal in
  tests (prefix-stability under appended future candles).

### 3. Recognition (`apps/book_strategies/services/recognition.py`)

- `BookStrategyRecognizer.evaluate(key, candles, ...)`: OHLC-verified evaluation
  with the Step 9 structured response — every result carries
  `decision = NO_TRADE`, `probability = null`,
  `probability_status = UNAVAILABLE_UNCALIBRATED`. Optional
  `screenshot_is_otc` / `feed_market_type` inputs refuse verification with
  `INCOMPATIBLE_FEEDS` when an OTC screenshot would be checked against
  non-OTC candles; OTC is never verified with MT5 regular-session data.
- `evaluate_enabled`: runs only strategies with the admin `recognition_enabled`
  switch on; optional persistence writes `BookStrategyDetection` rows.
- `build_book_candidates(analysis)`: vision→book mapper over a **fixed table**
  (bullish/bearish engulfing→SS4, doji family→SS12/SS19/SS20, hammer /
  inverted hammer→SS15/SS16, three white soldiers→SS22, three black
  crows→SS23; morning/evening star deliberately unmapped). Candidates are
  capped at `AWAITING_CONFIRMATION` / `SCREENSHOT_ONLY`, list every missing
  condition, and **never invent OHLC values**.

### 4. Explainer (`apps/book_strategies/services/explainer.py`)

Deterministic 10-question explanation built only from the stored catalog fields
and the detection result (which strategy/pattern number, pattern candles,
reference level, breakout status, last-candle completeness, missing conditions,
invalidation rules, direction rationale, and the explicit NO TRADE rationale
stating the pattern is not a calibrated prediction). No LLM invents or
overrides any of it; `FORMING` is worded as "not yet a detection".

### 5. Validation (`apps/book_strategies/services/validation.py`)

Chronological replay with a hard no-future-leakage rule (a signal at index *i*
is computed only from candles `[0..i]`; the outcome is candle *i+1*'s direction;
a fresh-signal rule prevents re-signalling while a previous signal is live),
chronological 70/30 in-sample/out-of-sample split (never shuffled), Wilson 95%
intervals, an unconditional-majority baseline per window, and an explicit
metric-scope disclaimer: next-candle direction is **not** binary settlement.
`sufficient_data` is False below 30 pooled signals AND below 30 out-of-sample
signals; when insufficient, expectancy stays `null` and no accuracy claim is
made. `approved_for_decision_use` is always False in report output.

### 6. Dashboard, seeding, assistant

- `/dashboard/book-strategies/` (list, grouped by chapter, search) and
  `/dashboard/book-strategies/<key>/` (detail: confirmation rule, invalidation
  rules, requirements, recorded contradictions/ambiguities, market/MTG policy,
  recent recognitions) — staff-only toggle flips **only** `recognition_enabled`;
  it never touches `decision_use_approved` and never enables trading. Nav link
  added to the sidebar.
- `seed_book_strategies` management command: idempotent upsert of all 32
  entries (preserves an advanced `research_status` on re-seed; all
  recognition/decision switches default OFF). Migration
  `book_strategies/0001_initial` applied.
- `validate_book_strategies` management command: chronological replay over
  stored `MarketCandle` rows (complete + quality `ok` only), writes a JSON
  artifact to `docs/artifacts/book_validation.json`.
- Assistant: bounded (≤1400 chars) `_book_context` block wired into follow-up
  reasoning; it quotes only stored catalog fields, always states
  `NO TRADE; probability unavailable (uncalibrated)`, and contains no accuracy
  or win-rate numbers (the model cannot receive a fabricated stat to repeat).

## Tests

`tests/test_book_strategies.py` — **83 tests**, all passing:

- Catalog completeness (32 entries, PDF page refs on every entry, sure shots
  numbered 1–30, exactly 2 Chapter 7 entries, contradictions present for the
  five known book conflicts, SS10/SS11 catalogued without detectors).
- Detectors: positive confirmation for all 10; negative (`FORMING`), incomplete
  (`AWAITING_CONFIRMATION`), lookalike rejection (SS6 wick-only "breakout",
  monotonic series with no EMA cross), invalidation (SS5 broken level), empty
  /short series (`INSUFFICIENT_DATA`), forming-last-candle never confirms,
  valid-state invariant across all detectors.
- Indicator causality (stochastic/EMA/PSAR prefix-stability).
- No-lookahead property: replay signal at index *i* equals the standalone
  detector on the prefix; appending future candles cannot change a past signal.
- Mapper: candidates capped at AWAITING/SCREENSHOT_ONLY, no OHLC invented,
  unknown labels map to nothing, OTC metadata detected (`otc_status` enum
  honoured).
- Recognizer: confirmed pattern still returns NO TRADE + null probability;
  Step 9 field shape; catalog-only key → `INSUFFICIENT_DATA / NOT_EVALUATED`;
  OTC mismatch → `INCOMPATIBLE_FEEDS`; enabled-only evaluation; persistence.
- Validation honesty: zero-signal report invents no accuracy, Wilson interval
  sanity, chronological OOS split, baseline present in every split, expectancy
  null when insufficient, `approved_for_decision_use` always False, metric
  scope disclaimer wording.
- Explainer: 10 questions present, FORMING wording, invalidation rationale,
  forming-candle missing condition.
- Dashboard: list/detail 200s, 404 for unknown key, login required, non-staff
  toggle rejected, staff toggle flips recognition only, GET returns 405, list
  marks entries "Not approved for decisions".
- Seed command: idempotent, 10 entries marked `implemented`, advanced status
  preserved across re-seed, all switches stay off.
- Assistant: unrelated message gets no block; book mention gets a bounded
  block containing `NO TRADE`/`uncalibrated`; no `win rate`, `accuracy` or `%`
  appears in any block.

Repository-wide gates after this phase: **1108 passed, 3 skipped** (existing
suite + Phase 13), `ruff check apps tests` clean, `manage.py check` clean,
`makemigrations --check` clean.

## Phase 13 continuation — research pipeline (R1–R10)

The first pass above delivered the catalog, detectors, recognition, explainer and
a pilot validation. The continuation completed the remaining research
requirements so the strategies are genuinely *researchable* without ever
fabricating a result. Every component below is additive; nothing existing was
rebuilt.

### R1 — Dataset import with provenance (`apps/research/services/dataset_builder.py`)

`DatasetBuilder.import_ohlc()` validates, sorts, dedupes and gap-detects raw
OHLC rows. It **rejects rather than repairs**: rows with impossible
high/low/open/close relationships, missing timestamps or duplicates are dropped
and counted, and genuine gaps are flagged (never filled). A
`metadata.provenance` block records the source-file SHA-256, importer, accepted
/ rejected counts, the reasons for each rejection, and the gap count; naive
timestamps are assumed UTC and flagged. `is_validated` is true only when there
are zero rejects **and** zero gaps. The `import_ohlc_csv` command wraps this
with header aliasing and hashes the input file bytes.

### R2 — Deterministic leak-free backtesting (`services/backtest.py`)

`BookBacktestService.run()` replays the shared causal machinery once and persists
a `BacktestRun` (kind `book_strategy`). Results are byte-identical across runs on
the same input. `metrics` always carries `approved_for_decision_use: False`,
`metric_scope = "next_candle_direction"` and an accuracy status. Signals come
from the causal replay only (signal at *i* uses `candles[0..i]`, outcome is
`i+1`), and `advance_research_status()` can move an entry **at most** to
`backtested`.

### R3 — Chronological OOS + walk-forward (`services/walk_forward.py`)

`WalkForwardValidation.chronological_folds()` returns chronological, disjoint
half-open `[start, end)` windows with `end <= n-1` — never shuffled.
`BookWalkForwardService` partitions a single causal replay across those folds
(no re-running the detector per fold, so there is no window leakage) and reports
per-fold **and** pooled statistics: signal counts, accuracy, Wilson 95%
intervals and the unconditional baseline for each window. Insufficient results
carry explicit reasons (no signals, below threshold, series too short, no
folds); the dict includes `metric_scope` and a disclaimer that this is **not**
binary settlement.

### R5 — Comparison / ranking (`services/comparison.py`)

`BookComparisonService.compare()` ranks **only** rows with sufficient validation
**and** sufficient walk-forward evidence, ordered by out-of-sample margin
(accuracy minus baseline) descending, ties broken by sample size. Unranked rows
are sorted by key alone — never by accuracy. Tiers are
`candidate_for_further_research`, `ranked_but_below_baseline` and
`insufficient_evidence_unranked`, and `approved_for_decision_use` is False on
every row. The run is persisted as a `BacktestRun` (kind `book_comparison`).

### R6 — Recognition vs prediction separation (`services/metrics.py`)

Two explicit scopes: `pattern_recognition` and `next_candle_direction`.
`assert_recognition_scope()` / `assert_prediction_scope()` are hard walls in both
directions, so a recognition figure can never be quoted as a predictive one and
vice versa. `recognition_accuracy` is always `None`
(`NOT_COMPUTABLE_NO_GROUND_TRUTH`), and `verify_reproducibility()` re-runs a
detector twice and states that it proves *recognition* reproducibility only,
not predictive power.

### R7 — Binary settlement evaluation (`services/settlement.py`)

`BookSettlementService` wraps the research `BinarySettlement` primitive and
returns explicit states (win / loss / tie / unverifiable / refused). Missing
quotes yield `UNVERIFIABLE` with no win rate invented; an OTC screenshot checked
against MT5 regular-session data is **refused** with `INCOMPATIBLE_FEEDS` and
never coerced. `summarize()` counts only *verified* settlements and reports
unverifiable/refused separately with a warning; scope is `binary_settlement`.

### R8 — Immutable paper forward predictions (`services/paper_forward.py`)

`PaperForwardPrediction` freezes a prediction at creation behind a
`payload_sha256` and a `PROTECTED_FIELDS` / outcome-field guard enforced in
`save()`. Status changes happen only through `resolve()`, which requires a
complete outcome candle opening exactly at the signal's close time; incomplete
outcome candles are skipped, not raised. Verified settlement fields
(WIN/LOSS/TIE) are write-once; unverifiable ones may be re-evaluated.
`verify_integrity()` detects tampering. `PaperForwardService` provides
`record()` / `resolve()` / `settle()` / `summary()`, and the
`record_paper_predictions` / `resolve_paper_predictions` commands scope feeds by
the shared source labels `mt5:SYM:TF` and `historical_import:<name>`.

### R9 — Decision-engine integration (`apps/strategy_engine/…`)

`StrategyFamily.BOOK_PATTERN` was added (with a migration).
`book_strategy_candidates()` returns a candidate only when the entry has
`decision_use_approved AND recognition_enabled` **and** a fresh
`CONFIRMED_PATTERN` on the latest *closed* candle; any exception degrades to an
empty list (never propagates). Book candidates are appended after the engine's
own candidates, and book evidence never overrides a NO TRADE safeguard. Because
`decision_use_approved` is False for every entry, the hook is inert in practice —
it is a correctly-gated placeholder for a future approved strategy.

### R10 — Research dashboard (`apps/dashboard/…`)

`/dashboard/book-strategies/research/` (`book_research` view + template) shows
the recognition-scope markers (`pattern_recognition`,
`NOT_COMPUTABLE_NO_GROUND_TRUTH`), the paper-prediction summary, the comparison /
ranking table, recent backtest runs and imported datasets with their provenance.
It always displays an explicit "not a performance claim / not binary-option
settlement" warning. A "Research metrics →" link was added to the catalog list
page. `PaperForwardPrediction` is registered in the admin read-mostly
(`has_add_permission = False`).

### Continuation tests

`tests/test_phase13_research.py` — **75 tests** covering R1–R10 and the new
management commands, all passing. Repository-wide gates after the continuation:
**1183 passed, 3 skipped** (2 Postgres-only, 1 live-LLM-gated), `ruff check apps
tests` clean, `manage.py check` clean, `makemigrations --check --dry-run` =
"No changes detected".

## Known follow-ups (not blockers)

- The end-to-end persisted vision run against the book mapper remains gated on
  the Gemini free-tier quota reset (Phase 12 item, unchanged).
- Pilot validation on the current genuine-data sample is statistically
  insufficient for every strategy (see the validation report); more clean
  candles are required before any accuracy claim could even be considered, and
  `decision_use_approved` stays False regardless.
- Production deployment remains forbidden without explicit user authorization;
  nothing in Phase 13 was deployed.

**Phase 13 is complete. Phase 14 was not started.**
