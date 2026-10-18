# Phase 5 Checklist — Price-Action Knowledge Engine

Legend: ✅ done & verified · ⚠️ partial / documented limitation · ⬜ out of scope

App: `apps.price_action` (constants, `services/`, `schemas/`, `knowledge/`, `rules/`,
`migrations/`). Detectors are pure, deterministic functions over plain candle dicts;
the engine converts the standardized `MarketInput` to plain dicts before detection.

## Step 1 — Audit
- ✅ Inspected Phases 1–4 (`core`, `market_data`, `chart_vision`, `market_sync`) and the
  authoritative `docs/PRICE-ACTION-KNOWLEDGE-BASE.md` concept index
- ✅ Confirmed no prior working price-action engine existed; rebuilt the broken scaffold
- ✅ Preserved all policy constraints: no trade execution, no fabricated OHLC/prices,
  no trading probabilities, no next-candle predictions, OTC never substituted
- ✅ Baseline of prior suite recorded; Phase 5 added 107 tests, all green

## Step 2 — Scaffold, constants, DTOs & config
- ✅ `constants.py`: 30 `TextChoices` enums (evidence status, direction, trend, swings,
  structure, zones, rejection, data quality, candle strength, volume source, gap/FVG,
  market type/regime/volatility, sessions, news, sweeps, order blocks, cycle, conflict,
  severity) plus version constants `PA_ENGINE_SCHEMA_VERSION`, `PA_MARKET_INPUT_SCHEMA_VERSION`,
  `PA_RULE_VERSION`, `PA_KNOWLEDGE_VERSION`
- ✅ `services/dto.py`: immutable `Candle` / `MarketInput` DTOs + `candle_from_dict`,
  `candles_from_dicts`, `as_plain`
- ✅ `services/config.py`: `PriceActionConfig` (28 thresholds, `slots=True`) with a
  field→env map and `from_settings()`; defaults documented as pragmatic
- ✅ `exceptions.py`: `PriceActionError` hierarchy

## Step 3 — Versioned market-input schema
- ✅ `schemas/market_input.py`: `MARKET_INPUT_SCHEMA` (v1.0), `validate_payload`,
  `build_market_input`
- ✅ Validates candles; flags missing fields, non-list candles, `high < low`, etc.
- ✅ Records `data_quality`, `warnings`, `candle_count`; strict mode raises
  `SchemaValidationError`; unknown `market_type` → `unknown` + warning
- ✅ Completed candles only: rightmost/incomplete candles are excluded by the engine

## Step 4 — Candle math & strength
- ✅ `services/candle_math.py`: range, body, body/range ratio, upper/lower wick ratios,
  real-body top/bottom, `is_doji`, `average_range`, `classify_strength`,
  `is_rejection_candle`, `is_wick_sweep_candidate`, `aggregate_ohlc`
- ✅ Ratios return `None` for zero-range candles (never divide by zero)

## Step 5 — Market structure
- ✅ `services/market_structure.py`: `detect_swings` (lookback, no look-ahead),
  `label_swings` (HH/HL/LH/LL), `infer_trend`, `structure_state`,
  `detect_structure_break` (BOS), `detect_failed_breakout`, `detect_consolidation`
- ✅ Trend requires a minimum number of swings; too few → `insufficient`/`unknown`

## Step 6 — Buyer/seller source identification & failure
- ✅ `services/buyer_seller_failure.py`: `buyers_create_support`,
  `sellers_create_resistance`, `detect_failures`, `source_strength`,
  `detect_buyer_seller_failure`
- ✅ Failure events: buyers failed to break resistance / sellers failed to break support
- ✅ Output explicitly states "not an intent claim" (source ≠ intent)

## Step 7 — Candlestick patterns
- ✅ `services/candlestick_patterns.py`: bullish/bearish engulfing, hammer, shooting
  star, doji, bullish/bearish harami, inside bar, outside bar, piercing, dark cloud,
  morning/evening star, three white soldiers/three black crows
- ✅ `detect_patterns` returns name, direction, candle count/refs, context requirement,
  invalidation condition

