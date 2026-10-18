# Chart Vision — Screenshot Analysis (Phase 3)

This document explains how to configure, run and operate the Phase 3 screenshot
vision pipeline in `apps.chart_vision`.

> **Analysis only.** The pipeline produces *visual observations* from an uploaded
> chart image. It does **not** compare against MT5, score a strategy, estimate a
> probability, or place any trade. The UI states this explicitly:
>
> *“Vision observations only — MT5 comparison and final strategy evaluation are not yet available.”*

---

## 1. What it does

1. **Upload** a candlestick-chart screenshot (PNG / JPEG / WebP).
2. The image is **validated** (type, size, dimensions, signature, decodability) and
   stored in **private** storage, owned by the uploading user.
3. A **configurable vision provider** receives the image plus a versioned prompt
   (`prompts/chart_analysis_v1.md`) and returns a structured JSON analysis.
4. The JSON is validated against the **strict versioned schema** (`v1.0`); anything
   fabricated (probabilities, invented OHLC prices) is rejected or stripped.
5. The validated result is stored once and summarised into queryable observation,
   pattern and price-zone rows, with an audit trail of processing events.

---

## 2. Configuration

All settings are environment-driven (see `.env.example`).

### Provider

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `VISION_LLM_PROVIDER` | `mock` | `mock`, `openai` or `custom` |
| `VISION_LLM_MODEL` | *(empty)* | Model identifier (required for `openai`/`custom`) |
| `VISION_LLM_API_KEY` | *(empty)* | Bearer token (required for `openai`/`custom`) |
| `VISION_LLM_BASE_URL` | *(empty)* | Base URL; defaults to `https://api.openai.com/v1` |
| `VISION_LLM_TIMEOUT_SECONDS` | `60` | Per-request timeout |
| `VISION_LLM_MAX_RETRIES` | `2` | Bounded retries for transient errors |
| `VISION_LLM_BACKOFF_SECONDS` | `1.5` | Base exponential-backoff delay |
| `VISION_LLM_MAX_TOKENS` | `2048` | Response token cap |
| `VISION_LLM_TEMPERATURE` | `0.0` | Sampling temperature |

- **`mock`** returns a deterministic, clearly-labelled illustrative payload. Use it
  for local development and tests — **no key and no network required**.
- **`openai` / `custom`** speak the OpenAI-compatible `/chat/completions` wire
  protocol with the image sent as a base64 data URI. `custom` is the same code path
  with an explicit `VISION_LLM_BASE_URL`.

Example (OpenAI-compatible):

```powershell
$env:VISION_LLM_PROVIDER="openai"
$env:VISION_LLM_MODEL="gpt-4o-mini"
$env:VISION_LLM_API_KEY="sk-..."
```

Secrets are read from the environment only and are **never** stored in the database
or written to logs.

### Upload limits & retention

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `VISION_MAX_UPLOAD_BYTES` | `8388608` (8 MiB) | Maximum upload size |
| `VISION_MIN_WIDTH` / `VISION_MIN_HEIGHT` | `200` / `100` | Minimum dimensions |
| `VISION_MAX_WIDTH` / `VISION_MAX_HEIGHT` | `8000` / `8000` | Maximum dimensions |
| `VISION_MAX_PIXELS` | `40000000` | Decompression-bomb / pixel guard |
| `VISION_PREPROCESS_MAX_DIMENSION` | `2000` | Downscale longest edge before sending |
| `VISION_SCREENSHOT_ROOT` | `<BASE_DIR>/private_media/screenshots` | Private storage root |
| `VISION_SCREENSHOT_RETENTION_DAYS` | `30` | Retention window for the purge task |
| `VISION_ANALYSIS_MAX_ATTEMPTS` | `3` | Bounded analysis attempts |

### Throttling

| Variable | Default |
| -------- | ------- |
| `VISION_UPLOAD_THROTTLE` | `30/minute` |
| `VISION_READ_THROTTLE` | `240/minute` |

---

## 3. API

All endpoints are mounted under `/api/vision/`, require authentication
(`IsAuthenticated`) and are scoped to the requesting owner.

| Method | Path | Description |
| ------ | ---- | ----------- |
| POST | `screenshots/` | Upload a screenshot (multipart `image`). `?analyze=true` also queues analysis. |
| GET | `screenshots/` | List the caller's screenshots. |
| GET | `screenshots/{id}/` | Screenshot detail. |
| GET | `screenshots/{id}/image/` | Stream the private image bytes (owner only). |
| POST | `screenshots/{id}/analyze/` | Start/reuse/re-queue analysis. Idempotent. |
| GET | `analyses/{id}/` | Full structured result + observations/patterns/zones. |
| GET | `analyses/{id}/events/` | Processing-event audit trail. |
| GET | `history/` | Paginated history (`?status=completed|partial|failed|…`). |
| GET | `status/{id}/` | Lightweight status for polling. |

