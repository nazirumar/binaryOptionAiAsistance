# PHASE 11 — LIVE VALIDATION STATUS

Project: Nazbeen Academy Binary Ai Asisstance
Date: 2026-10-18
Baseline: `e77bbb0` (Phase 10 closed, 689 passed / 2 skipped)

Every test that could be executed is placed in exactly one bucket below.
No test labelled LIVE is ever silently mocked; no credentials are reproduced
in this document (the Google/Gemini key lives only in the local, gitignored
`.env` and is never echoed or committed).

---

## 1. LIVE AND PASSED

### 1.1 CP4 reasoning provider — real HTTP round trip

| Field | Value |
|---|---|
| Test | `tests/test_phase11_reasoning.py::test_live_reasoning_smoke` |
| Marker | `@pytest.mark.live` (registered in `pyproject.toml`, strict-markers) |
| Gate | `REASONING_LLM_LIVE_TEST=1` **and** a configured non-mock provider **and** a non-empty API key — all read from `os.environ` at runtime |
| Provider | Google Gemini `generateContent` (stdlib `urllib`, header `x-goog-api-key`, key never in the URL) |
| Model | `gemini-flash-latest` |
| Executed | 2026-10-18, opt-in run with `REASONING_LLM_LIVE_TEST=1` set for that single command |
| Result | **PASSED** — `response.success is True`, non-empty content, real provider echo, ≈11 s wall time |
| Key handling | Key read from local `.env`; value not reproduced anywhere in this document or the repository |

**Model-name corrections made against live API feedback (recorded for
auditability):**

