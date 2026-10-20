# Phase 15 — Live Signals Architecture

Automatic, closed-candle signal monitoring for **Nazbeen Academy Binary Ai
Asisstance**.

> **Scope.** Live signals are research and paper-monitoring records. The monitor
> never places trades, never assigns a probability, and only an explicitly
> approved strategy can carry a direction. Nothing in Phase 15 changes the
> existing decision engine, the strategy approval gates, or any trade logic.

---

## 1. Why a new app

Phase 15 is net-new: before this phase there was no `Signal`/`Alert` model and
no periodic monitoring task anywhere in the project. The monitors reuse the
**existing** deterministic detectors rather than duplicating strategy logic, but
the persistence, lifecycle, alerts and dashboard are new. They live in a
dedicated app, `apps/live_signals`, so the screenshot, book-strategy and
research concerns stay separate.

## 2. Component map

```
apps/live_signals/
├── constants.py              enumerations, timeframes, disclaimers, invariants
├── models.py                 InstrumentMonitor, LiveSignal, SignalAlert,
│                             UserMonitorSettings (immutable signal + digest)
├── tasks.py                  Celery: live_signals.run_monitors (beat, 45s)
├── page_views.py             dashboard pages + HTMX fragments
├── services/
│   ├── providers.py          CandleProvider interface + db / mt5 providers
│   ├── matching.py           eligibility, categorisation, strategy matching
│   ├── monitor.py            the orchestration engine (one pass per monitor)
│   ├── alerts.py             in-app alerts with structural deduplication
│   ├── metrics.py            recognition vs directional metrics (never merged)
│   └── dashboard.py          read-models for the UI
└── management/commands/
    └── run_live_monitor.py   manual one-shot run for smoke tests
```

## 3. Data flow

```
Celery beat (45 s)  ──▶  live_signals.run_monitors
                              │
                              ▼
                    ensure_monitors()  ── InstrumentMonitor rows (shared)
                              │
                     for each enabled monitor
                              │
                              ▼
                    CandleProvider.fetch_closed()   ← closed candles only
                              │
                ┌─────────────┼───────────────────────────┐
                ▼             ▼                           ▼
        feed health     duplicate check            matching engine
        (ok/stale/     (last_evaluated_          (eligible strategies
         unavailable/   candle_open_time)         × closed candles)
         incompatible)         │                           │
                               ▼                           ▼
                        skip already-        MatchedSignal  ──▶  LiveSignal
                        evaluated candle                        (immutable)
                               │                           │
                               ▼                           ▼
                        expire + resolve          create_alerts_for_signal
                        outcomes (one              (deduplicated per event)
                        compatible candle
                        later)
```

## 4. Candle providers

The monitor never talks to a data source directly. It asks a
`CandleProvider` (defined in `services/providers.py`) for **closed** candles:

| Provider | Name | Behaviour |
| --- | --- | --- |
| `DatabaseCandleProvider` | `db` (default) | Reads `MarketCandle` rows already persisted by the existing MT5 sync / HTTP ingest. Makes **no** assumption a live terminal is present; missing data is reported `UNAVAILABLE`. |
| `MT5GatewayCandleProvider` | `mt5` | Optional; fetches through the existing `MetaTrader5Client` at monitor time. Only usable on a Windows host with a connected terminal; any failure degrades to `UNAVAILABLE`. |

`_finalise()` re-derives completeness from the candle's open time, the timeframe
duration and the current UTC time using the existing
`apps.market_data.services.candle_service.is_candle_complete`. A provider that
wrongly marks a forming bar complete therefore **cannot** slip it past the
monitor. New authorized feeds are added by registering another class in the
`PROVIDERS` registry — no strategy logic changes.

## 5. Supported timeframes

Monitoring is restricted to the low timeframes the brief names, in
`constants.MONITORABLE_TIMEFRAMES`:

```
M1, M2, M3, M5, M15
```

The wider `Timeframe` enum (which also has M30/H1/H4/D1) remains for storage, but
monitors reject anything outside the five above. `TIMEFRAME_SECONDS` drives the
staleness and expiry windows.

## 6. Persistence and recovery

* `InstrumentMonitor` is deduplicated by `(instrument, timeframe, market_type)`,
  so two users watching the same market share one row.
* `last_evaluated_candle_open_time` is committed after each pass. A worker
  restart therefore resumes from the last processed candle instead of
  re-evaluating or skipping candles.
* `consecutive_failures`, `last_error` and `state` implement bounded retries:
  after `MAX_CONSECUTIVE_FAILURES` (5) a monitor is marked `ERROR` and skipped
  until an operator re-enables it.
* Duplicate signals are impossible: a unique constraint on
  `(monitor, strategy_key, signal_candle_open_time, status)` makes re-runs
  idempotent.

## 7. OTC and feed compatibility

The monitor reuses
`apps.market_data.services.symbol_mapper.check_feed_type_compatibility`. An OTC
instrument can **never** be satisfied by a regular feed (or vice versa). When a
monitor's market type and its instrument's OTC nature disagree:

* the feed is marked `INCOMPATIBLE`,
* no signal is produced, and
* any existing pending outcomes for that monitor are marked `UNVERIFIABLE`
  rather than guessed.

This is the same rule the rest of the project already applies — Phase 15 adds no
way to bypass it.

## 8. Live updates

The dashboard uses **HTMX polling** as the reliable fallback (the project has
Django Channels configured with an in-memory fallback, but the brief prefers a
reliable path). Two fragments poll independently:

* `dashboard:live-signals-status` (monitor/feed summary), and
* `dashboard:live-signals-feed` (filtered signal feed).

Both poll on the same interval (`LIVE_SIGNAL_POLL_SECONDS`, default 15 s), swap
only their own container, and preserve the active filters through the querystring
so a poll never resets a user's view. The signal-detail panel is fetched on
demand, not polled.

## 9. Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `LIVE_SIGNAL_MONITORS` | `[]` | `"CANONICAL:TIMEFRAME[:market_type]"` entries the system watches. Empty → the monitor reports `UNAVAILABLE` rather than pretending. |
| `LIVE_SIGNAL_PROVIDER` | `db` | Default candle provider (`db` or `mt5`). |
| `LIVE_SIGNAL_POLL_SECONDS` | `15` | HTMX poll interval for the dashboard fragments. |

The Celery beat entry `live-signals.monitor-minute` runs
`live_signals.run_monitors` every 45 seconds on the `market` queue.

## 10. Explicit non-goals

* **No real-money execution.** No order placement exists in this app.
* **No fabricated data.** No price, signal, metric or statistic is invented; an
  empty feed is shown as empty.
* **No approval bypass.** `decision_use_approved` is the only switch that can
  produce a directional signal, and it is only ever set by explicit human
  approval (unchanged from Phase 13).
* **No external messaging.** In-app alerts only; browser notifications require
  explicit user permission and no external service is contacted or claimed.
