# Phase 5 Report — Price-Action Knowledge Engine

**Status:** complete and verified. The engine is deterministic and DB-free at runtime;
it evaluates synthetic/stored candles and returns machine-readable evidence. It never
executes trades, fabricates OHLC/prices, estimates a trading probability or predicts the
next candle.

## Summary

`apps.price_action` implements the Nazbeen Academy price-action knowledge base as a set
of pure, deterministic detectors plus an orchestrating engine. `PriceActionEngine.run()`
accepts a candle series (list, dict payload or `MarketInput`), evaluates the concepts,
and returns a versioned, machine-readable document containing `evidence`, `conflicts`,
`context` and a descriptive `summary`. Contradictory observations are **preserved**;
they are surfaced as conflicts rather than resolved with a probability.

## Delivered components

### Services (`apps/price_action/services/`)
| Module | Responsibility |
|---|---|
| `config.py` | `PriceActionConfig` (28 thresholds, `slots=True`) with field→env map and `from_settings()` |
| `dto.py` | Immutable `Candle` / `MarketInput` DTOs; `candle_from_dict`, `candles_from_dicts`, `as_plain` |
| `candle_math.py` | Range/body/wick ratios, real-body bounds, doji, average range, strength classification, rejection/sweep-candidate helpers, OHLC aggregation |
| `market_structure.py` | Swing detection (no look-ahead), HH/HL/LH/LL labelling, trend inference, structure state, BOS, failed breakout, consolidation |
| `support_resistance.py` | Zone detection (clustered swings + touch counts), wick rejection, breakout confirmation, retest, SBR/RBS flip, level invalidation |
| `buyer_seller_failure.py` | Buyer-source support / seller-source resistance, failure events, source strength |
| `candlestick_patterns.py` | 14 single/two/three-candle patterns + `detect_patterns` with context/invalidation |
| `candle_sequences.py` | Directional runs, reference sequences, similar sequences, lonely candles, psychological-sequence templates |
| `market_cycle.py` | Motive / counter / last-effort cycle classification |
| `liquidity_sweeps.py` | Previous high/low sweeps and sweep outcome (rejection/continuation/pending) |
| `order_blocks.py` | Order blocks under two separate definitions (`teacher_pattern`, `ict_style`); lifecycle annotation |
| `fair_value_gaps.py` | True 3-candle FVG detection + open/mitigated/invalidated state; sweep confluence |
| `opening_gaps.py` | Close→open gap detection and reaction annotation |
| `volume_analysis.py` | Volume source separation (real vs tick), effort/result, anomaly and sequence patterns, reversal context |
| `market_context.py` | Session bands, overlap, regime, volatility, news status, freshness, `build_context` |
| `evidence_registry.py` | Full `Evidence` record + append-only `EvidenceRegistry` |
| `conflict_detector.py` | `detect_conflicts` → `ConflictRecord` (never resolves by probability) |
| `engine.py` | `PriceActionEngine.run()` orchestration + machine-readable output |

### Schemas & knowledge
- `schemas/market_input.py`: `MARKET_INPUT_SCHEMA` (v1.0), `validate_payload`,
  `build_market_input` (data quality, warnings, strict mode)
- `knowledge/catalogue.py`: versioned `Concept` catalogue (course interpretation,
  implementation, required inputs, detection logic, limitations); `get_concept`,
  `catalogue()`

### Domain (`models.py`, `admin.py`, `exceptions.py`)
- `PriceActionRun` — owner, `input_snapshot`, `result`, `schema_version`,
  `engine_version`, `candles_evaluated`
- `EvidenceItem` — run, `rule_id`, `detector`, `status`, `direction`, `explanation`,
  `candle_refs`, `supporting_levels`, `reasons`, `missing_inputs`, `data_quality`
- `exceptions.py`: `PriceActionError`, `InvalidInputError`, `MissingInputError`,
  `SchemaValidationError`, `DetectorError`
- Migrations: `0001_initial`, `0002_alter_evidenceitem_supporting_levels`

### Constants (`constants.py`)
30 `TextChoices` enums (evidence status, direction, trend, swings, structure, zones,
rejection, data quality, candle strength, volume source, gap/FVG, market type/regime/
volatility, sessions, news, sweep type/outcome, OB type/definition, cycle phase,
conflict type, severity) plus `PA_ENGINE_SCHEMA_VERSION`, `PA_MARKET_INPUT_SCHEMA_VERSION`,
`PA_RULE_VERSION`, `PA_KNOWLEDGE_VERSION`.

## Engine output contract

`PriceActionEngine.run(input_, now=None)` returns:

