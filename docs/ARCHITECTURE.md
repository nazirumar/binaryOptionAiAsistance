# Architecture

This document describes the intended architecture. Phase 1 delivers the foundation
shaded below; later phases add the remaining apps.

## Layered design

```
┌──────────────────────────────────────────────────────────────┐
│ Presentation      Django templates + HTMX + Tailwind          │
│                   DRF JSON API (apps.api)                     │
├──────────────────────────────────────────────────────────────┤
│ Application       views, serializers, tasks, consumers        │
├──────────────────────────────────────────────────────────────┤
│ Domain            price-action knowledge engine, strategies,  │
│                   probability/calibration (phases 5–7)        │
├──────────────────────────────────────────────────────────────┤
│ Integration       AI providers (vision/reasoning), MT5 client │
│                   screenshot vision, symbol mapping           │
├──────────────────────────────────────────────────────────────┤
│ Infrastructure    core models/logging, config, DB, Celery,    │
│                   Channels, Redis, health checks              │
└──────────────────────────────────────────────────────────────┘
```

## Apps

| App | Phase | Responsibility |
| --- | ----- | -------------- |
| `apps.core` | 1 | Abstract base models, structured logging, request-id middleware, health views, system checks, shared tasks |
| `apps.accounts` | 1 | Custom `User` model, login/logout/sign-up |
| `apps.dashboard` | 1 | Authenticated HTMX/Tailwind UI shell and roadmap |
| `apps.api` | 1 | DRF configuration, health + current-user endpoints, pagination, error envelope |
| `apps.market_data` | 2 | MT5 connection manager, symbol/timeframe mapping, OHLC/tick retrieval + validation, idempotent storage, Windows worker, feed health API |
| `apps.chart_vision` | 3 | Secure screenshot uploads, configurable vision provider, versioned structured observations (metadata, candles, structure, zones, patterns), audit trail |
| `apps.market_sync` | 4 | Screenshot-vs-MT5 verification: instrument/timeframe matching, timestamp alignment, candle/structure/price comparison, feed compatibility (OTC), freshness, 7-query outcome statuses, audit trail |
| `apps.price_action` | 5 | Deterministic price-action knowledge engine: market structure, support/resistance, candlesticks, sequences, cycle, liquidity sweeps, order blocks, FVG, gaps, volume, market context; evidence registry + conflict detection; versioned, machine-readable output |
| `apps.analysis` | 6–7 | Strategy evaluation, scoring and dataset collection |
| `apps.probability` | 7 | Dataset collection, calibration, reliability, NO-TRADE policy |
| `apps.assistant` | 8 | Reasoning LLM orchestration and explanation generation |
| `apps.analytics` | 9 | Dashboards, history, outcome tracking |

## Market-data integration (phase 2)

The MetaTrader 5 Python package is Windows-only, so it is **never imported by the
web tier**. A dedicated worker (or a Celery task on a Windows host) owns the
terminal connection and either writes to the shared database or pushes data to
the server over an authenticated API.

```
Windows worker (MetaTrader5)                Web / API tier
  MT5 terminal                                /api/market/*  (IsAuthenticated)
      │  ConnectionManager (retry/backoff)          ▲
      │  CandleService / TickService                │  worker ingest (X-Worker-Token)
      │  DataValidator (never fabricate)            │
      ▼                                             │
  MarketDataSyncService ── persist ──▶ MarketCandle / MarketTick ──▶ dashboard
      │                                   MarketDataSyncLog
      └── record ──▶ MarketDataHealthEvent ─┘  WorkerHeartbeat ──▶ health API
```

Key rules enforced by the domain layer:

- A candle is **never assumed complete**: completeness is derived from its open
  time, timeframe duration, current UTC time and a feed-delay allowance.
- Source values are stored verbatim; gaps are reported, never interpolated.
- Ingestion is **idempotent** on `(symbol, timeframe, open_time)` for candles and
  `(symbol, time, source)` for ticks.
