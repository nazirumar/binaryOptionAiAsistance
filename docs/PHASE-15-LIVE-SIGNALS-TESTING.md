# Phase 15 — Live Signals Testing

Hermetic test suite: SQLite, hand-built candles, an in-memory fake provider, no
network, no MT5, no LLM.

```
tests/test_phase15_live_signals.py     54 tests, all passing
```

Run it with:

```
.venv\Scripts\python.exe -m pytest tests/test_phase15_live_signals.py -q
```

The full project suite is green after Phase 15 (see the completion report).

---

## 1. Test areas mapped to the brief

| Brief requirement | Test class / tests |
| --- | --- |
| Closed-candle-only processing | `TestClosedCandleOnly` — `_finalise` drops forming bars, re-derives completeness from time, `match_strategy` refuses incomplete candles, monitor detects only closed bars |
| Strategy matching | `TestMatching` — confirmed pattern detected, insufficient candles → no signal |
| Invalidation | `TestMatching.test_invalidated_pattern_is_not_directional` (a non-confirmed state never carries a direction) |
| Feed compatibility | `TestFeedCompatibility` — OTC instrument requires OTC feed; mismatch marks the monitor `INCOMPATIBLE` |
| OTC rejection | `TestFeedCompatibility.test_otc_outcome_is_unverifiable` — no compatible feed ⇒ outcomes `UNVERIFIABLE`, never guessed |
| Strategy approval gates | `TestApprovalGates` — unapproved ⇒ no direction; approved + validated ⇒ direction; approved-but-not-validated ⇒ pattern only; recognition disabled ⇒ ineligible |
| Duplicate prevention | `TestDuplicatePrevention` — same candle not evaluated twice, duplicate insert is a no-op, restart recovery from persisted position |
| Worker restarts | `TestDuplicatePrevention.test_restart_recovers_from_persisted_position` |
| User permissions | `TestUserSettings` + `TestDashboardViews.test_detail_is_owner_scoped` — owner scoping; settings can only narrow |
| Live dashboard updates | `TestDashboardViews` — feed/status fragments render, outcomes page separates metrics |
| Notification deduplication | `TestAlerts` — one alert per event, `only_approved` suppresses pattern alerts, owner-scoped read |
| Signal immutability | `TestImmutability` — direction/status frozen, outcome recorded once, digest stable, tamper detected |
| Paper outcome verification | `TestOutcomeResolution` — next-candle direction scored, tie recorded as tie |
| Metrics separation | `TestMetrics` — recognition vs directional never merged; unverifiable not folded into hit rate |
| Feed honesty | `TestFeedHonesty` — unavailable feed creates nothing, provider errors bounded, stale feed flagged |
| Real DB integration | `TestDatabaseProvider` — reads closed `MarketCandle` rows, missing symbol / unsupported timeframe → unavailable |
| Tasks | `TestTasks` — safe with no monitors, alerts on new signal |

## 2. Key invariants the tests pin

* **No signal without closed candles.** `_finalise` rejects a bar whose period
  has not closed even if `is_complete=True` is asserted by a provider.
* **No direction without approval.** Every path that could set a direction is
  behind `decision_use_approved` **and** `research_status == "approved"`.
* **No duplicate signal.** The unique constraint plus the
  `last_evaluated_candle_open_time` marker are both exercised.
* **No rewritten signal.** Frozen-field mutation raises `SignalImmutableError`;
  a final outcome cannot be overwritten.
* **No guessed OTC outcome.** An incompatible feed yields `UNVERIFIABLE`.
* **No widened gate via preferences.** `only_approved` / `show_experimental`
  only filter the view.
* **No fake feed.** Empty/unavailable providers produce zero signals and a
  `UNAVAILABLE`/`DEGRADED` monitor state.

## 3. Notable test doubles

* `FakeProvider` — an in-memory `CandleProvider` returning exactly the candles a
  test hands it, or an explicit unavailable/error result.
* `ss22_series()` / `_legs()` — the Phase 13 candle fixtures, reused so the
  trend gate sees a genuine uptrend and the SS22 detector genuinely confirms.

## 4. What is *not* covered by automated tests (and why)

* **A live MT5 terminal or a real market feed.** `MT5GatewayCandleProvider`
  depends on a Windows terminal and the `MetaTrader5` package; it is exercised
  only through the DB provider and fakes. Its failure path is covered (it
  degrades to `UNAVAILABLE`); its happy path requires an actual terminal.
* **A real Redis/Celery beat worker.** The task functions are called directly in
  tests, with `CELERY_TASK_ALWAYS_EAGER` semantics in the test settings. The beat
  schedule entry itself is configuration, not code.
* **Browser notification delivery.** Only the *flag* (`delivered_browser`) is
  set, with the user's explicit permission; no external service is contacted, so
  there is nothing external to test and none is claimed.

## 5. Regression safety

Phase 15 touches shared configuration (`INSTALLED_APPS`, `CELERY_BEAT_SCHEDULE`,
`CELERY_TASK_ROUTES`), the dashboard URL namespace, the navigation registry and
the icon sprite. The full suite is run after the change to confirm none of these
regressed (see `docs/PHASE-15-COMPLETION-REPORT.md`).
