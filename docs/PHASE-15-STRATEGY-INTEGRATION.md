# Phase 15 — Strategy Integration

Which existing strategy logic the live monitor reuses, and exactly when a
detector result may become a signal.

---

## 1. No logic is duplicated

The monitor does **not** reimplement any pattern detection. Matching delegates
to the Phase 13 service:

```python
apps.book_strategies.services.recognition.BookStrategyRecognizer.evaluate(
    key, candles, *, instrument, timeframe, market_type,
    last_candle_forming=False, persist=False,
)
```

which in turn calls the deterministic detector registry
`apps.book_strategies.services.detectors.BOOK_DETECTORS`. Each detector is a
pure function `detector(candles, *, last_candle_forming=False) -> BookPatternResult`
and returns one of the explicit states:

`FORMING`, `AWAITING_CONFIRMATION`, `CONFIRMED_PATTERN`, `INVALIDATED`,
`INSUFFICIENT_DATA`.

The monitor reads those states; it never invents one.

## 2. Detectors available to the monitor

Ten catalog strategies ship with a deterministic detector (Phase 13 priority):

| Catalog key | Detector | Name | Book market type | Trade type |
| --- | --- | --- | --- | --- |
| `SS1` | `ss1` | Sequence Breakout Continuation | trending / ranging | continuation |
| `SS2` | `ss2` | Magic V | trending / ranging | continuation |
| `SS3` | `ss3` | Magic V Advanced | trending | continuation |
| `SS5` | `ss5` | Four-Candle Pullback Hold | trending | continuation |
| `SS6` | `ss6` | Four-Candle Body Breakout | trending | continuation |
| `SS19` | `ss19` | Doji-Level Breakout | trending | reversal |
| `SS21` | `ss21` | Five-Candle Reference-Candle Breakout | trending | continuation |
| `SS22` | `ss22` | Rising Three Method | trending | continuation |
| `SS23` | `ss23` | Falling Three Method | trending | continuation |
| `CH7_S1` | `ch7_s1` | EMA5 + Parabolic SAR + Stochastic Alignment | trending | continuation |

Every other catalogued book strategy has `detector_key == ""` and is
`INSUFFICIENT_DATA` under evaluation — it is never a signal. The monitor only
evaluates strategies whose `recognition_enabled` admin switch is on, which is
the same gate the Phase 13 recognition runs use.

## 3. Eligibility gates (all must hold)

`services/matching.check_eligibility`:

1. **Timeframe** is one of `M1, M2, M3, M5, M15`.
2. **Recognition enabled** — `BookStrategy.recognition_enabled` is True.
3. **Detector exists** — `BookStrategy.detector_key` is non-empty.
4. **Feed compatible** — the feed's OTC nature matches the instrument's, via the
   existing `check_feed_type_compatibility`. A mismatch is refused, never
   coerced.

And per candle series (in `match_strategy`):

5. **Candles available** and every candle used is **closed**.
6. **Detector state is not `INSUFFICIENT_DATA`** (too few closed candles → no
   signal, not a fabricated one).

## 4. Categories and the approval gate

`services/matching.categorise` maps a detector state + strategy flags onto one
of the three brief categories:

| Condition | Category | Carries direction? |
| --- | --- | --- |
| `CONFIRMED_PATTERN` **and** `decision_use_approved` **and** `research_status == "approved"` | `RESEARCH_VALIDATED` | **Yes** (bullish/bearish) |
| `CONFIRMED_PATTERN` (not approved for decisions) | `CONFIRMED_PATTERN` | No (`none`) |
| `FORMING` / `AWAITING_CONFIRMATION` | `EXPERIMENTAL_PATTERN` | No (`none`) |
| `INVALIDATED` | stored as `INVALIDATED` status | No (`none`) |
| `INSUFFICIENT_DATA` | not persisted | — |

The approval switch is the exact same `BookStrategy.decision_use_approved` flag
the decision engine already honours in
`apps.book_strategies.services.decision_integration`. Phase 15 adds no second
approval path and no way to set it except explicit human approval.

An unapproved strategy may therefore appear as a **pattern alert**, but never as
an approved directional signal. The `approval_status` string is copied onto each
row for audit (`approved_for_decision_use` or `not_approved (<research_status>)`).

## 5. Decision and probability

Every signal records:

* `decision = "NO_TRADE"` — a recognised pattern is an observation, not a trade
  prediction; the decision engine's own safeguards are untouched.
* `probability_status = "UNAVAILABLE_UNCALIBRATED"` — the monitor never produces
  a confidence percentage. No probability field is populated.

## 6. Recognition vs directional, kept separate

The same discipline as Phase 13's validation machinery:

* **Recognition metrics** count detections (`total_patterns`,
  `confirmed_patterns`, `invalidated`, `expired`, `experimental`) and make no
  correctness claim.
* **Directional metrics** score only `RESEARCH_VALIDATED` signals, using their
  next-candle paper outcome, reported with a Wilson interval and an
  `insufficient` flag below `DEFAULT_MIN_SIGNALS` (30). Ties and unverifiable
  outcomes are counted separately and never folded into the hit rate.

## 7. What the monitor deliberately does not do

* It does not evaluate a forming candle, even if the detector would confirm on
  it (`last_candle_forming` is always `False` and completeness is re-derived).
* It does not "re-arm" an old pattern as a new live signal: each signal is tied
  to the specific closed candle it was detected on, and the unique constraint
  prevents backfilling the same candle twice.
* It does not substitute an OTC feed or guess an OTC outcome.
* It does not let a user setting promote an unapproved strategy
  (`only_approved` and `show_experimental` can only *narrow* what is shown).
