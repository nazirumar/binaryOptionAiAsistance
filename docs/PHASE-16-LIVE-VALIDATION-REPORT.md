# Phase 16 — Live Signals End-to-End Validation Report

**Repository:** https://github.com/nazirumar/binaryOptionAiAsistance
**Date:** 2026-10-20
**Baseline commit at start of audit:** `b8b2b2a` (*fix(market-data): convert MT5 server-clock times to true UTC*)
**Auditor role:** senior Django engineer / quantitative research engineer / QA

> Every figure below comes from a real database row, a real function call, or a
> real command output. Nothing is estimated. Where a check could not be run
> (no desktop browser, no live provider key), it is reported **NOT TESTED** —
> not simulated.

---

## 0. Summary of findings

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| F1 | MT5 server-clock→UTC conversion is correct and independently verified (+3.00 h on MetaQuotes-Demo) | — | ✅ Verified |
| F2 | Full pipeline (arrival→persist→close→detect→persist→dashboard→alerts) works on real candles | — | ✅ Verified |
| F3 | 10/10 detectors confirm their reviewed examples; 7/7 lookalikes rejected; 6/6 forming-bar downgrades; 6/6 no-lookahead | — | ✅ Verified |
| F4 | **Stuck chart-vision analysis bug**: a worker killed mid-flight leaves `status=RUNNING` forever and the UI blocks ("already queued") | **High** | 🔧 **Fixed this phase** |
| F5 | First-run monitor backfills old candles (evaluated a 3.6-day-old candle and emitted signals for it) | Medium | Reported (by-design, noisy) |
| F6 | No strategy is validated: SS1/SS2 clear the 30-signal bar but out-of-sample accuracy is ≤ chance | — | Gate correctly closed |
| F7 | Real-browser checks (responsive layout, JS states, notifications) could not be run | — | **NOT TESTED** |

---

## Checkpoint 1 — Environment audit

**Commands**

```powershell
.venv\Scripts\python.exe --version
.venv\Scripts\python.exe -c "import django; print(django.get_version())"
.venv\Scripts\python.exe manage.py check
```

**Results**

| Component | Evidence | State |
|-----------|----------|-------|
| Python | `3.13.14` | ✅ |
| Django | `5.2.18` | ✅ |
| Database | engine `django.db.backends.postgresql`, db `nazbeen_academy`; `connection.is_usable()` → True | ✅ PostgreSQL 18.6 |
| Redis (Celery broker) | `127.0.0.1:6379` TCP accept → True | ✅ reachable |
| MT5 terminal | `terminal64.exe` running (PID 12880); `terminal_info().connected` → True | ✅ connected |
| Celery worker / Beat | not running during the audit window (started on demand) | ⚠️ not resident |
| Configured monitors | `LIVE_SIGNAL_MONITORS = ['EURUSD:M5']`; 1 `InstrumentMonitor` row, `feed=ok` | ✅ |

**Credential handling:** the audit read `MT5_SERVER`, `MT5_LOGIN` presence only.
No password, token or key is printed, logged or committed anywhere in this
report. `scripts/scan_secrets.py` → *"No possible secrets found."*

### Timezone fix verification (no offset assumed)

The fix was checked against a **trusted clock**, not against an assumption:

```powershell
# MT5's own tick epoch vs the OS clock
EURUSD tick raw epoch: 1792523179 -> 2026-10-20 19:06:19+00:00
trusted UTC (OS)     : 2026-10-20 16:06:15+00:00
implied offset hours : 3.001
```

* Raw MT5 time is **3 h ahead** of UTC ⇒ the broker (MetaQuotes-Demo) genuinely
  serves server wall-clock, not UTC. This is **not** a repo constant; it is
  measured per terminal.
* `MetaTrader5Client.detect_server_offset()` derives the offset from a fresh
  tick, rounds to the nearest minute, caches it, and falls back to **0** when it
  cannot be measured (an unknown offset never shifts data). It can be pinned
  explicitly with `MT5_SERVER_TZ_OFFSET_MINUTES`.
* Stored candles are true UTC (no negative age):

  ```
  M1 newest stored=2026-10-20 15:43:00+00:00 age=23.5 min
  M5 newest stored=2026-10-20 15:40:00+00:00 age=26.5 min
  ```

**Configuration problems found:** none blocking. One design note: offset
detection probes `EURUSD`; on an account where `EURUSD` has no tick, detection
falls back to 0. Acceptable (safe default) but worth configuring
`MT5_SERVER_TZ_OFFSET_MINUTES` explicitly for non-EURUSD-only accounts.

---

## Checkpoint 2 — End-to-end monitoring (real candles, real timestamps)

Harness: `scripts/phase16_e2e_probe.py` (read-only; measures each step).

**Live run output (real):**