1. `gemini-1.5-pro` — rejected by the API: retired model for this account.
2. `gemini-2.5-flash` — rejected: "no longer available to new users"
   (the API's response recommends `gemini-3.8-flash`).
3. `gemini-flash-latest` — accepted; the live smoke test passed with it.

`.env` / `.env.example` carry `REASONING_LLM_MODEL=gemini-flash-latest`.

**Hermeticity note (CP4 regression):** immediately after CP4 introduced the
real HTTP path, the unit suite inherited `REASONING_LLM_PROVIDER=google` from
the developer `.env` and began issuing real requests (suite time ballooned to
≈243 s and one assertion observed a real LLM-composed answer). Fixed by
forcing `REASONING_LLM_PROVIDER="mock"` + empty key in
`config/settings/test.py`; the suite returned to ≈27 s with zero network
traffic, while the gated live smoke — which builds its provider explicitly
from `os.environ`, independent of Django settings — continued to perform a
genuine round trip when opted in. Both behaviours were re-verified after the
fix.

---

## 2. MOCKED AND PASSED

All Phase 11 correctness suites run fully offline: local vision doubles
(`tests/vision_fakes.py`), patched `urlopen` for CP4, eager Celery, in-memory
SQLite. These are labelled MOCKED, never LIVE.

| Suite | Scope | Result |
|---|---|---|
| `tests/test_phase11_timing.py` | CP5 tz-aware timing, expiry, rollover | 100 passed |
| `tests/test_phase11_probability.py` | CP6 strict probability presenter | passed |
| `tests/test_phase11_reasoning.py` (non-live) | CP4 adapters with patched HTTP | passed (live case separately gated, §1) |
| `tests/test_phase11_strategy_api.py` | CP2 evaluate/rules APIs, forged-field bypass | passed |
| `tests/test_phase11_pipeline.py` | CP1 upload → durable job → assessment; CP7 educational; CP9-J probability | 20 passed |
| `tests/test_phase11_research_api.py` | CP3 datasets/backtests/performance/calibration/registry | 15 passed |
| `tests/test_phase11_scenarios.py` | CP9 scenarios A–J | 12 passed |
| `tests/test_phase11_e2e.py` | CP10 end-to-end (login → analyze → verified sync → evaluation → follow-up → research → journal; isolation; idempotency; unverifiable path) | 4 passed |
| `tests/test_ai_assistant.py` | CP8 durable jobs, CP7, assistant API | 40 passed |
| Phase 11 additions, combined run | all of the above + probability/timing/strategy | 195 passed, 1 skipped (the gated live case) |

Full-suite (CP14) totals are recorded in
`docs/PHASE-11-COMPLETION-REPORT.md`.

---

## 3. LIVE FAILED

*None.* No live execution produced a failure that remains unresolved. The
only live failures observed were the model-name rejections in §1, which were
diagnosed, corrected, and re-executed to a pass.

---

## 4. NOT EXECUTED

| Item | Reason | Carried from |
|---|---|---|
| Production deployment / migration on a live server | Explicitly forbidden until the user authorizes it | Phase 10 non-negotiable |
| Any real-money trading action | No automatic trading exists by design; out of scope for all phases | Phase 10 non-negotiable |

Nothing in this bucket was executed with a mock and reported as live. The
MT5-dependent code paths remain covered in CI by MOCKED AND PASSED suites
using seeded `MarketCandle` rows (§2); the real-terminal verification that
previously blocked this bucket was executed on 2026-10-18 and is recorded in
§4a.

---

## 4a. ADDENDUM (2026-10-18, user-authorized live run): MT5 + vision

The user explicitly requested live connection testing. Executed with the
credentials already present in the local (gitignored) `.env`. No secrets were
printed or committed.

### MT5 terminal — LIVE VERIFIED

| Step | Result |
|---|---|
| `manage.py mt5_integration_check` | Connected to `MetaQuotes-Demo`, account `********89`, terminal build 6271, `connected=True` (attempt 1 hit terminal warm-up: IPC pipe timeout; automatic retry connected) |
| `manage.py seed_market_symbols` | 14 global symbol mappings created |
| Re-run integration check | `EURUSD M1`/`M5`: 10 completed candles each, last close `1.12393`, clean disconnect |
| `manage.py mt5_worker --once` (direct mode) | 300 M1 + 300 M5 candles + 1 tick persisted to PostgreSQL, `WorkerHeartbeat` **online**, `EURUSD` mapping status **valid** |

The run landed on a Sunday: MT5 correctly returned the last *completed*
session's candles (Friday 2026-10-16 close) and no live forming candle —
honest historical data, not synthetic.

**Config defect found & fixed (`.env`, gitignored):** `MT5_PATH` was written
as a quoted Windows path with backslashes; the env loader stripped the
backslashes, producing the invalid path `C:Program FilesMetaTrader 5\terminal64.exe`.
Rewritten with loader-proof forward slashes
(`C:/Program Files/MetaTrader 5/terminal64.exe`) and verified to resolve to
the real `terminal64.exe`.

### Vision provider (Gemini via OpenAI-compatible endpoint) — CONNECTION LIVE VERIFIED

| Check | Result |
|---|---|
| Authenticated request to `generativelanguage.googleapis.com/v1beta/openai` with `VISION_LLM_MODEL=gemini-3.8-flash` | **Two successful round trips** (real image upload, real model responses) on 2026-10-18 |
| Full pipeline attempt (provider → JSON parse → schema validation → persist) | Attempt 1 exposed a config defect; later attempts blocked by quota (below). Fail-closed behaviour confirmed: every failure persisted as `failed` with machine-readable codes (`schema_invalid`, `provider_rate_limited`) — never a fabricated analysis |

**Config defect found & fixed (`.env`, gitignored):** `VISION_LLM_MAX_TOKENS`
was `2048`, truncating the structured chart-analysis JSON mid-object
(`finish_reason: length`). Raised to `16384`.

**Remaining limitation:** the free-tier quota `generate_content_free_tier_requests`
allows **20 requests/day per model**; it was exhausted during validation
(resets nightly). One clean end-to-end persisted run remains to be captured
after quota reset or on a paid tier. No further API calls were made once the
quota message was identified.

### Reasoning LLM — LIVE VERIFIED on Groq (2026-10-18, user-supplied key)

The user supplied a Groq API key (stored only in the gitignored `.env`) to
replace Gemini for reasoning. The opt-in live smoke
(`test_phase11_reasoning.py::test_live_reasoning_smoke`, `REASONING_LLM_LIVE_TEST=1`)
**passed** against `https://api.groq.com/openai/v1` with `qwen/qwen3.8-27b`
(12.7s).

**Defect found & fixed:** Groq's Cloudflare layer rejected urllib's default
`Python-urllib/...` User-Agent with error 1010 (HTTP 403). The OpenAI-compatible
request path (`reasoning_provider._build_openai_request`) now sends a
descriptive `nazbeen-academy/0.1` User-Agent; verified end-to-end live.
`openai/gpt-oss-120b`/`-20b` were rejected as unusable for this integration:
their hidden reasoning tokens consume the whole `REASONING_LLM_MAX_TOKENS`
budget and the visible answer comes back empty. `qwen/qwen3.8-27b` responds
cleanly. Full suite after the change: 876 passed, 3 skipped.

**Key scope note:** the supplied Groq key exposes **no vision-capable models**
(only `gpt-oss`, `qwen3.8-27b`, `allam-2-7b`, `whisper`, `prompt-guard` and
TTS), so screenshot vision remains on Gemini (free tier, 20 requests/day,
quota resets nightly). Moving vision to Groq requires a key that exposes a
vision model (e.g. llama-4 multimodal).

Reproduction (after quota reset):

```powershell
$env:DJANGO_SETTINGS_MODULE = "config.settings.dev"
.\.venv\Scripts\python.exe manage.py mt5_integration_check
.\.venv\Scripts\python.exe manage.py mt5_worker --once
```

---

## 5. REPRODUCING THE LIVE SMOKE (opt-in)

```powershell
$env:REASONING_LLM_LIVE_TEST = "1"
.\.venv\Scripts\python.exe -m pytest tests\test_phase11_reasoning.py::test_live_reasoning_smoke -m live -q
```

Without all three gates (`REASONING_LLM_LIVE_TEST=1`, non-mock provider,
non-empty key) the test **skips with an explicit reason** — it never falls
back to a mock. Observed in ordinary runs:

```
SKIPPED [1] tests\test_phase11_reasoning.py:...: Live reasoning smoke test
requires REASONING_LLM_LIVE_TEST=1 and a configured provider/key
```
