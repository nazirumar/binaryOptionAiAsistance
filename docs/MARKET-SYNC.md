# Market Sync — Screenshot vs. MT5 Synchronization (Phase 4)

This document explains how to configure, run and operate the Phase 4 synchronization
layer in `apps.market_sync`.

> **Verification only.** The layer checks whether a stored Phase 3 screenshot analysis
> is **consistent with** stored Phase 2 MT5 candles. It does **not** score a strategy,
> estimate a probability, predict the next candle, or place any trade. A successful
> match validates *data consistency*, **not** future price direction.

---

## 1. What it does

Given a stored `ScreenshotAnalysis` (Phase 3 observations) and stored `MarketCandle`
rows (Phase 2 MT5 feed), the service runs a fixed, deterministic pipeline:

1. **Instrument matching** — resolve the screenshot instrument to an explicit broker
   symbol via validated mappings (never inferred from similar names).
2. **OTC protection** — an OTC screenshot is never compared against a regular feed.
3. **Timeframe matching** — parse and compare timeframes; a missing/uncertain
   timeframe is never assumed.
4. **Timestamp alignment** — anchor from user-provided time → visible time → capture
   metadata → fallback; map only **completed** screenshot candles onto MT5 open times.
5. **Candle comparison** — direction, body/upper/lower wick ratios and qualitative
   size bands.
6. **Structure comparison** — swings (HH/HL/LH/LL), trend agreement.
7. **Price-level comparison** — numeric axis (with reported offset) or relative
   structure when no labels exist.
8. **Feed compatibility & freshness** — OTC/mapping verification and age checks.
9. **Status decision** — a fixed-priority outcome with persisted evidence.

It never mutates the screenshot observations and never fabricates candle data, prices
or probabilities.

---

## 2. Configuration

All settings are environment-driven (see `.env.example`).

### Thresholds

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `SYNC_MAX_CANDLES` | `200` | Maximum candles considered |
| `SYNC_MIN_OVERLAP_CANDLES` | `3` | Minimum comparable candles before a verdict |
| `SYNC_DIRECTION_MATCH_MIN` | `0.75` | Direction agreement required for `VERIFIED_ALIGNMENT` |
| `SYNC_DIRECTION_PARTIAL_MIN` | `0.5` | Lower bound for `PARTIAL_ALIGNMENT` |
| `SYNC_DOJI_BODY_RATIO_MAX` | `0.12` | Doji body/range ceiling |
| `SYNC_BODY_BAND_SMALL_MAX` | `0.25` | Small-body band ceiling |
| `SYNC_BODY_BAND_MEDIUM_MAX` | `0.60` | Medium-body band ceiling |
| `SYNC_WICK_BAND_SMALL_MAX` | `0.20` | Small-wick band ceiling |
| `SYNC_WICK_BAND_MEDIUM_MAX` | `0.45` | Medium-wick band ceiling |
| `SYNC_BODY_RATIO_TOLERANCE` | `0.30` | Body-ratio agreement tolerance |
| `SYNC_WICK_RATIO_TOLERANCE` | `0.35` | Wick-ratio agreement tolerance |
| `SYNC_SCREENSHOT_MAX_AGE_SECONDS` | `3600` | Max screenshot age before `STALE_DATA` |
| `SYNC_MT5_MAX_CANDLE_AGE_SECONDS` | `900` | Max MT5 candle age before `STALE_DATA` |
| `SYNC_TIMESTAMP_TOLERANCE_SECONDS` | `5` | Grid-alignment tolerance |
| `SYNC_MIN_STRUCTURE_OVERLAP` | `5` | Minimum candles for a structure verdict |
| `SYNC_STRUCTURE_AGREE_MIN` | `0.70` | Structure agreement threshold |
| `SYNC_SWING_LOOKBACK` | `2` | Swing detection lookback |
| `SYNC_DEFAULT_TZ_OFFSET_MINUTES` | `0` | Assumed offset for naive timestamps |
| `SYNC_CONFIG_VERSION` | `1.0` | Recorded with each run |

Thresholds are **pragmatic defaults, not scientifically validated**. Tune per
broker/feed and re-run the comparator tests.

### Throttling