```
[16:09:00.991] preflight DB connectivity: OK (ok)
[16:09:01.028] monitor: EURUSD M5 (feed=ok, enabled=True, state=running)
[16:09:01.111] step1/2 newest M5 candle open_time=2026-10-20 16:05:00+00:00 is_complete=False age=4.0min source=mt5
[16:09:01.111] step3 close time = open_time + M5 duration (the monitor never evaluates a forming bar)
[16:09:01.179] step4 before: signals=40 alerts=0
[16:09:02.043] step4 monitor run: evaluated=True new=10 expired=20 resolved=10 feed=ok msg='ok' latency=862ms
[16:09:02.049] step5/6 latest signal=CH7_S1 status=AWAITING_CONFIRMATION category=experimental_pattern direction=none
[16:09:02.049]        candle_close=2026-10-20 16:05:00+00:00 detected_at=2026-10-20 16:09:01.179257+00:00 detection_latency=241.2s
[16:09:05.155] step7 GET /dashboard/live-signals/ -> HTTP 200 bytes=125109 shows_instrument=True
[16:09:05.166] step8 alerts total=0 (new=0) duplicate (user,signal) pairs=0
```

| Step | Result | Evidence |
|------|--------|----------|
| 1. New candle arrives | ✅ | MT5 worker log `market_data.candles.persisted` every 15 s |
| 2. Persisted correctly | ✅ | `MarketCandle` rows, `is_complete` derived from open time + delay |
| 3. Candles closes | ✅ | newest **stored** bar is the forming one (`is_complete=False`); only closed bars reach the engine |
| 4. Monitoring task processes | ✅ | `evaluated=True`, run latency **862 ms** |
| 5. Detectors evaluate | ✅ | 10 strategies evaluated (same 10 from Checkpoint 3) |
| 6. Patterns persisted | ✅ | `LiveSignal` rows created; one per (monitor, strategy, candle, status) |
| 7. Dashboard displays | ✅ | `GET /dashboard/live-signals/` → HTTP 200, 125 109 bytes, instrument present |
| 8. Notifications, no dupes | ✅ | 0 duplicate `(user, signal)` pairs; dedup is a DB unique constraint |

**Detection latency (Checkpoint 5).** `scripts/phase16_timing_analysis.py`:

```
latency  min=17.3s  median=241.2s  mean=62581.3s  max=312126.5s
late (>300s): 10/50
```

* Live detections land **17.3 s–282 s** after candle close — consistent with a
  15 s poll interval plus M5 close timing.
* The 10 "late" rows are **one first-run backfill batch**: on `2026-10-20
  14:42:06` the brand-new monitor evaluated the oldest stored candle
  (`2026-10-16 23:55`) — see **F5**. No signal is *backdated*: each carries its
  true candle open time and is expired if its window has passed.

---

## Checkpoint 3 — Strategy detection audit

Harness: `scripts/phase16_detector_audit.py`. Rules were **not** modified.

| Sub-check | Result |
|-----------|--------|
| A. Reviewed positive examples confirm with the right direction | **10/10** |
| B. Lookalikes / negatives correctly not confirmed | **7/7** |
| B2. Forming last candle never confirms | **6/6** |
| C. Truncation invariance — a detection is reproducible from its prefix (no lookahead) | **6/6** |

**Real-feed firing rate** (actual stored EURUSD candles):

```
M5 605 complete candles (2026-10-15 23:00 .. 2026-10-20 16:05)
  SS2 CONFIRMED_PATTERN bearish ; SS1/SS3/CH7_S1 AWAITING ; SS5/SS6/SS19/SS21/SS22/SS23 FORMING
M1 626 complete candles
  all AWAITING/FORMING (no confirmation in this window)
```

**Missed patterns / false positives:** none observed against the reviewed
fixtures. The zero-signal strategies on M5 (SS5, SS6, SS21, SS22, SS23) are the
**book rules being selective**, not detector failures — their reviewed fixtures
confirm (check A). No rule was relaxed to raise counts.

---

## Checkpoint 4 — Live-monitoring reliability

Existing Phase 15 suite: `tests/test_phase15_live_signals.py` → **55 passed**.
New Phase 16 suite: `tests/test_phase16_reliability.py` → **7 passed**.

| Scenario | Covered by | Result |
|----------|-----------|--------|
| Missing candles | `test_unavailable_feed_marks_monitor_and_creates_nothing`, `test_missing_symbol_is_unavailable` | ✅ never healthy |
| Duplicate candles | `TestOverlappingJobs` (new), `test_duplicate_insert_is_noop` | ✅ no double-persist |
| Broker disconnections | `test_provider_error_is_bounded` | ✅ bounded failures |
| Stale feeds | `test_stale_feed_marked_stale`, `test_status_fragment_does_not_claim_a_stale_feed_is_reporting` | ✅ never reported healthy |
| Timezone changes | Checkpoint 1 (offset measured, not assumed) | ✅ |
| Worker restarts | `test_restart_recovers_from_persisted_position` | ✅ resumes from persisted position |
| Delayed processing | `test_delayed_candle_is_evaluated_once_when_it_arrives` (new) | ✅ evaluated once |
| Overlapping monitoring jobs | `TestOverlappingJobs` (new) | ✅ idempotent |
| Database interruptions | `_record_failure` marks DEGRADED→ERROR; monitor skipped after 5 failures | ✅ (unit) |
| Market closure | `test_no_new_candles_leaves_healthy_but_unevaluated` (new) | ✅ no signal during closure |

