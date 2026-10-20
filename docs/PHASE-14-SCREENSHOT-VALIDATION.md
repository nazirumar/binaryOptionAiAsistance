# PHASE 14 — SCREENSHOT VALIDATION

Date: 2026-10-20. Status: COMPLETE — delivered for review. Nothing was deployed.

Phase 14 builds a **measured, real-screenshot evaluation workflow** on top of the
existing vision pipeline (`apps.chart_vision`, Phase 12) and the book-strategy
recognizers (`apps.book_strategies`, Phase 13). It rebuilds nothing. It owns a
new app, `apps.screenshot_eval`, whose only responsibility is honest evaluation:
a labelled screenshot dataset, a persisted recognition pass, chart annotations
that are only drawn when coordinates are reliable, immutable forward paper
predictions, outcome verification that never substitutes a feed, a review queue
and a two-scope metrics surface.

Two non-negotiable rules are encoded as code, not prose:

1. **No fabrication.** Screenshot evidence is qualitative. Candle OHLC prices and
   pixel coordinates are never invented from pixels. A recognition sourced only
   from a screenshot is capped at `AWAITING_CONFIRMATION` with
   `data_verification = SCREENSHOT_ONLY`, and every unrecognised requirement is
   listed as missing.
2. **Scope separation.** Recognition accuracy (did the system identify the
   pattern a human labelled?) and prediction accuracy (did verified outcomes
   move as predicted?) are different scopes and are never combined into a single
   figure.

## Checkpoint 0 — readiness audit (passed)

| Prerequisite | Evidence |
| --- | --- |
| Phase 13 complete | 32 catalogued strategies, 10 implemented detectors, HEAD `f61c4c5` pushed |
| Historical backtesting works | `BookBacktestService.run`; 11 persisted `BacktestRun` rows in the dev DB (kinds `book_strategy`, `book_comparison`) |
| Out-of-sample validation exists | `WalkForwardValidation.chronological_folds` (chronological, no leakage) |
| Ranking operational | `BookComparisonService.compare` (OOS margin, then sample size) |
| Approval mechanism | `BookStrategy.decision_use_approved` gate (0 approved — correctly OFF) |
| Screenshot vision | `apps.chart_vision`; dev has a live OpenAI vision provider configured; 2 real screenshots/analyses already stored |
| MT5 integration | `apps.market_sync` verification service |
| Existing tests | **1183 passed, 3 skipped** at `f61c4c5` (baseline before Phase 14 changes) |

No blockers. Implementation proceeded.

## Checkpoint 1 — real screenshot dataset

Model `ScreenshotCase` (`apps/screenshot_eval/models.py`) wraps an existing
`ChartScreenshot` and records everything a reproducible evaluation needs:

- instrument, timeframe, screenshot timestamp
- market type: `otc` / `regular` / `unknown` (never guessed)
- reviewer-assessed quality: `high` / `medium` / `low` / `unusable` / `unknown`
- visible candle count (as counted by the reviewer)
- human label: `case_kind` (`positive` / `negative` / `incomplete` /
  `unlabelled`), `expected_strategy_keys`, `expected_direction`
- `coordinates_reliable` flag (whether reliable pixel geometry is available)
- provenance: `source` (`user_upload` / `imported_directory` / `seeded` /
  `unknown`) plus a `provenance` JSON blob (file name + SHA-256, importer name)

Human review is explicit: `review_state` is `unreviewed` / `confirmed` /
`corrected` / `rejected`. **A case only counts as ground truth once a reviewer
confirms or corrects it** (`ScreenshotCase.is_labelled`). Corrections update the
human label only; they never touch stored predictions or recognitions.

`ScreenshotDatasetService.create_case` refuses to build a case over another
user's screenshot (`PermissionError`), closing an IDOR gap.

Import path: `python manage.py import_screenshot_cases --directory <dir>
--owner <user> [--instrument ... --timeframe ... --market-type ...
--kind ... --strategies SS1,SS2 --reviewed]`. Every file must decode as an
image; the SHA-256 of each file is recorded. **No synthetic or fabricated case
is ever seeded** — the dataset starts empty and stays honest, and metrics report
explicit insufficiency until genuine cases exist.

## Checkpoint 2 — strategy recognition

