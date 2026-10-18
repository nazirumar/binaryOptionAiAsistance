# PHASE 12 COMPLETION REPORT — Strategy Knowledge & Pattern Recognition

Date: 2026-10-18. Status: COMPLETE — delivered for review. Nothing was deployed.

Phase 12 added an expandable **Strategy Knowledge and Pattern Recognition
System**: a versioned, structured knowledge base of strategy definitions; a
registry of deterministic detectors; a vision→candidate→verification
pipeline; a dataset workflow; honest detection metrics; dashboard pages; and
an annotation service. It did **not** rebuild existing modules, did not touch
the decision engine, and did not weaken the NO TRADE policy.

## What was delivered (by checkpoint)

| CP | Deliverable |
| --- | --- |
| CP0 | Repository audit + coverage matrix (`docs/PHASE-12-CHECKLIST.md`) |
| CP1 | `apps/strategy_knowledge/`: versioned models (category, version, definition, condition, pattern label, example, detection, evidence, dataset sample), whitelisted param schemas, admin, migration `0001_initial` |
| CP2 | 9 new candlestick detectors (pin bars, inverted hammer, hanging man, dragonfly/gravestone doji, spinning top, tweezer top/bottom) + context-aware alternation suppression in `detect_patterns` |
| CP3 | `level_setups.py`: 7-stage SBR/RBS lifecycle (formation → valid break → retest → acceptance/rejection → completed/invalidated, never skipped), false breakout, failed zone test, engulfing/doji at validated levels |
| CP4 | `market_structure.py`: CHOCH, MSS (CHOCH + displacement, names never merged), trend exhaustion, reversal candidates, structure narrative |
| CP5 | `ict_concepts.py`: equal highs/lows, swing-point sweeps, inducement, displacement, FVG retest, breaker blocks, mitigation report, premium/discount; documented ICT ambiguities recorded on results |
| CP6 | `candle_sequences.py`: candle progress, run count, strong/weak close, failed continuation |
| CP7 | `abc_pattern.py`: generic textbook ABC pivots, explicitly labelled `generic_abc` (course-specific rules were not available in machine-readable form) |
| CP8 | `registry.py`: 74-key `DETECTOR_REGISTRY`; DB definitions reference keys only — unknown keys are inert, detector failures degrade to "no evidence" |
| CP9 | `PatternVerificationService`: DETECTED / POSSIBLE / REJECTED / INSUFFICIENT_EVIDENCE, set deterministically; OTC screenshots capped at `possible` (`otc_incompatible`) and never confirmed with normal-session MT5 prices |
| CP10 | `dedupe_candidates` + `MultiStrategyRecognitionService`: overlapping candidates grouped (shared candles / same family+direction), one primary verified, absorbed candidates recorded in `deduped_from` |
| CP11 | `KnowledgeRetrievalService` + assistant wiring: follow-up reasoning receives a bounded (≤1400 chars) retrieved-knowledge block; drafts/experimental definitions are never retrieved by default |
| CP12 | Dashboard `/dashboard/strategies/` library + `/dashboard/strategies/<id>/` detail pages; experimental entries always visibly labelled |
| CP13 | `annotate_screenshot`: draws only model-reported pixel boxes on a copy; original screenshot bytes are never modified; everything else becomes a text explanation |
| CP14 | `StrategyDatasetWorkflow`: vision candidates, course references and reviewer labels kept in separate lanes; only reviewer-approved samples are ground truth; poor-quality/OTC are first-class sample kinds |
| CP15 | `DetectionMetricsService`: per-strategy/overall precision/recall/F1 over reviewer labels only, always with counts; recall is `None` (undefined) with zero ground-truth positives — never 100% |
| CP16 | Tests + full regression (below) |
| CP17 | This report |

Seed command: `python manage.py seed_strategy_knowledge` — one **knowledge-only,
draft, disabled** definition per registry key (74), 57 deterministic vision
pattern-label mappings, 19 structured conditions. Idempotent; ran successfully
against the dev SQLite database.

## Honesty guardrails (as built)

- **No fabricated accuracy.** No course claim (e.g. 80%/95%) is presented as
  verified anywhere. Detection metrics are labelled
  `metric_scope="pattern_detection"` with an explicit disclaimer that they are
  NOT prediction-accuracy, win-rate or profitability figures.
- **Pattern recognition is separate from next-candle prediction.** Recognition
  only records what was observed and how well it was verified; it never feeds
  the decision engine (which was not modified this phase).
- **Database content can never execute logic.** Rules are structured rows
  validated against whitelisted scalar schemas; `detector_key` only references
  the fixed registry.
- **Vision is never self-confirming.** A screenshot candidate is at best
  `possible` until a deterministic detector confirms it on verified OHLC
  candles; OTC screenshots are never confirmed with normal-session prices.
- **Experimental/unapproved definitions are always labelled** and can never be
  silently active (`is_active` requires enabled + reviewed/approved).
- **S/R touch alone is never a completed setup** — the lifecycle reports the
  furthest stage actually reached and marks unfinished setups in progress.

## Bug found and fixed by the new tests

`candle_sequences.failed_continuation` compared run direction against the
strings `"up"`/`"down"` while `Direction` values are `bullish`/`bearish`, so
the detector could never fire. Fixed to compare against `Direction.BULLISH` /
`Direction.BEARISH`. Also added the missing `ob.mitigation` registry detector
so all 74 `DETECTOR_KEYS` are registered (unknown-key inertness preserved).

## Test results

- New: `tests/test_phase12_detectors.py` (116 tests, traced fixtures) and
  `tests/test_phase12_knowledge.py` (33 tests: CP1, CP8–CP15).
- Full regression: `pytest tests -q` → **1025 passed, 3 skipped** (same 3
  pre-existing skips: 2 PostgreSQL-specific, 1 live-LLM opt-in). Baseline
  before Phase 12: 876 passed / 3 skipped.
- Gates: `ruff check` clean, `ruff format --check` clean, `manage.py check`
  clean, `makemigrations --check` → no pending changes.

## Not done / blocked (intentionally)

- **Live end-to-end persisted Gemini vision run**: blocked by free-tier quota
  (resets nightly ~00:52). The pipeline is fully covered by hermetic tests with
  static schema-valid payloads.
- **No production deployment** — awaiting explicit authorization.
- No seeded definition is enabled or approved; a human reviewer must approve
  and enable any definition before it can participate in recognition, and none
  of them can influence trade decisions regardless.
- No accuracy claim is made for any detector; the metrics service will report
  real numbers only once reviewer-labelled datasets exist.

## How to review

1. `python manage.py migrate && python manage.py seed_strategy_knowledge`
2. `python manage.py runserver` → `/dashboard/strategies/`
3. `pytest tests/test_phase12_detectors.py tests/test_phase12_knowledge.py -q`