**Failed/stale feeds never appear healthy** — confirmed both by test and by the
live `feed_state` transition (`ok`→`stale`→`unavailable`), with the dashboard
summary surfacing `stale_monitors` rather than claiming "all feeds reporting
live".

### F4 — Stuck chart-vision analysis (found here, fixed this phase)

Read-only evidence (`scripts/phase16_screenshot_diag.py`):

```
id=1 screenshot=1 status=running attempts=1 created=2026-10-18 09:59:59
     started=2026-10-18 10:00:00 finished=None          <-- stuck ~2.5 days
id=2 screenshot=2 status=failed  error_code=provider_timeout "no response within 60s"
id=10 screenshot=3 status=completed (owner 2)
id=11 screenshot=4 status=failed attempts=2 provider_timeout
```

* Analysis **#1** has `status=running`, `finished_at=None`, and its last event is
  `provider_request` — the worker died mid-flight and **nothing reconciled it**.
* `_launch_analysis` treated any in-flight row as "already queued", so Screenshot
  #1 was **permanently stuck**. There was **no stale-run reaper**.

**Fix (behaviour-preserving for healthy runs):**
* `VISION_ANALYSIS_STALE_SECONDS` (default 900) — a `RUNNING` analysis older
  than this is abandoned.
* `reap_stale_analyses()` + beat task `chart_vision.reap_stale_analyses`
  (every 5 min) marks stale rows `FAILED` (`stale_run`) so they become retryable,
  or re-queues them.
* `_launch_analysis` recovers a genuinely-stuck row instead of blocking.
* **Diagnostic evidence preserved:** the four existing rows were *not* mutated;
  the reader confirmed Analysis #1 `stuck=True` would be recovered by the reaper.

---

## Checkpoint 5 — Signal timing and outcomes

* **Latency**: see Checkpoint 2 (`min 17.3 s`, live median ≈ 241 s, one
  first-run backfill batch).
* **Outcome scope**: outcomes are the **next-candle close direction on the same
  feed** (`_outcome_fields` → `"next-candle close direction on the same feed"`),
  explicitly **not** a binary-option settlement. The metric-scope disclaimer is
  embedded in every validation artifact.
* **OTC**: OTC instruments are never verified with an MT5 (non-OTC) feed → they
  are marked `UNVERIFIABLE`. All 14 `MarketSymbol` rows have `is_otc=False`;
  this deployment is **real-pairs only, no OTC**.
* **Outcome coverage**: 30 `unverifiable` (pattern-only, no direction to score),
  20 `pending`. No outcome is estimated where a feed cannot verify it.

---

## Checkpoint 6 — Frontend verification

**Browser environment: NOT TESTED.** No desktop browser is connected to the
session, so responsive layout, JS loading states, filter interactions,
notification UX and screen-reader behaviour were **not** exercised in a real
browser and are **not** claimed.

Best available evidence — server-side rendering of real pages with real data
(`scripts/phase16_frontend_check.py`):

```
[OK ] live-signals dashboard  /dashboard/live-signals/   bytes=125109  markers={lang,viewport,h1,skip_link,htmx,nav_aria}=True
[OK ] dashboard home          /dashboard/                bytes= 45682  all markers True
[OK ] screenshot cases        /dashboard/screenshot-cases/ bytes=32755 all markers True
[404] screenshot case detail  /dashboard/screenshot-cases/1/  -> no ScreenshotCase rows exist
```

The 404 is correct: there are **0** `ScreenshotCase` rows, so there is no detail
page to render.

**Previously reported stuck Screenshot #1 / failed Screenshot #2:** substantiated
as F4 above — a real stuck `RUNNING` row and a real `provider_timeout` failure.
Their diagnostic evidence (rows, files under `private_media/screenshots/`) is
**intact**.

---

## Checkpoint 7 — Research readiness

**Reproduce with:**

```powershell
.venv\Scripts\python.exe manage.py validate_book_strategies --symbol EURUSD --timeframe M5 --out docs/artifacts/phase16_validation_eurusd_m5.json
```

**Real results (619 M5 candles, chronological replay, no lookahead; outcome =
next-candle direction):**

