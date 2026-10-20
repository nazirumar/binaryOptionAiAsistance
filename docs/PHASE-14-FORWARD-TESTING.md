# PHASE 14 — FORWARD PAPER TESTING

Date: 2026-10-20. Status: COMPLETE — delivered for review. Nothing was deployed.

This document covers Checkpoints 4–6: immutable forward paper predictions,
actual outcome verification without feed substitution, and the forward-testing
performance dashboard.

> **No automatic trading, no martingale staking, no real-money execution.**
> Every record here is research. Nothing in Phase 14 enables a trade or approves
> a strategy for decision use.

## Checkpoint 4 — forward paper predictions (immutable, locked)

Workflow enforced by `ForwardPredictionService.record`, in the order the
checkpoint requires:

1. Capture the screenshot — the case already exists (`ScreenshotCase`).
2. Record the exact decision timestamp — `decision_timestamp` (defaults to now
   at write time; the payload asserts `written_before_outcome = True`).
3. Identify instrument + timeframe — taken from the case, never re-guessed.
4. Run pattern recognition — a persisted `ScreenshotRecognitionRun`.
5. Verify eligible strategy conditions — a strategy is eligible only if it is
   **named in the human label** or has a **fresh deterministic
   `CONFIRMED_PATTERN`** recognition. Nothing else qualifies.
6. Record the strategy version — `strategy_version`, frozen for audit.
7. Record `UP` / `DOWN` / `NO TRADE` — `direction`.
8. Store probability only when calibrated — `probability` may only be set with a
   non-default `probability_status`; recognition alone never yields a value
   (attempting `probability=0.7` with the default status raises).
9. Lock the prediction — `payload_sha256` is computed from the canonical
   `prediction_payload` at creation.

`ForwardPaperPrediction` reuses the Phase 13 immutability discipline exactly:

- `PROTECTED_FIELDS` (case, strategy, instrument, timeframe, direction,
  decision timestamp, probability, payload, digest, …) are frozen at creation.
- Editing any protected field re-raises `PredictionLockedError` from `save()`.
- `status` may only change through `verify_outcome()`, which is the single
  transition out of `locked` and can fire at most once.
- `verify_integrity()` recomputes the digest and detects out-of-band tampering
  (asserted by test: a raw `.update()` is caught).

**Never modify a prediction after its outcome becomes known.** The model
enforces it; the review queue and metrics never mutate predictions either.

The candle-driven Phase 13 `PaperForwardPrediction` is untouched and continues
to operate independently.

## Checkpoint 5 — actual outcome verification (no feed substitution)

`OutcomeVerificationService.verify` verifies the result against the **correct**
feed. The rules, in order:

1. **NO TRADE has no outcome.** A `NO TRADE` prediction is recorded as
   `pending` / `unresolved`; the locked prediction is not transitioned.
2. **OTC feed gate (before any arithmetic).** An OTC prediction verified with an
   absent or MT5/regular price source is **refused** with reason code
   `INCOMPATIBLE_FEEDS`. Ordinary MT5 prices are never substituted for IQ Option
   OTC settlement prices.
3. **Reuse of the settlement engine.** For compatible feeds the result reuses
   `BookSettlementService.evaluate` (which itself never substitutes MT5 closes
   for platform expiry). Its `win` / `loss` / `tie` / `refused` / `unverifiable`
   status maps onto `OutcomeVerdict`.
4. **No quote → unverified, never correct.** With no settlement quote the verdict
   is `unverifiable` and the prediction moves to `unverified`; it is excluded
   from accuracy.
5. **Ties recorded separately.** An entry quote equal to the settlement quote is
   a `tie`, not a win.

Outcome verdicts: `correct` / `incorrect` / `tie` / `refused` / `unverifiable` /
`pending`. Prediction terminal statuses: `verified` / `unverified` / `tie`
(plus `locked` / `unresolved`).

`OutcomeVerification` is **write-once**: a second verification returns the first
record unchanged. `counts_as_verified` is true only for `correct` / `incorrect` /
`tie`.

**UNVERIFIED outcomes are excluded from verified accuracy statistics** — never
assumed successful.

## Checkpoint 6 — performance dashboard (two scopes, never mixed)

Page: `/dashboard/forward-testing/` (`templates/dashboard/forward_testing.html`).
Command: `python manage.py screenshot_forward_report [--out report.json]`.

The page and the JSON payload present **two clearly separated scopes**:

### Recognition scope — `pattern_recognition`

- total screenshots / cases analysed, human-labelled cases (ground truth)
- correctly recognised, incorrectly recognised, incomplete formations
  (true/false positives, false negatives, true negatives)
- precision and recall with Wilson 95% intervals
- `insufficient_reason` when below the label threshold; `status =
  NOT_COMPUTABLE_NO_GROUND_TRUTH` when there is no labelled ground truth

Recognition accuracy here means *did the system identify the pattern a human
labelled on the same screenshot*. It never draws on an outcome.

### Prediction scope — `binary_settlement_outcome`

- UP / DOWN / NO TRADE counts
- verified correct and incorrect outcomes
- directional hit rate with a Wilson 95% interval
- ties, unverified, refused and unresolved reported **separately**, and the
  `excluded_from_accuracy` total
- `insufficient_reason` below the verified-outcome threshold

### Segmentation

`ScreenshotMetricsService.by_segment` breaks verified counts out by **strategy,
instrument, timeframe and market type**. Every segment carries its own `total`,
`up`/`down`/`no_trade`, `verified_total`, `verified_correct`, `hit_rate` and
`excluded` count.

### The wall

`assert_scope_separation` raises if a payload leaks the other scope's keys
(a recognition payload carrying `hit_rate`, or a prediction payload carrying
`precision`). The test suite asserts both directions. The page states plainly
that the two are never combined.

## Honesty defaults

- No rate is reported below threshold; insufficiency is explicit.
- `approved_for_decision_use` is always `False`; forward predictions never
  approve a strategy.
- No fabricated statistics: empty datasets yield `None` rates and explicit
  reasons, never a placeholder number.

See `docs/PHASE-14-ERROR-REVIEW.md` and `docs/PHASE-14-COMPLETION-REPORT.md`.