| Variable | Default |
| -------- | ------- |
| `SYNC_VERIFY_THROTTLE` | `60/minute` |
| `SYNC_READ_THROTTLE` | `240/minute` |

---

## 3. API

All endpoints are mounted under `/api/sync/`, require authentication
(`IsAuthenticated`) and are scoped to the requesting owner.

| Method | Path | Description |
| ------ | ---- | ----------- |
| POST | `verify/` | Verify an `analysis_id` or `screenshot_id`. Idempotent per user. `201` new, `200` reused. |
| GET | `results/{id}/` | Full session detail (owner-scoped). Includes `status_message`. |
| GET | `history/` | Paginated history; filters `outcome`, `timeframe`. |
| GET | `health/` | Reference-data availability, `config_version`, `server_time`, outcome counts. |

- Idempotency keys are **per-user** (`f"u{user.pk}:{key}"`) so they never cross
  tenants. Re-using the same key returns the existing session (`200`).
- Unknown/other-owner analyses return `404`; missing identifier or an invalid
  timeframe returns `400`.

---

## 4. Outcome statuses (fixed priority)

| Status | Meaning |
| ------ | ------- |
| `INCOMPATIBLE_FEED` | e.g. OTC screenshot vs. regular feed → never compared |
| `INSUFFICIENT_INFORMATION` | Missing symbol/timeframe/anchor, or too little overlap |
| `MT5_UNAVAILABLE` | No stored MT5 candles for the reference |
| `STALE_DATA` | Screenshot or MT5 beyond the freshness window |
| `VERIFIED_ALIGNMENT` | Direction ≥ `0.75`, structure `AGREE`, feed compatible **and** mapping verified, fresh, not uncertain |
| `PARTIAL_ALIGNMENT` | Moderate agreement — **never** presented as fully verified |
| `DATA_MISMATCH` | Sufficient overlap but the two sources disagree |

Only **`VERIFIED_ALIGNMENT`** counts as a successful dual-source verification.

---

## 5. Dashboard

| Path | Description |
| ---- | ----------- |
| `/dashboard/sync/` | Picker of verifiable analyses + history table (outcome, instrument, MT5 symbol, timeframe, created) |
| `/dashboard/sync/<pk>/` | Full detail: previews, assessment, per-candle comparison, reasons/issues, audit log, metrics |

The detail page shows a **"Not verified"** badge whenever the outcome is not
`VERIFIED_ALIGNMENT`; an unverified run is never presented as successful.

---

## 6. Background processing

| Task | Purpose |
| ---- | ------- |
| `market_sync.run_verification_task` | Thin wrapper that runs the (already synchronous) service for a session id. |

The API runs the comparison **synchronously** (cheap DB work); the Celery task is
provided for queued execution. With `CELERY_TASK_ALWAYS_EAGER=True` (dev/test) it
runs inline.

---

## 7. Security & integrity notes

- All reads are owner-scoped (superusers may use the management surfaces).
- Idempotency keys never cross tenants.
- Screenshot observations are never mutated; no prices or probabilities are fabricated.
- Only reliably completed candles are compared; the rightmost screenshot candle is
  always excluded.
- OTC protection is strict (verified OTC ↔ verified OTC only).

---

## 8. Troubleshooting

| Symptom | Cause / fix |
| ------- | ----------- |
| `INCOMPATIBLE_FEED` | OTC screenshot without a verified, mapped OTC reference. |
| `INSUFFICIENT_INFORMATION` | Symbol/timeframe/timestamp unreadable or too little overlap; improve the screenshot or widen `SYNC_MIN_OVERLAP_CANDLES`. |
| `MT5_UNAVAILABLE` | No stored MT5 candles for the symbol/timeframe; run the Phase 2 collector first. |
| `STALE_DATA` | Screenshot older than `SYNC_SCREENSHOT_MAX_AGE_SECONDS` or MT5 candle older than `SYNC_MT5_MAX_CANDLE_AGE_SECONDS`. |
| `PARTIAL_ALIGNMENT` shown as "Not verified" | Working as intended — only `VERIFIED_ALIGNMENT` is a successful verification. |

Run the quality gate before shipping changes:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```