- OTC and regular feeds are explicitly non-interchangeable (`OTC_MISMATCH`).
- Passwords are never stored or logged; profiles hold a secret *reference* only.
- No order-execution capability exists anywhere in this layer.

## Screenshot vision (phase 3)

A screenshot is validated (format, size, dimensions, signature, decodability),
stored privately and analysed by a **configurable** vision provider. The raw model
response is validated against a strict, versioned schema before anything is stored.

```
Browser ──upload──▶ /api/vision/screenshots/ ──▶ ImageValidator ──▶ ChartScreenshot
                                                        │            (private storage)
                                                        ▼
                                              ScreenshotAnalyzer ──▶ VisionProvider
                                                        │            (mock / openai / custom)
                                                        ▼
                                              SchemaValidator (v1.0)  ── reject/rewrite
                                                        │
                                                        ▼
                                  ScreenshotAnalysis.result (stored once)
                                        └── VisionObservation / DetectedPattern /
                                            DetectedPriceZone (compact evidence refs)
                                        └── VisionProcessingEvent (audit trail)
```

Key rules enforced by the domain layer:

- Screenshot bytes are **never** served from a public media URL; `url()` raises and
  images are streamed only through an authenticated, owner-checked endpoint.
- Unreadable metadata becomes `UNKNOWN`; symbol/timeframe are never guessed and
  OTC vs. regular is never substituted.
- Numeric candle OHLC prices are stripped; probabilities/predictions are rejected.
- The rightmost candle is always treated as potentially incomplete.
- Analyses are **idempotent** on `(screenshot, prompt_version, schema_version)`.
- A provider failure never produces a fabricated result.
- No trade execution exists anywhere in this layer.

## Market synchronization (phase 4)

`apps.market_sync` compares the **stored** Phase 3 analysis with **stored** Phase 2
candles. It is synchronous and DB-only (no MT5 terminal on the web tier), and it
never mutates the screenshot observations.

```
ScreenshotAnalysis.result ─┐
                           ├─▶ SynchronizationService.verify()
MarketCandle (stored MT5) ─┘        │
                                    ├─ InstrumentMatcher   (explicit broker mappings; OTC aware)
                                    ├─ TimeframeMatcher    (never assumes a missing timeframe)
                                    ├─ TimestampAligner    (anchor from chart/user/capture time)
                                    ├─ CandleComparator    (direction, body/wick ratios, size bands)
                                    ├─ StructureComparator (HH/HL/LH/LL, swings, trend)
                                    ├─ PriceLevelComparator(axis labels or relative structure)
                                    ├─ FeedCompatibility   (OTC protection, mapping verification)
                                    └─ FreshnessValidator  (screenshot + MT5 age, entry window)
                                    │
                                    ▼
                         MarketSyncSession.outcome (7 statuses)
                         CandleAlignment / FeedCompatibilityAssessment /
                         MarketSyncIssue / SynchronizationAuditLog
```

Key rules enforced by the domain layer:

- Instrument equivalence is **never** inferred from similar names; only explicit,
  validated broker-symbol mappings are used, and ambiguity is rejected.
- An OTC screenshot is **never** verified against a regular forex feed — that is
  `INCOMPATIBLE_FEED` unless a dedicated, verified OTC reference is mapped.
- A missing/uncertain timeframe or timestamp is never assumed; the run is marked
  unverified (`INSUFFICIENT_INFORMATION`) instead.
- Only reliably **completed** candles are compared; the rightmost candle is always
  excluded. Broker feed differences are expected, not errors.
- Only `VERIFIED_ALIGNMENT` counts as a successful dual-source verification; a
  `PARTIAL_ALIGNMENT` is never presented as fully verified.
- Results are **idempotent** on a per-user idempotency key; a duplicate request
  returns the existing session.

## Price-action engine (phase 5)

`apps.price_action` turns a candle series into **evidence**, not a verdict. Detectors are
pure, deterministic functions over plain candle dicts; `PriceActionEngine.run()` normalises
the input, evaluates the concepts and returns a versioned, machine-readable document.

