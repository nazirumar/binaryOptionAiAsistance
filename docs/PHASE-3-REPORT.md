# Phase 3 Report — AI Screenshot Vision & Candlestick Recognition

**Status: implementation complete and verified with a mocked vision provider.**
**A live round trip to a real hosted vision model is PENDING** (no provider API key
was available in this environment). Per the phase rules, this is **not** claimed as
live-verified.

---

## 1. What was delivered

A new Django app, **`apps.chart_vision`** (label `chart_vision`), plus REST API,
dashboard and documentation integration. Phase 1 and Phase 2 behaviour and styling
were preserved.

### Domain / service layer (`apps/chart_vision/services/`)
| Module | Responsibility |
| ------ | -------------- |
| `exceptions.py` | `ChartVisionError` hierarchy (`ImageValidationError` subtypes, `VisionProviderError`, `VisionRateLimitError`, `VisionTimeoutError`, `VisionResponseError`, `SchemaValidationError`) with `code`/`retryable` |
| `dto.py` | Immutable `ProviderConfig`, `ProviderResult`, `ProviderUsage`, `ImageInfo`, validation DTOs |
| `image_validator.py` | Format allow-list, size/dimension/pixel limits, MIME + magic-byte signature checks, safe Pillow decode, corrupted-image rejection |
| `image_preprocessor.py` | EXIF-orientation correction, RGB conversion, bounded downscale for the provider; **pixel values are never turned into prices** |
| `vision_provider.py` | `VisionProvider` ABC, `MockVisionProvider`, `OpenAICompatibleVisionProvider` (stdlib `urllib`, base64 data-URI image), `get_vision_provider`, `build_mock_payload` |
| `schema_validator.py` | Strict versioned v1 validation, JSON extraction, normalisation, forbidden probability/prediction rejection, numeric-price stripping |
| `candle_extractor.py` | Left→right candle observations, body/wick relative sizes, approximate pixel coordinates, completeness/ambiguity |
| `chart_metadata.py` | Instrument/timeframe/platform/axis/OTC extraction; `UNKNOWN` when unreadable |
| `pattern_observer.py` | Structure, swing points, S/R zones, candlestick patterns, advanced-course concepts (sequences, lonely candles, psychological sequences, motive/counter/last-effort waves, sweeps, order blocks, FVG, gaps, relative volume) |
| `screenshot_analyzer.py` | End-to-end pipeline: read → preprocess → provider (retry/backoff) → validate → post-process → persist + events |
| `events.py` | Structured `VisionProcessingEvent` audit trail helper |
| `upload.py` | Shared upload validation/ownership/retention used by API **and** dashboard |

### Data model (`apps/chart_vision/models.py`)
`ChartScreenshot`, `ScreenshotAnalysis`, `VisionObservation`, `DetectedPattern`,
`DetectedPriceZone`, `VisionProcessingEvent`.

- The full validated structured payload is stored **once** on
  `ScreenshotAnalysis.result`. Derived rows (`VisionObservation`, `DetectedPattern`,
  `DetectedPriceZone`) hold compact, queryable summaries plus evidence *references*.
- `ScreenshotAnalysis.idempotency_key` is unique
  (`analyze:<screenshot_id>:<prompt_version>:<schema_version>`), preventing
  uncontrolled duplicate jobs.
- Screenshot bytes live in private storage; `url()` raises so records can never be
  served from a public media URL.

### Structured output (versioned)
- `SCHEMA_VERSION = "1.0"`, `PROMPT_VERSION = "v1"`
  (`apps/chart_vision/prompts/chart_analysis_v1.md`).
- Sections: chart metadata, candles, market structure, support/resistance zones,
  candlestick patterns, candle sequences, market cycle, liquidity, relative volume,
  observation confidence, missing information, warnings and analysis status.
- Unknown enum values are coerced to `unknown` with a warning; a **schema-version
  mismatch** or **missing required section** fails validation.
- Forbidden probability / win-rate / prediction keys are hard-rejected; numeric
  candle price keys are stripped with a warning (no fabricated OHLC).

### API (`/api/vision/`, all `IsAuthenticated` + owner-scoped)
| Method | Path | Notes |
| ------ | ---- | ----- |
| POST | `screenshots/` | multipart upload; `?analyze=true` queues analysis |
| GET | `screenshots/` | list the caller's screenshots |
| GET | `screenshots/{id}/` | screenshot detail |
| GET | `screenshots/{id}/image/` | private byte stream (owner only) |
| POST | `screenshots/{id}/analyze/` | idempotent start/reuse/re-queue |
| GET | `analyses/{id}/` | full structured result + derived rows |
| GET | `analyses/{id}/events/` | processing-event trail |
| GET | `history/` | paginated history, `?status=` filter |
| GET | `status/{id}/` | lightweight status for polling |

Throttling uses `ScopedRateThrottle` (`vision_upload`, `vision_read`).

### Background processing & UI
- Celery tasks `chart_vision.analyze_screenshot` and `chart_vision.purge_screenshots`.
- Dashboard `/dashboard/vision/` (upload, preview, start analysis, live status,
  metadata, patterns/structure, confidence/warnings, history) and a detail page,
  both showing the required disclaimer:
  > Vision observations only — MT5 comparison and final strategy evaluation are not yet available.

