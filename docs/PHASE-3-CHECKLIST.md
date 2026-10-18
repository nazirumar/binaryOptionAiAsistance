# Phase 3 Checklist — AI Screenshot Vision & Candlestick Recognition

Legend: ✅ done & verified · ⚠️ partial / documented limitation · ⬜ out of scope

## Step 1 — Audit
- ✅ Inspected existing structure (settings split, apps, DRF conventions, error envelope, pagination)
- ✅ Ran the Phase 1 + 2 suite before starting (140 passed, 2 skipped)
- ✅ Confirmed no prior screenshot/AI-provider abstraction existed
- ✅ Confirmed available imaging dependencies: `Pillow 12.3.0`, `numpy 2.5.4`
- ✅ Chose stdlib `urllib` for the vision HTTP client (matches the Phase 2 `remote_ingest` pattern; no new runtime dependency)
- ✅ Preserved all Phase 1 and Phase 2 functionality and styling

## Step 2 — Vision application
- ✅ `apps.chart_vision` created with `models`, `serializers`, `views`, `urls`, `admin`,
  `dashboard`, `tasks`, `permissions`, `constants`, `storage`, `prompts/` and `services/`
- ✅ Service modules: `image_validator`, `image_preprocessor`, `vision_provider`,
  `schema_validator`, `candle_extractor`, `chart_metadata`, `pattern_observer`,
  `screenshot_analyzer`, `events`, `upload`, `dto`, `exceptions`

## Step 3 — Secure screenshot upload
- ✅ Accepted formats: PNG, JPEG, WebP only
- ✅ Enforced maximum byte size, minimum/maximum width/height and maximum pixel count
- ✅ MIME type **and** file-signature (magic-byte) verification
- ✅ Safe decoding via Pillow with the decompression-bomb guard enabled
- ✅ Corrupted/truncated images rejected with a structured error code
- ✅ Per-user ownership on every record; never shared across accounts
- ✅ Private storage (`PrivateScreenshotStorage`); `url()` raises — no public media URL
- ✅ Bounded retention (`VISION_SCREENSHOT_RETENTION_DAYS`) + purge task

## Step 4 — Configurable vision provider
- ✅ Env-driven selection: `VISION_LLM_PROVIDER` (`mock`/`openai`/`custom`), `VISION_LLM_MODEL`, `VISION_LLM_API_KEY`, `VISION_LLM_BASE_URL`
- ✅ No hardcoded credentials; nothing secret stored in the database or logs
- ✅ Request timeout, bounded retries and exponential backoff
- ✅ Rate-limit handling honouring `Retry-After`
- ✅ Non-retryable errors (401/403/misconfiguration) are surfaced, not retried
- ✅ Structured response validation; token-usage logging; model identification; prompt-version tracking
- ✅ Provider failure never fabricates a result (the stored `result` stays empty)
- ✅ `mock` provider default so development/tests need no key or network

## Step 5 — Chart metadata extraction
- ✅ Instrument/symbol, timeframe, platform, visible axis labels, OTC status
- ✅ Unreadable values reported as `UNKNOWN` — never guessed
- ✅ Symbol/timeframe never inferred when not visible
- ✅ OTC vs regular never substituted (`otc_status` coerced to `unknown`, never `regular`)

## Step 6 — Candlestick recognition
- ✅ Candles classified left → right
- ✅ Body/wick direction and relative body/wick sizes
- ✅ Approximate pixel coordinates (`high_px`, `low_px`, `open_px`, `close_px`, `body_px`)
- ✅ Completeness flag; rightmost candle **always** treated as potentially incomplete
- ✅ Per-candle confidence and an explicit ambiguity note
- ✅ **No OHLC prices fabricated from pixels** (numeric price fields stripped with a warning)

## Step 7 — Market structure, zones & patterns
- ✅ Market structure: trend, swing highs/lows, break-of-structure, ranges, consolidation
- ✅ Support/resistance zones with repeats, breaks and support↔resistance flips
- ✅ Candlestick patterns (engulfing, pin bar, doji, inside/outside bar, …)
- ✅ Advanced course concepts: candle sequences, lonely candles, eight psychological
  sequences, motive/counter/last-effort waves, liquidity sweeps, order blocks, FVG,
  gaps, relative volume
- ✅ Each item marked confirmed vs. uncertain; `insufficient_evidence` where undeterminable

