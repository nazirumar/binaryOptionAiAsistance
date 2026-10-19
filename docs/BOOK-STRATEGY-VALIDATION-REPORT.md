# BOOK STRATEGY VALIDATION REPORT — Phase 13 pilot

Date: 2026-10-18. Status: pilot run over available genuine data. **No strategy
is validated. No approval for decision use is granted or implied.** Artifact:
`docs/artifacts/book_validation.json` (regenerate with
`python manage.py validate_book_strategies --out docs/artifacts/book_validation.json`).

## Dataset

| Item | Value |
| --- | --- |
| Candles used | 300 EURUSD **M5**, complete, `quality_status = ok` (genuine MT5 data from the synced dev database) |
| Candles excluded | 300 EURUSD M1 — excluded because their stored `quality_status` is `suspect`; suspect data is never used for validation claims |
| Burn-in | 20 candles (indicator warm-up, not evaluated) |
| Split | chronological: in-sample = indices 20–214 (194 outcome candles), out-of-sample = 215–299 (85 outcome candles) |
| Metric scope | direction of the **next candle's close**, measured with a hard no-future-leakage rule (signal at *i* uses only candles `[0..i]`) |
| Baseline | unconditional majority direction of the same window (in-sample 53.6% up, out-of-sample 51.8% up, pooled 53.0% up) |
| Threshold | a validation claim would require ≥30 pooled signals **and** ≥30 out-of-sample signals; every result below is `sufficient_data = false` |

**Next-candle direction is NOT binary-option settlement.** Slippage, expiry
timing, payout and spread are not modelled. A hypothetical 80% payout is used
only to illustrate expectancy, and expectancy is reported only when — and
because — `sufficient_data` is false everywhere here, it is `null` for every
strategy.

## Results (genuine data, chronological replay)

| Strategy | Signals (IS / OOS) | Accuracy IS | Accuracy OOS | Pooled accuracy (Wilson 95%) | Pooled baseline | Sufficient? |
| --- | --- | --- | --- | --- | --- | --- |
| SS1 | 18 / 6 | 83.3% (15/18) | 66.7% (4/6) | 79.2% (19/24) [59.5%, 90.8%] | 53.0% | **No** — 24 pooled, 6 OOS |
| SS2 | 25 / 6 | 56.0% (14/25) | 33.3% (2/6) | 51.6% (16/31) [34.8%, 68.0%] | 53.0% | **No** — 6 OOS |
| SS3 | 3 / 0 | 100% (3/3) | — (0 signals) | 100% (3/3) [43.8%, 100%] | 53.0% | **No** — 3 pooled, 0 OOS |
| SS5 | 0 / 0 | — | — | — | 53.0% | **No** — zero signals |
| SS6 | 0 / 0 | — | — | — | 53.0% | **No** — zero signals |
| SS19 | 0 / 1 | — | 0.0% (0/1) | 0.0% (0/1) [0.0%, 79.3%] | 53.0% | **No** — 1 signal |
| SS21 | 0 / 0 | — | — | — | 53.0% | **No** — zero signals |
| SS22 | 0 / 0 | — | — | — | 53.0% | **No** — zero signals |
| SS23 | 0 / 0 | — | — | — | 53.0% | **No** — zero signals |
| CH7_S1 | 3 / 0 | 66.7% (2/3) | — (0 signals) | 66.7% (2/3) [20.8%, 93.9%] | 53.0% | **No** — 3 pooled, 0 OOS |

Hypothetical expectancy per trade: `null` for all ten strategies (insufficient
data). `approved_for_decision_use`: **false** for all ten.

## Honest reading of these numbers

- **Nothing here validates anything.** Every strategy is below the sample-size
  threshold, so the reports mark `sufficient_data = false` with an explicit
  reason; no accuracy figure above is a claim, and none may be quoted as one.
- The apparent SS1 strength (79.2% pooled) rests on 24 signals from a single
  300-candle M5 window of one instrument; its Wilson interval [59.5%, 90.8%]
  is wide, its out-of-sample slice is only 6 signals, and a single-window
  sample cannot separate skill from regime. It would need an order of
  magnitude more clean candles — across instruments and time periods — before
  any claim, and even then next-candle direction ≠ binary settlement.
- SS2 does **not** beat its baseline (51.6% vs 53.0% pooled; 33.3% vs 51.8%
  out-of-sample). This is reported as-is; there is no re-tuning on this data.
- SS3's 3/3 is a rounding error in a 279-candle window, not a result.
- SS19 went 0/1; also not a result.
- SS5, SS6, SS21, SS22 and SS23 produced **zero** completed signals in this
  window — the report states that plainly and invents no accuracy in their
  place (`accuracy = null`, `wilson_95 = [null, null]`).
- The M1 candles were refused validation entirely because the database itself
  flags them `suspect`. Excluding them is the honest behaviour, and it halves
  the available sample — a data-quality debt to fix before any future
  validation attempt.

## What would be required before any validation claim

1. A substantially larger pool of `quality_status = ok` candles (multiple
   instruments and timeframes, weeks of data), with the M1 suspect-flag cause
   diagnosed and fixed at the source.