`ScreenshotRecognitionService.run` orchestrates the existing machinery; it does
not re-implement any pattern logic:

- `build_book_candidates(analysis)` maps the analysis' persisted vision records
  through the fixed `VISION_BOOK_MAP` table (e.g. a `bullish_engulfing`
  observation seeds SS4). Unmapped labels produce nothing — no fuzzy guessing.
- When compatible OHLC is supplied (`--symbol`/`--timeframe` on
  `run_screenshot_recognition`, sourced from complete `quality_status="ok"` MT5
  candles), `BookStrategyRecognizer.evaluate` runs the deterministic state
  machine for every implemented detector.

Every result is persisted as a `ScreenshotRecognition` row carrying exactly what
the checkpoint asks for:

| Field | Meaning |
| --- | --- |
| `strategy_id`, `strategy_key`, `strategy_name`, `book_number` | strategy identity |
| `recognition_state` | `FORMING` / `AWAITING_CONFIRMATION` / `CONFIRMED_PATTERN` / `INVALIDATED` / `INSUFFICIENT_DATA` |
| `observed_evidence` | visible evidence (qualitative) |
| `missing_conditions` | unmet book requirements |
| `invalidation_evidence` | records that invalidate the setup |
| `contradictions` | recorded contradictions |
| `data_verification` | `SCREENSHOT_ONLY` / `MT5_VERIFIED` / `INCOMPATIBLE_FEEDS` / `NOT_EVALUATED` |
| `decision`, `probability`, `probability_status` | always `NO_TRADE`, `None`, `UNAVAILABLE_UNCALIBRATED` |

A screenshot-only recognition can never reach `CONFIRMED_PATTERN` and never
carries a `reference_level`: there is no OHLC to confirm against. This is
asserted by test.

### Requested recognition coverage

The checkpoint lists specific pattern families. Mapping to this catalog:

| Checkpoint pattern | Catalog entry | Detector |
| --- | --- | --- |
| Magic V | SS2 (seed) / SS3 (advanced) | implemented |
| Four-candle body breakout | SS6 | implemented |
| Five-candle reference breakout | SS21 | implemented |
| Doji-level breakout | SS19 | implemented |
| Rising Three Method | SS22 | implemented |
| Falling Three Method | SS23 | implemented |
| Trend pullback continuation | SS5 (four-candle pullback hold) | implemented |
| EMA 5 + Parabolic SAR + Stochastic alignment | CH7_S1 | implemented |

## Checkpoint 3 — chart annotations

`AnnotationService.annotate` writes `ChartAnnotation` rows and follows a strict
honesty ladder:

- `available` — a reviewer (or a reliable geometry step) supplied relative
  coordinates `[x0, y0, x1, y1]` in the 0..1 range **and** the case marks
  `coordinates_reliable`. Coordinates are trusted verbatim.
- `qualitative` — the case coordinates are reliable but this specific element
  has no verified geometry: the label is kept, no box is invented.
- `skipped` — the case's coordinates are unreliable (`COORDINATES_UNRELIABLE`):
  nothing is drawn.

Invalid geometry (out of range, inverted rectangle) is downgraded to
`qualitative`, never drawn. The original screenshot bytes are never modified
(asserted by test). The vision model returns qualitative descriptions and
relative candle positions — never pixel geometry — so no coordinate is ever
synthesised.

## Reproducibility

The recognition run, its per-strategy rows, the annotations, the predictions and
the outcomes are all persisted; dashboard pages read persisted rows only and
never recompute. `screenshot_forward_report` reproduces the metric payload as
JSON.

## What this checkpoint does NOT claim

- No real IQ Option screenshot dataset is shipped. The ingestion path is
  complete and tested hermetically; the dataset is empty until genuine
  screenshots are supplied. Every metric reports `INSUFFICIENT_LABELLED_CASES`
  / `NOT_COMPUTABLE_NO_GROUND_TRUTH` until then.
- Recognition accuracy is `None` until a human-labelled ground-truth set exists.
  It is never estimated from outcomes.

See `docs/PHASE-14-FORWARD-TESTING.md`,
`docs/PHASE-14-ERROR-REVIEW.md` and `docs/PHASE-14-COMPLETION-REPORT.md`.