## Step 8 — Support & resistance
- ✅ `services/support_resistance.py`: `Zone`, `detect_zones` (clustered swings +
  touch counting), `detect_rejection` (wick rejection), `detect_breakout_confirmation`,
  `detect_retest`, `detect_sbr_rbs` (support↔resistance flip), `is_level_invalidated`
- ✅ `zone_kind`/`zone_state` distinguish support/resistance and flip state

## Step 9 — Reference sequences
- ✅ `services/candle_sequences.py`: `directional_runs`, `consecutive_bullish/bearish`,
  `analyze_reference_sequences` (current run, extension, optional strengthening/weakening)
- ✅ No look-ahead: only trailing runs to the last completed candle

## Step 10 — Similar sequences
- ✅ `similar_sequences`: trailing signature compared to earlier windows; reports
  `predictive_claim=False` and requires a minimum sample count
- ✅ Insufficient samples → `insufficient`, never an inferred outcome

## Step 11 — Lonely candles
- ✅ `lonely_candles`: an isolated counter-direction candle inside a run, reported as a
  hypothesis (e.g. "candidate seller-stop support"), never a certainty

## Step 12 — Psychological sequences
- ✅ `psych_sequences`: the eight psychological templates matched against the trailing
  sign sequence; results flagged `template_not_signal`

## Step 13 — Market cycle
- ✅ `services/market_cycle.py`: `classify_cycle` → motive / counter / last-effort /
  unknown with reasons; insufficient history → `insufficient`

## Step 14 — Liquidity sweeps
- ✅ `services/liquidity_sweeps.py`: `prev_high_sweep`, `prev_low_sweep`, `detect_sweep`
  (type, penetration, closed-back-inside, outcome: rejection/continuation/pending)

## Step 15 — Order blocks (two definitions, never merged)
- ✅ `services/order_blocks.py`: `detect_order_blocks(definition=...)` supports both
  `TEACHER_PATTERN` and `ICT_STYLE`; each result carries its `definition`
- ✅ ICT style additionally requires an imbalance; the ambiguity between the two course
  definitions is documented, not resolved by preference

## Step 16 — Fair value gaps
- ✅ `services/fair_value_gaps.py`: `detect_fvg` (true 3-candle definition:
  bullish `left.high < right.low`; bearish `left.low > right.high`),
  `classify_fvg_state` (open/mitigated/invalidated), `annotate_fvg_states`,
  `fvg_sweep_confluence`

## Step 17 — Opening gaps
- ✅ `services/opening_gaps.py`: `detect_opening_gaps` (close→open discontinuity),
  `gap_reaction`, `annotate_gap_reactions`

## Step 18 — Volume intelligence
- ✅ `services/volume_analysis.py`: `volume_of` (real volume preferred, tick volume
  separately labelled, never merged), `average_volume`, `volume_effort_result`,
  `detect_volume_patterns` (high/low volume × narrow/wide range, rising/falling
  sequences), `reversal_pattern_volume_context`

## Step 19 — Market context
- ✅ `services/market_context.py`: `classify_session` (UTC session bands, requires
  tz-aware time), `session_overlap`, `classify_regime`, `classify_volatility`,
  `news_status` (UNKNOWN without a provider), `freshness_status`, `build_context`
- ✅ News/events never invented; missing provider → `news_status_unknown`

## Step 20 — Evidence registry
- ✅ `services/evidence_registry.py`: full `Evidence` record (rule_id, rule_version,
  detector, status, direction, explanation, candle_refs, supporting_levels, timestamps,
  required/invalidation conditions, missing_inputs, data_quality, reasons, metrics) +
  append-only `EvidenceRegistry` (add/all/by_detector/by_status/directions/to_dicts)
- ✅ Contradictory evidence is preserved, never overwritten

## Step 21 — Conflict detector
- ✅ `services/conflict_detector.py`: `detect_conflicts` → `ConflictRecord` for
  opposing evidence, bullish-after-buyer-failure, sweep-without-recovery,
  unconfirmed pivot (severity error), source-incompatible
- ✅ Conflicts are reported with severity; they are never resolved with a probability