Upload errors return HTTP `400` with a structured body such as:

```json
{ "detail": "…", "error_code": "image_format_unsupported", "request_id": "…" }
```

Error codes include `image_format_unsupported`, `image_corrupted`,
`image_too_large`, `image_dimensions_invalid` and `image_missing`.

The private image endpoint returns `404` (not `403`) for other users' records so
existence is not leaked.

---

## 4. Analysis lifecycle & statuses

`queued → running → completed | partial | insufficient_evidence | failed`

- **`completed`** — full observation set produced.
- **`partial`** — produced, but required information is missing/unreadable.
- **`insufficient_evidence`** — the screenshot cannot support a meaningful reading.
- **`failed`** — provider/schema error; `result` stays empty (nothing fabricated).

### Idempotency

Every analysis has a unique key
`analyze:<screenshot_id>:<prompt_version>:<schema_version>` (e.g.
`analyze:12:v1:1.0`). Therefore:

- A **completed** analysis is reused — no re-run, no new job.
- An **in-flight** analysis is reused — a repeat `POST …/analyze/` does **not**
  enqueue a duplicate job.
- A **failed** analysis is reset on the same row and re-queued.

---

## 5. Structured output (schema `v1.0`)

The validated payload contains:

- `chart_metadata` — platform, instrument, OTC status, timeframe, visible price
  labels, candle colours, indicators…
- `candles` — left→right classification, body/wick relative sizes, approximate
  pixel coordinates, completeness and per-candle confidence.
- `market_structure` — trend, swing highs/lows, breakouts, consolidation.
- `support_resistance` — zones, repeats, breaks, flips.
- `patterns` — candlestick patterns **and** advanced-course concepts (sequences,
  lonely candles, psychological sequences, motive/counter/last-effort waves,
  liquidity sweeps, order blocks, FVG, gaps, relative volume).
- `market_cycle`, `liquidity`, `volume`.
- `observation_confidence`, `missing_information`, `warnings`, `analysis_status`.

Integrity guarantees enforced by the validator:

- **No fabricated prices.** Numeric candle OHLC price keys are stripped with a
  warning; only pixel coordinates and qualitative sizes remain.
- **No fabricated probabilities.** Keys such as `probability`, `win_rate`,
  `prediction`, `up_probability` are hard-rejected.
- **Unknown means unknown.** Unreadable metadata is `UNKNOWN`; unknown enum values
  are coerced to `unknown` with a warning; OTC is never silently turned into regular.
- **Rightmost candle** is always marked potentially incomplete, with an ambiguity
  note and a top-level warning — regardless of what the provider claims.

---

## 6. Dashboard

`/dashboard/vision/` provides upload, private preview, start-analysis, live status,
metadata, patterns/structure, confidence/warnings and history. The detail page at
`/dashboard/vision/<id>/` shows the private preview and the structured result, and
both pages display the required disclaimer.

---

## 7. Background processing

| Task | Purpose |
| ---- | ------- |
| `chart_vision.analyze_screenshot` | Run the pipeline for an analysis id. |
| `chart_vision.purge_screenshots` | Delete screenshots past their retention window. |

- Transient errors (timeout, 5xx, 429) are retried with bounded exponential
  backoff; a `Retry-After` header is honoured.
- Non-retryable errors (401/403, misconfiguration, schema failure) fail fast.
- With `CELERY_TASK_ALWAYS_EAGER=True` (dev/test) tasks run inline.

---

## 8. Security notes

- Screenshot bytes live in **private** storage; `PrivateScreenshotStorage.url()`
  raises, so a record can never be served from `MEDIA_URL`.
- Images are streamed only through the authenticated, owner-checked endpoint.
- Uploads are checked by both declared MIME type **and** magic bytes, then decoded
  with Pillow's decompression-bomb guard and explicit dimension/pixel limits.
- Provider credentials are environment-only; nothing secret is persisted or logged.
- No trade/order execution exists anywhere in this layer.

---

## 9. Troubleshooting

| Symptom | Cause / fix |
| ------- | ----------- |
| `image_format_unsupported` | File is not a real PNG/JPEG/WebP (extension alone is not enough). |
| `image_corrupted` | Truncated/invalid image data. |
| `image_too_large` / `image_dimensions_invalid` | Exceeds `VISION_*` limits; resize or raise limits. |
| `Analysis failed: provider_unavailable` | Bad/missing `VISION_LLM_API_KEY` or `VISION_LLM_MODEL`, or the endpoint is unreachable. |
| `Analysis failed: schema_invalid` | Provider returned malformed/non-conforming JSON; check the model/prompt. |
| `Analysis failed: provider_timeout` | Increase `VISION_LLM_TIMEOUT_SECONDS` or `VISION_LLM_MAX_RETRIES`. |
| Provider returns impossible values | The validator drops fabricated prices and rejects probabilities; check the provider/model. |

Run the quality gate before shipping changes:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```
