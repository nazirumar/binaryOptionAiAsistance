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
| MT5 terminal live tests (real broker connection, real candle streaming) | No MetaTrader 5 terminal is available in this environment | Phase 10 C5 |
| Production deployment / migration on a live server | Explicitly forbidden until the user authorizes it | Phase 10 non-negotiable |
| Any real-money trading action | No automatic trading exists by design; out of scope for all phases | Phase 10 non-negotiable |

Nothing in this bucket was executed with a mock and reported as live. The
MT5-dependent code paths are covered only by MOCKED AND PASSED suites using
seeded `MarketCandle` rows (§2), and that limitation is carried forward
unchanged.

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
