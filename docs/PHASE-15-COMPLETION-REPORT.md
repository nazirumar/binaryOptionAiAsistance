# Phase 15 — Completion Report

**Feature:** Automatic Live Signals Monitor
**Project:** Nazbeen Academy Binary Ai Asisstance
**Status:** Complete — all eight checkpoints delivered.

---

## 1. Checkpoints

| # | Checkpoint | Delivered |
| --- | --- | --- |
| 1 | Audit existing strategy engines and data feeds | `docs/PHASE-15-LIVE-SIGNALS-ARCHITECTURE.md`, `docs/PHASE-15-STRATEGY-INTEGRATION.md` (inventory of reusable detectors, providers, approval gates) |
| 2 | Monitoring models and services | `apps/live_signals/models.py`, `services/providers.py`, `services/monitor.py`, migration `0001_initial` |
| 3 | Live closed-candle detection | `services/providers.py` (`_finalise` re-derives completeness), `services/matching.py`, `services/monitor.py` |
| 4 | Strategy eligibility and approval rules | `services/matching.py` (`check_eligibility`, `categorise`, `match_strategy`) |
| 5 | Live Signals dashboard | `/dashboard/live-signals/` + status/feed/detail/outcomes/settings templates |
| 6 | Live updates and notifications | HTMX polling fragments + `services/alerts.py`, `tasks.py` |
| 7 | Forward paper evaluation | `services/monitor.py` (`_resolve_outcomes`), `services/metrics.py`, outcomes page |
| 8 | Test, document and report | `tests/test_phase15_live_signals.py` (54 tests), 4 docs |

## 2. What was built

* **Automatic monitoring engine** — a Celery task
  (`live_signals.run_monitors`, beat every 45 s) walks every enabled
  `InstrumentMonitor`, asks a `CandleProvider` for **closed** candles, and
  evaluates only new candles (duplicate prevention + restart recovery).
* **Provider abstraction** — `db` (default, reads already-persisted
  `MarketCandle` rows) and optional `mt5`; new feeds register in `PROVIDERS`
  without touching strategy logic.
* **Strategy matching** — reuses the Phase 13 `BookStrategyRecognizer` /
  `BOOK_DETECTORS`; no detection logic is duplicated.
* **Signal lifecycle** — `FORMING`, `AWAITING_CONFIRMATION`,
  `CONFIRMED_PATTERN`, `INVALIDATED`, `EXPIRED`, `UNVERIFIABLE`, with immutable
  rows (frozen provenance + SHA-256 digest) and one-shot outcome recording.
* **Approval gate** — a directional (UP/DOWN) signal exists **only** when the
  strategy is `decision_use_approved` **and** `research_status == "approved"`.
  Every other result is a pattern observation with direction `none`.
* **Dashboard** — premium, responsive, dark-first pages consistent with the
  frontend design system: monitoring status, feed health, counters, filters
  (strategy/instrument/timeframe/category/status/outcome), recent history and an
  on-demand detail panel.
* **Live updates** — HTMX polling of two narrow fragments (status + feed) that
  preserve active filters and swap only their own container.
* **Notifications** — in-app `SignalAlert`s deduplicated structurally by
  `(user, signal)`; browser notifications set a flag only with explicit user
  permission. No external messaging service is contacted or claimed.
* **Paper outcome tracking** — outcomes are the next-candle close direction of
  the same feed; incompatible/OTC instruments are marked `UNVERIFIABLE`. Metrics
  keep **recognition** and **directional** families strictly separate, with a
  Wilson interval and an explicit insufficiency flag.

## 3. Honesty guarantees (enforced, not just documented)

| Guarantee | Enforcement |
| --- | --- |
| Closed candles only | `_finalise` re-derives completeness from time; `last_candle_forming=False` |
| No unapproved direction | `categorise()` requires both approval flags |
| No duplicate signal | unique `(monitor, strategy_key, candle, status)` + evaluated-candle marker |
| No rewritten signal | `save()` guard raises `SignalImmutableError`; one-shot outcomes |
| No OTC substitution | `check_feed_type_compatibility`; mismatch ⇒ `INCOMPATIBLE` / `UNVERIFIABLE` |
| No invented confidence | `probability_status` is always `UNAVAILABLE_UNCALIBRATED` |
| No fake data | empty/unavailable feed ⇒ zero signals and `UNAVAILABLE`/`DEGRADED` |
| No gate widening via preferences | `only_approved`/`show_experimental` filter the view only |
| No real-money trading | no order-placement code exists in the app |

## 4. Test results

* Phase 15 suite: `tests/test_phase15_live_signals.py` — **54 passed**.
* Targeted regression suites (book strategies, pages, screenshot eval,
  settings): **154 passed**.
* **Full suite:** 1293 passed, 3 skipped (see §7).

## 5. New / changed surface

* New app `apps/live_signals` (constants, models, admin, tasks, page_views,
  services, management command, migration).
* New dashboard routes under the `dashboard` namespace:
  `live-signals`, `live-signals-feed`, `live-signals-status`,
  `live-signals-outcomes`, `live-signals-settings`, `live-signal-detail`,
  `live-signal-alert-read`.
* New icon symbols: `icon-activity`, `icon-broadcast`, `icon-arrow-up`,
  `icon-arrow-down`, `icon-shield-check`, `icon-pause`.
* New nav entry “Live Signals” (Workspace group) + breadcrumbs.
* Settings: `LIVE_SIGNAL_MONITORS`, `LIVE_SIGNAL_PROVIDER`,
  `LIVE_SIGNAL_POLL_SECONDS`; beat entry `live-signals.monitor-minute`; task
  route `live_signals.*` → `market` queue.

No existing `{% url %}` name, view signature, HTMX endpoint, upload field or
permission was changed.

## 6. Unavailable integrations (documented, not faked)

* **Live MT5 feed** — the `mt5` provider requires a Windows host with a
  connected terminal; in this environment the default `db` provider is used, so
  the monitor reports `UNAVAILABLE` until real candles are persisted. No price
  is invented.
* **Real OTC feed** — none exists in the project; OTC instruments are therefore
  marked `UNVERIFIABLE` rather than verified against an incompatible feed.
* **External messaging** (SMS/email/push) — not integrated and not claimed.
* **Django Channels push** — Channels is configured with an in-memory fallback;
  Phase 15 uses HTMX polling as the reliable live-update path per the brief.

## 7. Verification

```
.venv\Scripts\python.exe -m pytest tests/test_phase15_live_signals.py -q   # 54 passed
.venv\Scripts\python.exe -m pytest -q                                      # full suite
.venv\Scripts\python.exe -m ruff check apps/live_signals                    # clean
.venv\Scripts\python.exe manage.py check                                    # no issues
```

* Full suite: **1293 passed, 3 skipped** (the 3 skips are the pre-existing
  PostgreSQL-semantics and live-LLM opt-in tests).
* Page render smoke checks pass for all new routes (see
  `TestDashboardViews`).