```
MarketInput / candle list ─▶ SchemaValidator (market_input v1.0)
                                   │
                                   ▼
                            PriceActionEngine.run()
                                   ├─ candle math + strength
                                   ├─ market_structure   (swings, trend, BOS, consolidation)
                                   ├─ support_resistance (zones, rejection, breakout/retest, SBR/RBS)
                                   ├─ buyer_seller_failure
                                   ├─ candlestick_patterns / candle_sequences
                                   ├─ market_cycle
                                   ├─ liquidity_sweeps / order_blocks / fair_value_gaps / opening_gaps
                                   ├─ volume_analysis
                                   └─ market_context     (session, regime, volatility, news, freshness)
                                   │
                                   ▼
                    EvidenceRegistry (append-only) ─▶ ConflictDetector
                                   │
                                   ▼
                 {schema_version, evidence, conflicts, context, summary}
                 knowledge/catalogue.py (versioned concept documentation)
```

Key rules enforced by the engine:

- **No look-ahead.** Only completed candles are evaluated; the incomplete/rightmost
  candle is excluded and evidence refs never exceed the series.
- **No verdict.** The output contains observations and conflicts only — never a
  next-candle prediction, a trading probability or an UP/DOWN recommendation.
- **Contradictions are preserved.** Opposing evidence is reported as a `ConflictRecord`
  with a severity and is never resolved by a probability.
- **Missing means missing.** Insufficient history or unreadable inputs yield
  `insufficient`/`unknown` evidence instead of a guess.
- **Ambiguity stays explicit.** Two competing order-block definitions are kept separate
  and never merged; the course ambiguity is documented in the catalogue.
- Detectors are deterministic: identical input produces identical output.
- No order-execution capability exists anywhere in this layer.

## Configuration strategy

Settings are split into `base`/`dev`/`test`/`prod` modules. `base` holds everything
common and reads all environment-specific values through `django-environ`. `prod`
applies hardening and fails fast on missing secrets. `test` is hermetic (in-memory
SQLite, eager Celery, in-memory channel layer, cheap hashers).

## Data-integrity model (phases 3–4)

The comparison between an uploaded screenshot and the MT5 feed produces an explicit
verification state (Step 12):

- `VERIFIED_ALIGNMENT` — aligned completed candles, strong direction agreement,
  agreeing structure, a compatible + fresh feed and a validated instrument mapping.
  This is the **only** successful dual-source verification.
- `PARTIAL_ALIGNMENT` — the sources broadly agree but not enough to verify; it is
  never described as fully verified.
- `DATA_MISMATCH` — enough candles overlap, but the sources disagree.
- `INCOMPATIBLE_FEED` — the feeds are not interchangeable (e.g. OTC vs. regular).
- `STALE_DATA` — the screenshot or the MT5 reference is outside its freshness window.
- `INSUFFICIENT_INFORMATION` — a required input (symbol/timeframe/anchor) is missing
  or too few completed candles overlap.
- `MT5_UNAVAILABLE` — no stored MT5 reference series exists.

Only `VERIFIED_ALIGNMENT` may support a downstream hypothesis, and even then the match
validates **data consistency, not future price direction**.

## Probability policy (phase 7)

No probability is ever fabricated. The engine collects timestamped examples and actual
outcomes, splits them chronologically (train/validation/test) to prevent leakage,
calibrates, measures reliability, records sample size, and compares against baselines.
Until that exists the UI displays:

> Probability unavailable — model not calibrated.

## Security posture

- Custom user model defined from the first migration.
- Session + token authentication; DRF defaults to `IsAuthenticated`.
- Secure upload handling with strict size limits and private, owner-scoped storage (Phase 3).
- Owner-scoped, rate-limited synchronization API: per-user idempotency keys and a
  strict ownership check on every session read (Phase 4).
- The Phase 5 engine is pure and deterministic with no public endpoints yet; it accepts
  caller-supplied candles and executes no trades.
- CSRF protection preserved for HTMX; secure cookies and HSTS in production.
- Structured, request-correlated logging; no secrets or market payloads in logs.