| Key | Meaning |
|---|---|
| `schema_version` / `engine_version` / `knowledge_version` | Version stamps (`1.0`) |
| `timeframe`, `canonical_instrument`, `broker_symbol`, `market_type` | Input echo |
| `candles_evaluated` | Number of **completed** candles evaluated |
| `data_quality`, `warnings` | From the validated market input |
| `context` | Session, overlap, regime, volatility, consolidation, news status, freshness |
| `evidence` | List of full evidence records (`Evidence.to_dict`) |
| `conflicts` | List of `ConflictRecord`s |
| `summary` | Descriptive counts only — *"no trading probability is computed"* |

Inputs accepted: a list of candle dicts, a dict payload (`{"candles": [...], ...}`) or a
built `MarketInput`. `None`/empty input is safe (0 candles evaluated). The run is
**deterministic** and **look-ahead free** (only completed candles; refs never exceed the
series).

### Rule-ID families
`pa.structure.*`, `pa.sr.*`, `pa.bsf.*`, `pa.candle.*`, `pa.sequence.*`, `pa.cycle.phase`,
`pa.sweep.*`, `pa.ob.*`, `pa.fvg.*`, `pa.gap.*`, `pa.volume.*`, `pa.context.*`.

### Conflict types (reported, never resolved)
`opposing_evidence`, `bullish_after_buyer_failure`, `bearish_after_seller_failure`,
`reversal_against_breakout`, `sbr_rbs_without_break`, `sweep_without_recovery`,
`pattern_in_consolidation`, `unconfirmed_pivot` (severity *error*), `source_incompatible`.

## Configuration

`config/settings/base.py` registers `apps.price_action` and all `PA_*` variables; see
`.env.example`. Notable defaults: `PA_SWING_LOOKBACK=2`, `PA_ZONE_TOLERANCE=0.0015`,
`PA_ZONE_MIN_TOUCHES=2`, `PA_STRONG_BODY_RATIO_MIN=0.60`, `PA_SWEEP_MIN_PENETRATION=0.0`,
`PA_HIGH_VOLUME_MULTIPLE=1.5`, `PA_MAX_CANDLES=500`, `PA_MIN_CANDLES=3`,
`PA_KNOWLEDGE_VERSION=1.0`. Thresholds are pragmatic, not scientifically validated.

## Tests

| File | Tests |
|---|---|
| `test_price_action_candle_math.py` | 7 |
| `test_price_action_structure.py` | 8 |
| `test_price_action_zones.py` | 6 |
| `test_price_action_patterns.py` | 11 |
| `test_price_action_sequences.py` | 7 |
| `test_price_action_buyer_seller.py` | 6 |
| `test_price_action_sweeps_gaps.py` | 11 |
| `test_price_action_volume.py` | 8 |
| `test_price_action_context.py` | 10 |
| `test_price_action_evidence.py` | 9 |
| `test_price_action_market_input.py` | 8 |
| `test_price_action_knowledge.py` | 4 |
| `test_price_action_engine.py` | 12 |
| **Total** | **107 passed** |

Shared fixtures live in `tests/pa_fakes.py`. Every detector has positive and negative
cases; the engine suite asserts the integrity guarantees (no prediction/probability/
recommendation, deterministic output, completed-candles-only, bounded refs).

## Verification results

| Check | Result |
|---|---|
| `manage.py check` | no issues |
| `manage.py makemigrations --check --dry-run` | no changes |
| `ruff check .` | all checks passed |
| `ruff format --check .` | all formatted |
| `pytest` (full suite) | **468 passed, 2 skipped** (unchanged PostgreSQL-only skips) |

## Integrity & policy notes
- No order-execution capability exists anywhere in the layer.
- No OHLC, prices, or success probabilities are fabricated; ratios return `None` on
  zero-range candles instead of dividing by zero.
- Contradictory observations are preserved and reported; conflicts carry severity and are
  never collapsed into a probability or a directional recommendation.
- Missing/insufficient data produces `insufficient`/`unknown` evidence, never a guess.
- Two order-block definitions are kept separate and never merged; the course ambiguity is
  documented.
- Only the completed candles are evaluated; the rightmost/incomplete candle is excluded.

## Known limitations
- Trendline rejection and round-number confluence from the knowledge index are deferred.
- Thresholds are pragmatic, not scientifically validated; tune via `PA_*` and re-run tests.
- The engine returns in-memory documents; persisting into `PriceActionRun`/`EvidenceItem`
  and exposing them through the API/dashboard is deferred to a later phase.
- No live-data run was performed; detectors are exercised with deterministic synthetic
  fixtures.

## Files added/changed
Added: `apps/price_action/*` (constants, config/DTO, schemas, 18 service modules,
knowledge catalogue, exceptions, models/admin/apps, migrations, empty `views/urls/rules`
placeholders) and `tests/pa_fakes.py` + 13 Phase 5 test files (107 tests).
Changed: `config/settings/base.py`, `.env.example`, `README.md`, `docs/ARCHITECTURE.md`,
`docs/PRICE-ACTION-KNOWLEDGE-BASE.md`, and the new Phase 5 docs.

Phase 5 complete. No regressions to Phases 1–4; full suite green.