2. The same frozen replay machinery run unchanged (no per-strategy re-tuning on
   out-of-sample data), reporting pooled and out-of-sample counts, Wilson
   intervals and the baseline comparison for every strategy.
3. Sample sizes reaching the thresholds above, and even then only a
   *next-candle-direction* claim — never a binary-options win-rate claim.
4. Explicit human approval (`decision_use_approved = true`) as a separate,
   deliberate act — nothing in this phase moves that flag, and the dashboard
   toggle explicitly cannot.

Until all of the above hold: **NO TRADE. Probability: unavailable
(uncalibrated).**

---

## Phase 13 continuation — walk-forward, ranking, paper predictions and settlement

The pilot above reported a single chronological split. The continuation added
**walk-forward folds**, a **ranking** service, **immutable paper predictions**
and a **binary-settlement** scope. The genuine-data numbers below were produced
by the real commands against the dev database (300 EURUSD **M5** complete
`quality_status = ok` candles; the 300 M1 `suspect` candles remain excluded).
Artifacts: `docs/artifacts/book_validation.json` (per-strategy),
`docs/artifacts/book_research.json` (backtest + comparison).

### What changed in how numbers are produced

- **Walk-forward** (`BookWalkForwardService`): one causal replay is partitioned
  into chronological, disjoint folds; each fold and the pool carry their own
  signal count, accuracy, Wilson 95% interval and unconditional baseline. No
  detector is re-run per fold, so there is no window leakage.
- **Ranking** (`BookComparisonService`): only rows with *sufficient* validation
  **and** sufficient walk-forward evidence are ranked, by out-of-sample margin
  (accuracy minus baseline) descending, ties by sample size; everything else is
  unranked and sorted by key only. `approved_for_decision_use` is False on every
  row.
- **Metric scopes** (`services/metrics.py`): recognition and prediction are
  hard-walled apart. `recognition_accuracy` is always `None`
  (`NOT_COMPUTABLE_NO_GROUND_TRUTH`); only `next_candle_direction` ever carries a
  number, and that is still **not** binary-option settlement.

### Backtest result (genuine M5 replay)

Ten implemented strategies, pooled signals / next-candle accuracy:

| Strategy | Pooled signals | Accuracy | Sufficient? |
| --- | --- | --- | --- |
| SS1 | 24 | 79.2% | No — 6 out-of-sample |
| SS2 | 31 | 51.6% | No (below baseline) |
| SS3 | 3 | 100% | No — 0 out-of-sample |
| SS19 | 1 | 0.0% | No |
| CH7_S1 | 3 | 66.7% | No |
| SS5, SS6, SS21, SS22, SS23 | 0 | — | No — zero signals |

Result: **0 ranked, 10 unranked.** Every one of the ten was tiered
`insufficient_evidence_unranked`; none reached `candidate_for_further_research`
or even `ranked_but_below_baseline` with a valid claim. No accuracy figure above
is a claim. All ten were advanced to `research_status = backtested` at most —
none to `oos_validated`, none approved.

### Paper forward predictions (genuine, frozen)

The `record_paper_predictions` / `resolve_paper_predictions` commands were run
against the dev database with recognition temporarily enabled for SS1/SS2 (then
returned to the default OFF). One genuine SS1 bullish prediction was frozen with
a SHA-256 payload digest; `verify_integrity()` returns True. It remains
`status = pending` because its outcome candle is not yet complete — the pipeline
**skips** (never fabricates) an unresolved outcome, so no win/loss was invented.
After the run, `recognition_enabled` was set back to empty, so nothing remains
enabled for trading. No settlement could be verified, so the
`binary_settlement` summary is empty, exactly as it should be.

### Settlement scope caveat

A second, deliberate scope exists (`BookSettlementService`): **binary
settlement** (win/loss/tie against a real expiry price). It only ever counts
*verified* settlements; missing quotes yield `UNVERIFIABLE`, and OTC + MT5 data
is **refused** with `INCOMPATIBLE_FEEDS`. This scope is described here for
completeness only — the sample above produced no verified settlements, so it
reports nothing, and it is never conflated with the `next_candle_direction`
figures in the tables.

### Honest reading of the continuation

- Nothing in the continuation validates anything either. The walk-forward folds
  on a 300-candle single-instrument window are far too small; the pooled result
  still says `sufficient_data = false` everywhere, and the ranking service
  correctly returns **zero ranked strategies**.
- SS1's apparent strength is unchanged from the pilot and is still a 24-signal
  single-window artefact; SS2 still does not beat its baseline. Neither is
  re-tuned.
- The paper-prediction path is proven *mechanically* (frozen, digest-verified,
  skip-on-incomplete) but has produced no settled outcomes — which is the
  truthful state, not a result.
- `decision_use_approved` remains False for all entries and nothing advances
  past `backtested`. The gated decision-engine hook (R9) is therefore inert.

**Until real sample sizes exist, across instruments and periods: NO TRADE.
Probability: unavailable (uncalibrated).**