| Strategy | Pooled signals | Pooled acc. | OOS signals | OOS acc. | ≥30 signals? |
|----------|---------------|-------------|-------------|----------|--------------|
| SS1 | 47 | 0.617 | 11 | **0.455** | ✅ |
| SS2 | 68 | 0.574 | 22 | **0.545** | ✅ |
| SS3 | 4 | 1.000 | 1 | — | ❌ |
| SS19 | 1 | 0.000 | 0 | — | ❌ |
| CH7_S1 | 5 | 0.400 | 1 | — | ❌ |
| SS5, SS6, SS21, SS22, SS23 | 0 | — | 0 | — | ❌ |

* SS1's pooled 0.617 is driven by in-sample (0.847); its **out-of-sample**
  accuracy is **0.455** — below chance. Wilson 95% CI [0.21, 0.72] spans 0.5.
* SS2 out-of-sample **0.545**, CI [0.35, 0.73] — spans 0.5.
* **Neither strategy is validated.** The approval gate is therefore correctly
  **closed** (see below).

| Metric | Value (real) |
|--------|--------------|
| Real candles processed (M5) | 619–620 complete |
| Real candles processed (M1) | 626–700 complete |
| Patterns persisted | 50 `LiveSignal` rows (2 `confirmed_pattern`, 48 `experimental_pattern`) |
| Detection latency | live 17.3 s – 282 s |
| Missed / false-positive (vs fixtures) | 0 / 0 |
| Feed outages | 0 during window; `feed_state` transitions tested |
| Outcome verification coverage | 30 `unverifiable`, 20 `pending` |
| Strategy sample sizes | in table above |
| Unresolved blockers | F5 (first-run backfill noise); F7 (no browser) |

**Strategy approval state (unchanged, by design):**

```
strategies total: 32
recognition_enabled: 10
decision_use_approved: 0
research_status approved: 0
by research_status: {'extracted': 22, 'backtested': 10}
```

**No strategy was approved automatically.** Approval remains an explicit,
audited admin action requiring evolutionary evidence; nothing here triggers it.

---

## Checkpoint 8 — Completion

**Commands run**

```powershell
.venv\Scripts\python.exe manage.py check                       # no issues
.venv\Scripts\python.exe scripts/check_env_coverage.py         # RESULT: OK
.venv\Scripts\python.exe manage.py validate_book_strategies ...# 10 reports
.venv\Scripts\python.exe -m pytest tests/test_chart_vision_tasks.py tests/test_chart_vision_api.py tests/test_phase16_reliability.py -q
.venv\Scripts\python.exe -m pytest tests/test_phase15_live_signals.py -q
.venv\Scripts\python.exe -m ruff check <changed paths>
```

**Test results**

| Suite | Result |
|-------|--------|
| `test_chart_vision_tasks.py` + `test_chart_vision_api.py` + `test_phase16_reliability.py` | 43 passed |
| `test_phase15_live_signals.py` | 55 passed |
| Full suite | **1323 passed, 3 skipped** (161 → 141 s) |
| Ruff (changed paths) | All checks passed |

**Safety**

* No automatic real-money trading was implemented or deployed.
* No strategy was approved; signals remain direction-free (`direction=none` ×50).
* All 14 symbols are non-OTC real pairs.
* Screenshot diagnostic evidence was preserved (read-only audit + non-destructive
  code fix).

**Outstanding problems**

* **F5** — first-run monitor backfill emits (correctly-timestamped) signals for
  old candles. Operationally noisy; consider a configurable "ignore candles
  older than N periods on a monitor's first run".
* **F7** — real-browser verification not performed (no browser in this
  environment).
* SS5/SS6/SS21/SS22/SS23 produce **0** signals on M5 EURUSD in the current
  window: their rules are selective. More history and other instruments are
  needed before any validation claim.

---

## Files added / changed this phase

**Added**
* `scripts/phase16_e2e_probe.py` — end-to-end measurement harness
* `scripts/phase16_detector_audit.py` — detector audit harness
* `scripts/phase16_timing_analysis.py` — latency analysis
* `scripts/phase16_screenshot_diag.py` — read-only screenshot evidence reader
* `scripts/phase16_frontend_check.py` — server-side render checks
* `tests/test_phase16_reliability.py` — 7 reliability tests
* `docs/artifacts/phase16_validation_eurusd_m5.json` — real validation output
* `docs/PHASE-16-LIVE-VALIDATION-REPORT.md` — this report

**Changed**
* `apps/chart_vision/tasks.py` — stale-run detection + reaper task
* `apps/chart_vision/views.py` — recover a stuck analysis instead of blocking
* `config/settings/base.py` — `VISION_ANALYSIS_STALE_SECONDS`, beat entry
* `tests/test_chart_vision_tasks.py`, `tests/test_chart_vision_api.py` — recovery tests
* `.env.example` — documents `VISION_ANALYSIS_STALE_SECONDS`
