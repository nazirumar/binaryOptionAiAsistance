# PHASE 10 — USER ACCEPTANCE TESTING (UAT)

**Project:** Nazbeen Academy Binary Ai Asisstance
**Date:** October 18, 2026
**Method:** executable acceptance suite `tests/test_phase10_uat.py` (14 tests), run
against the deterministic test environment (`config.settings.test`, faked vision
provider, faked MT5 series). No live MT5 terminal or hosted LLM was involved.

Every scenario below is backed by a real test. **Actual** columns record what the
suite observed, not what was hoped for. A scenario that cannot be honestly
satisfied is marked as such rather than reported as a pass.

---

## Acceptance results

| # | Scenario | Expected | Actual | Verdict |
|---|---|---|---|---|
| 01 | Regular forex screenshot, verified MT5 alignment | Sync returns `verified_alignment`, `is_verified=True` | `outcome="verified_alignment"`, `is_verified=True`, 12 candles aligned | **PASS** |
| 02 | OTC screenshot with no compatible reference feed | Refused as incompatible; OTC never substituted with regular forex prices | `outcome="incompatible_feed"`, `is_verified=False` | **PASS** |
| 03 | Bullish support rejection | Detected as bullish rejection evidence | `pa.sr.rejection.support` present, direction `bullish` | **PASS** |
| 04 | Bearish resistance rejection | Detected as bearish rejection evidence | `pa.sr.rejection.resistance` present, direction `bearish` | **PASS** |
| 05 | SBR / RBS retest | Both flip types recognised on retest | `pa.sr.sbr_rbs.resistance_became_support` (RBS) and `pa.sr.sbr_rbs.support_became_resistance` (SBR) both detected | **PASS** |
| 06 | Liquidity sweep | Sweep recognised with correct bias | `pa.sweep.low_sweep` present, direction `bullish` | **PASS** |
| 07 | Conflicting bullish/bearish evidence | Conflict surfaced, never silently resolved into a confident direction | Both bullish and bearish evidence present; ≥1 conflict reported | **PASS** |
| 08 | NO TRADE due to insufficient information | Abstain instead of guessing | `direction == NO_TRADE` on a 1-candle input | **PASS** |
| 09 | Uncalibrated probability | No success probability quoted | `ProbabilityPresenter().present(None)` → `available=False` | **PASS** |
| 10 | Expired next-candle signal | Refused outside the entry window | `direction == NO TRADE`, warning `opportunity_expired` present | **PASS** |
| 11 | Historical analysis review | Prior analysis readable in dashboard + history API | `/dashboard/analyses/` → 200; `/api/vision/history/` contains the analysis | **PASS** |
| 12 | Trading journal entry | Entry recorded with explicit provenance | Created as `trade_type="hypothetical"`, `is_settled=False` | **PASS** |
| 13 | Educational follow-up question | Answer grounded in stored evidence | No error; `evidence.available == True` | **PASS** |

**Result: 13/13 acceptance scenarios satisfied (14 test cases).**

---

## Non-functional acceptance (verified separately)

| Area | Check | Result |
|---|---|---|
| Cross-user isolation (full stack) | Second user cannot read another's analysis / sync / evaluation / journal | **PASS** (`test_workflow_is_scoped_to_the_owner`, `TestCrossUserIsolation`) |
| Duplicate submission | Repeated analysis request is de-duplicated | **PASS** |
| Backtest authorization | User cannot queue a run against another user's dataset | **PASS** (IDOR closed) |
| Backup & restore (SQLite) | Backup → restore → identical content; tampered row detected | **PASS** (`scripts/verify_backup_restore.py`) |
| Failure handling (19 classes) | MT5 down/stale, OTC, mismatches, provider timeouts, Redis/DB/Celery failure, invalid model output, expiry, conflicts, unauth access | **PASS** — 64 tests, all fail closed |

---

## Scope limitations of this UAT

These are stated plainly so the results are not over-read:

1. **No live MT5 terminal.** Scenarios 01, 02, 06 used stored candle fixtures
   through the real synchronization code path, not a broker connection.
2. **No live vision or reasoning LLM.** Scenario 13's explanation came from the
   deterministic mock provider. The real vision HTTP path exists but was not
   exercised against a provider here.
3. **No probability-calibration scenario with real outcomes.** Scenario 09
   verifies that probability is *withheld* when no validated model exists. No
   calibrated model exists in this deployment, so no scenario can quote a real
   probability — by design.
4. **Scenario 04's fixture is hand-constructed.** No canned
   resistance-rejection fixture ships in the test helpers, so the series in
   `test_uat04_bearish_resistance_rejection_detected` was built and verified
   empirically to trigger the detector.
5. **No financial outcome is claimed.** These scenarios assert that the software
   behaves honestly and safely. They say nothing about whether any setup is
   profitable, and no such claim is made anywhere.

## How to re-run

```
.\.venv\Scripts\python.exe -m pytest tests/test_phase10_uat.py -v
```

A regression in any acceptance scenario fails CI (`.github/workflows/ci.yml`
runs the whole suite), so these behaviours are protected going forward.