## Step 22 — Knowledge catalogue
- ✅ `knowledge/catalogue.py`: versioned catalogue of every implemented concept
  (course interpretation, implementation, required inputs, detection logic,
  limitations); `get_concept` lookup; `catalogue()` embeds `PA_KNOWLEDGE_VERSION`

## Step 23 — Engine orchestration, output & no-look-ahead
- ✅ `services/engine.py`: `PriceActionEngine.run(input_)` accepts a list of candles, a
  dict payload, or a `MarketInput`; returns a machine-readable dict with
  `schema_version`, `engine_version`, `knowledge_version`, `context`, `evidence`,
  `conflicts`, `summary`, `candles_evaluated`, `data_quality`, `warnings`
- ✅ No look-ahead: only completed candles are evaluated; refs never exceed the series
- ✅ Never emits a next-candle prediction, trading probability or recommendation
- ✅ Deterministic: identical input → identical output

## Testing
- ✅ `tests/pa_fakes.py` — deterministic candle builders (uptrend/downtrend/flat,
  zigzag, FVG, sweep, volume-anomaly series) + `CONFIG`
- ✅ `tests/test_price_action_candle_math.py` (7)
- ✅ `tests/test_price_action_structure.py` (8)
- ✅ `tests/test_price_action_zones.py` (6)
- ✅ `tests/test_price_action_patterns.py` (11)
- ✅ `tests/test_price_action_sequences.py` (7)
- ✅ `tests/test_price_action_buyer_seller.py` (6)
- ✅ `tests/test_price_action_sweeps_gaps.py` (11)
- ✅ `tests/test_price_action_volume.py` (8)
- ✅ `tests/test_price_action_context.py` (10)
- ✅ `tests/test_price_action_evidence.py` (9)
- ✅ `tests/test_price_action_market_input.py` (8)
- ✅ `tests/test_price_action_knowledge.py` (4)
- ✅ `tests/test_price_action_engine.py` (12)
- ✅ **Total Phase 5 tests: 107 passed** (positive + negative cases per detector;
  deterministic, no network, no live data)

## Config & docs
- ✅ `config/settings/base.py`: registered `apps.price_action`; added all `PA_*` env
  vars with documented defaults
- ✅ `.env.example`: documents the `PA_*` block
- ✅ Migrations: `0001_initial` + `0002_alter_evidenceitem_supporting_levels`
  (corrected a `JSONField(default=float)` → `default=list`); `makemigrations --check` clean
- ✅ Docs: `PHASE-5-REPORT.md`, knowledge-base index updated, `ARCHITECTURE.md`,
  `README.md`

## Acceptance criteria
1. ✅ Patterns/conditions detected deterministically with configurable thresholds
2. ✅ Every detection explains **why** (reasons + required/invalidation conditions)
3. ✅ Contradictory evidence preserved; conflicts surfaced, never resolved by probability
4. ✅ Machine-readable, validated evidence schema (`Evidence.to_dict`)
5. ✅ No final UP/DOWN recommendation, no fabricated success probability, no auto-trading
6. ✅ No silently omitted course concepts (catalogue covers all implemented concepts)
7. ✅ No look-ahead bias; missing data handled safely (insufficient / unknown)
8. ✅ Each detector has positive **and** negative tests
9. ✅ Ruff + full test suite green; docs updated

## Known limitations
- The catalogue covers the concepts implemented in Phase 5; trendline rejection and
  round-number confluence from the index are deferred (noted in the knowledge base).
- Thresholds are pragmatic, not scientifically validated; tune via `PA_*` and re-run
  the detector tests.
- Persistence models (`PriceActionRun`, `EvidenceItem`) exist with a migration, but the
  engine currently returns in-memory dicts; wiring storage into the API/dashboard is a
  later phase.
- Live market data is out of scope for this phase; detectors are exercised with
  deterministic synthetic fixtures.

## Final check
- ✅ `manage.py check` — no issues
- ✅ `makemigrations --check --dry-run` — no changes
- ✅ `ruff check .` — all checks passed
- ✅ `ruff format --check .` — all formatted
- ✅ `pytest` — **468 passed, 2 skipped** (the 2 PostgreSQL-only skips unchanged)
- ✅ No regressions to Phases 1–4