---

## 2. Verification results

Environment: Windows, Python 3.13.14, `Pillow==12.3.0`, `numpy==2.5.4`.

| Check | Command | Result |
| ----- | ------- | ------ |
| Django checks | `manage.py check` | ✅ no issues |
| Migrations | `manage.py makemigrations --check --dry-run` | ✅ no changes detected |
| Applied migration | `manage.py showmigrations chart_vision` | ✅ `[X] 0001_initial` |
| Lint | `ruff check .` | ✅ all checks passed |
| Format | `ruff format --check .` | ✅ all files formatted |
| Tests | `pytest -q --cov` | ✅ **256 passed, 2 skipped** (88% coverage) |

The 2 skips remain the PostgreSQL-specific market-data constraint tests.

Migration created and applied: `apps/chart_vision/migrations/0001_initial.py`.

> Note: the benign `django-environ` "Engine not recognized from url" warning for the
> intentionally-empty local `DATABASE_URL` is pre-existing and harmless.

---

## 3. Acceptance criteria

| # | Criterion | Status |
| - | --------- | ------ |
| 1 | Screenshot upload secured (type/size/dimension/signature/corruption) | ✅ verified |
| 2 | Private, owner-scoped storage; no public URL | ✅ verified |
| 3 | Configurable provider; no hardcoded credentials | ✅ verified |
| 4 | Timeouts, bounded retries, rate-limit handling | ✅ verified |
| 5 | Structured response validation; no fabricated results on failure | ✅ verified |
| 6 | Token usage, model id and prompt version tracked | ✅ verified |
| 7 | Metadata `UNKNOWN` when unreadable; never guess symbol/timeframe | ✅ verified |
| 8 | OTC vs regular never substituted | ✅ verified |
| 9 | Left→right candles, relative sizes, pixel coords, ambiguity | ✅ verified |
| 10 | No OHLC prices invented from pixels | ✅ verified |
| 11 | Structure, zones, patterns, advanced concepts with confirmed/uncertain | ✅ verified |
| 12 | Versioned strict schema with evidence + missing info + warnings | ✅ verified |
| 13 | Observation confidence separate from probability; no fabricated probabilities | ✅ verified |
| 14 | Idempotent, non-duplicating background processing | ✅ verified |
| 15 | Dashboard with the required disclaimer | ✅ verified |
| 16 | Tests pass | ✅ 256 passed |
| 17 | Ruff passes | ✅ |
| 18 | Docs updated | ✅ |

---

## 4. Tests added (140 → 256 total; **116 new cases**)

`tests/vision_fakes.py` (image builders, `StaticVisionProvider`, payload factories)
plus:

- `test_chart_vision_images.py` (17) — format/signature/size/dimension/corruption/decode + preprocessor.
- `test_chart_vision_schema.py` (22) — required keys, version, normalisation, forbidden probability/prices.
- `test_chart_vision_analysis.py` (21) — metadata, rightmost candle, quality, failures, idempotency, advanced concepts, zones.
- `test_chart_vision_api.py` (21) — auth, upload errors, dedupe, owner isolation, private streaming, history, status.
- `test_chart_vision_tasks.py` (9) — success, idempotency, retry/non-retry, missing row, retention purge.
- `test_chart_vision_provider.py` (17) — factory, HTTP success, 401/429/5xx mapping, timeout, invalid body, analyzer retry loop.
- `test_chart_vision_dashboard.py` (9) — auth, upload, disclaimer, owner isolation.

The standard suite requires **no** provider key and **no** network: the provider is
`mock` in tests, and `StaticVisionProvider` / `urllib` are patched where needed.

---

## 5. Known limitations / follow-ups

1. **Live vision-provider verification is pending.** With a key set:
   ```powershell
   $env:VISION_LLM_PROVIDER="openai"; $env:VISION_LLM_MODEL="<model>"; $env:VISION_LLM_API_KEY="<key>"
   python manage.py runserver        # then upload a real screenshot in /dashboard/vision/
   ```
   The HTTP client layer, error mapping and retry logic are unit-tested against a
   fake transport; a real end-to-end call is not exercised here.
2. Screenshot analysis is intentionally **observation-only**. MT5 cross-comparison,
   strategy scoring and probability calibration belong to later phases and are **not**
   implemented; the UI states this explicitly.
3. EXIF orientation is corrected; unusual colour profiles are converted to RGB for
   the provider.

## 6. Security & integrity notes

- Screenshots are stored privately and streamed only through an authenticated,
  owner-checked endpoint; `PrivateScreenshotStorage.url()` raises.
- Uploads pass MIME + magic-byte checks; Pillow decodes with the decompression-bomb
  guard and explicit pixel limits.
- Provider credentials come from the environment only; nothing secret is persisted
  or logged.
- The schema validator refuses fabricated probabilities and strips numeric candle
  prices; the rightmost candle is always flagged potentially incomplete.
- **Analysis-only:** no trade/order execution exists anywhere in this layer.