## Step 8 — Versioned structured output
- ✅ `SCHEMA_VERSION = "1.0"`, `PROMPT_VERSION = "v1"` (`apps/chart_vision/prompts/chart_analysis_v1.md`)
- ✅ Strict schema: metadata, candles, structure, zones, patterns, sequences, cycle,
  liquidity, volume, observation confidence, missing information, warnings, analysis status
- ✅ Every observation cites evidence / candle references
- ✅ Observation confidence is separated from any trading probability
- ✅ **No fabricated UP/DOWN or win-rate probabilities** (forbidden keys hard-rejected)

## Step 9 — Database models
- ✅ `ChartScreenshot`, `ScreenshotAnalysis`, `VisionObservation`, `DetectedPattern`,
  `DetectedPriceZone`, `VisionProcessingEvent`
- ✅ Large payload stored **once** on `ScreenshotAnalysis.result`; derived rows hold compact evidence *references*
- ✅ Unique `idempotency_key` on analyses; indexes on owner/status/time
- ✅ Migration `0001_initial` created and applied

## Step 10 — Secure API
- ✅ `POST /api/vision/screenshots/` (upload; optional `?analyze=true`)
- ✅ `GET  /api/vision/screenshots/{id}/` and `GET .../{id}/image/` (owner-only byte stream)
- ✅ `POST /api/vision/screenshots/{id}/analyze/` (idempotent, deduplicated)
- ✅ `GET  /api/vision/analyses/{id}/`, `GET /api/vision/analyses/{id}/events/`
- ✅ `GET  /api/vision/history/`, `GET /api/vision/status/{id}/`
- ✅ `IsAuthenticated` + per-user scoping; `ScopedRateThrottle` (`vision_upload`, `vision_read`)

## Step 11 — Background processing
- ✅ Celery task `chart_vision.analyze_screenshot` (`analyze_screenshot_task`)
- ✅ queued → running → success/failure statuses
- ✅ Bounded retries with backoff; rate-limit aware
- ✅ Idempotent: repeated analyse requests reuse the same row and never create duplicate jobs
- ✅ Structured error logging (request-correlated)
- ✅ Retention task `chart_vision.purge_screenshots`

## Step 12 — Dashboard
- ✅ `/dashboard/vision/`: upload, preview, start analysis, live status, metadata,
  patterns/structure, confidence/warnings and history
- ✅ Detail page shows the private preview, structured observations and the disclaimer
- ✅ Displays: **“Vision observations only — MT5 comparison and final strategy evaluation are not yet available.”**
- ✅ Uses the existing Tailwind/HTMX stack; unrelated pages unchanged

## Step 13 — Testing
- ✅ Image validation/preprocessing (formats, signature, size, dimensions, corruption, decode)
- ✅ Schema validator (required keys, version, normalization, forbidden probability/prices)
- ✅ Analysis pipeline (metadata, rightmost candle, quality, failures, idempotency, advanced concepts)
- ✅ API (auth, upload errors, dedupe, owner isolation, private streaming, history, status)
- ✅ Tasks (success, idempotency, retry/non-retry, retention purge)
- ✅ Provider (factory, HTTP success, 401/429/5xx mapping, timeout, invalid body, retry loop)
- ✅ Dashboard (auth, upload, disclaimer, owner isolation)
- ✅ Vision provider fully mocked in the standard suite — no key, no network required
- ⚠️ No real vision-provider API key was available → **live provider round trip is PENDING**

## Step 14 — Documentation
- ✅ `docs/CHART-VISION.md` (config, API, dashboard, security, troubleshooting)
- ✅ `docs/PHASE-3-CHECKLIST.md`, `docs/PHASE-3-REPORT.md`
- ✅ README, ARCHITECTURE and `.env.example` updated

## Phase 3 acceptance criteria
1. ✅ Secure screenshot ingestion with ownership + private storage
2. ✅ Configurable, credential-safe vision provider with retries/rate-limit handling
3. ✅ Chart metadata extraction that reports `UNKNOWN` rather than guessing
4. ✅ Left-to-right candlestick recognition, never fabricating prices
5. ✅ Structure, zones, patterns and advanced concepts marked confirmed/uncertain
6. ✅ Versioned strict structured output with evidence and honest caveats
7. ✅ No fabricated probabilities and no final trading predictions
8. ✅ Authenticated, owner-scoped API + idempotent background processing
9. ✅ Vision dashboard with the required disclaimer
10. ✅ Tests pass and Ruff passes
11. ✅ Documentation updated
