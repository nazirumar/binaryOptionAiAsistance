# BINARY OPTIONS TRADING BIBLE — STRATEGY CATALOG

Date: 2026-10-18. Source: the supplied book PDF
`ilide.info-binary-options-trading-bible-pr_0128092050102e6628d37de3e31133af.pdf`
(119 pages, untracked in git, never committed). Page references below are PDF
page numbers extracted with pypdf. This catalog is seeded into the database by
`python manage.py seed_book_strategies` (idempotent) and rendered on the
dashboard at `/dashboard/book-strategies/`.

Scope: **30 Sure Shot patterns** (Chapter 6, book pages labelled SS1–SS30) plus
**2 Chapter 7 indicator strategies** (CH7_S1, CH7_S2) — 32 entries total.

## Extraction rules (what was and was not done)

- Every entry keeps the book's own wording in `requirements`; the implementation
  never silently repairs the source. **Contradictions inside the book are
  recorded verbatim** in `contradictions` and rendered on the detail page; the
  ambiguous reading the implementation chose is recorded in `ambiguities`.
- A pattern is only implemented as a deterministic detector when the book gives
  enough information to write one. SS10/SS11 (gap patterns, no minimum gap size
  ever defined) are catalogued but **not implemented** — they evaluate to
  `INSUFFICIENT_DATA / NOT_EVALUATED`, never to a guessed detection.
- A recognised pattern is an **observation, never a prediction**: the structured
  response is always `decision = NO_TRADE`, `probability = null`,
  `probability_status = UNAVAILABLE_UNCALIBRATED`.
- Research status starts at `extracted`; implementing a detector moves it to
  `implemented`. `decision_use_approved` stays **False** for every entry until a
  future validation phase with explicit approval — recognition enablement in
  the admin dashboard never approves decision use.

## Catalog table

Key = stable identifier; Chapter 6 entries are numbered 1–30 (SS\<n\>), Chapter
7 entries are CH7_S1/CH7_S2. "Detector" is the deterministic implementation key
(empty = catalogued only). "C/A" = recorded contradictions / ambiguities.

| Key | # | Name | PDF pp. | Markets | Type | Detector | Priority | C/A |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SS1 | 1 | Sequence Breakout Continuation | 31–33 | trending, ranging | continuation | ss1 | Y | 0/1 |
| SS2 | 2 | Magic V | 34–36 | trending, ranging | continuation | ss2 | Y | 1/1 |
| SS3 | 3 | Magic V Advanced | 37–39 | trending | continuation | ss3 | Y | 1/0 |
| SS4 | 4 | Engulfing + Tailless Candle | 40–43 | trending | continuation | — | — | 0/1 |
| SS5 | 5 | Four-Candle Pullback Hold | 44–48 | trending | continuation | ss5 | Y | 1/0 |
| SS6 | 6 | Four-Candle Body Breakout | 49–53 | trending | continuation | ss6 | Y | 0/1 |
| SS7 | 7 | Green-Red-Green + Pullback | 54–58 | trending | continuation | — | — | 0/1 |
| SS8 | 8 | Colour-Pattern Break Reversal | 59–63 | trending, ranging | reversal | — | — | 0/1 |
| SS9 | 9 | SS8 Continuation Reversal | 64–67 | trending, ranging | reversal | — | — | 0/0 |
| SS10 | 10 | Gap Up/Down Double Trade | 68–70 | trending, ranging, stack | continuation | — | — | 0/1 |
| SS11 | 11 | Gap Fill Counter | 71–73 | trending, ranging, stack | continuation | — | — | 0/1 |
| SS12 | 12 | Doji Direction Follow | 74–76 | ranging, stack | continuation | — | — | 0/1 |
| SS13 | 13 | Three-Candle Doji Reversal | 77–79 | ranging | reversal | — | — | 0/1 |
| SS14 | 14 | Wick Break of Prior Body | 80–81 | ranging | reversal | — | — | 0/1 |
| SS15 | 15 | Hammer → Inverted Hammer Reversal | 82 | trending, ranging, stack | reversal | — | — | 0/1 |
| SS16 | 16 | Inverted Hammer → Hammer Reversal | 83 | trending, ranging, stack | reversal | — | — | 0/0 |
| SS17 | 17 | Headless Red → Tailless Green | 84–85 | ranging, stack | continuation | — | — | 0/1 |
| SS18 | 18 | Tailless Green → Tailless Red | 86–87 | ranging, stack | continuation | — | — | 0/0 |
| SS19 | 19 | Doji-Level Breakout | 88–92 | trending | reversal | ss19 | Y | 0/2 |
| SS20 | 20 | Doji Continuation | 93–97 | trending | continuation | — | — | 0/1 |
| SS21 | 21 | Five-Candle Reference-Candle Breakout | 98–102 | trending | continuation | ss21 | Y | 0/2 |
| SS22 | 22 | Rising Three Method | 103–104 | trending | continuation | ss22 | Y | 0/1 |
| SS23 | 23 | Falling Three Method | 105–106 | trending | continuation | ss23 | Y | 1/0 |
| SS24 | 24 | Increasing Body Exhaustion | 107–108 | trending | reversal | — | — | 0/1 |
| SS25 | 25 | Brazilian Pattern Up | 109–110 | ranging | continuation | — | — | 0/1 |
| SS26 | 26 | Brazilian Pattern Down | 111–112 | ranging | continuation | — | — | 0/0 |
| SS27 | 27 | Brazilian Pattern 3 Up | 113–114 | ranging | continuation | — | — | 1/0 |
| SS28 | 28 | Brazilian Pattern 3 Down | 115–116 | ranging | continuation | — | — | 1/0 |
| SS29 | 29 | Colour Pattern Follow (paired 29/30 up) | 117 | ranging, stack | continuation | — | — | 0/1 |
| SS30 | 30 | Colour Pattern Follow (paired 29/30 down) | 117 | ranging, stack | continuation | — | — | 1/0 |
| CH7_S1 | 1 | EMA5 + Parabolic SAR + Stochastic Alignment | 118 | trending | continuation | ch7_s1 | Y | 0/3 |
| CH7_S2 | 2 | EMA5 + SAR + Donchian + Stochastic Tailless Entry | 119 | trending | continuation | — | — | 0/2 |

All 30 Sure Shot patterns are binary-options framed in the book; the catalog
records `market_types` exactly as claimed (trending / ranging / stack) and the
dashboard labels OTC-only entries distinctly from real-market ones.

## Recorded book contradictions (kept verbatim, never silently repaired)

- **SS2 / SS3**: "Either SS2 or SS3 will work so back test properly" — the book
  never provides a rule for deciding which Magic V variant is active on a given
  day. Both are catalogued separately and implemented as separate detectors with
  the exact entry-timing difference preserved.
- **SS5**: requirement 3 says "wait for 1 opposite colour candle" but the chart
  illustrations label "1 or 2 opposite candle". Both readings are supported; the
  3-opposite-candle invalidation is enforced.
- **SS23**: requirement 4 literally reads "Wait for 1 red candle to engulf all
  three red candle" — a typo, because the mirrored SS22 rule and the down-setup
  illustration show it must be the three GREEN candles. The contradiction is
  recorded; the detector implements the mirror-accurate reading and says so in
  its evidence text.
- **SS27 / SS28**: requirement 3 trades DOWN after a sequence ending in GREEN
  (1 green, 1 red, 2 green) while the mirror SS28 trades UP — the
  direction-to-sequence mapping contradicts the trend logic used everywhere else
  in the book. Recorded, not repaired; not implemented deterministically.
- **SS29 / SS30**: presented as one pattern with one requirement list; they
  cannot be separated from the text alone, so they are catalogued as a single
  undifferentiated section with the conflict recorded.

## Recorded ambiguities and the implementation choices made

Every choice below is an explicit, recorded interpretation — the alternative
reading is preserved in the catalog entry text.

| Entry | Ambiguity in the book | Recorded implementation choice |
| --- | --- | --- |
| SS1 | Level described only as "in between of 2 back to back candles" | Level = max high of the two pair candles |
| SS2 | "place the trade in the same direction" names no reference | Direction = colour of the waited-for candle (chart annotation) |
| SS4 | "Immediately" not quantified beyond the next candle | Next completed candle only |
| SS6 | Requirement says top of the single opposite candle; live example says "Two candles which Ever is the highest point" | Detector uses the single-candle top, ambiguity recorded |
| SS7 | Text says "minimum of 4 green candles"; illustrations say "Minimum 3-4" | Not implemented deterministically (count unresolved) |
| SS8 | Number of alternating candles before the break unspecified | Catalogued only |
| SS10 / SS11 | No minimum gap size defined; genuine gaps rarely exist on continuous FX feeds | Catalogued, **not implemented** — always `NOT_EVALUATED` |
| SS12 / SS13 | "green/red doji" is not standard terminology for a neutral candle | Doji family mapped to vision candidates only, capped at AWAITING |
| SS14 | Only the down direction described; no mirrored up rule | Catalogued only |
| SS15 | Chapter 1 says inverted hammer is bearish "after a long uptrend"; SS15 imposes no trend condition | Recorded; not implemented deterministically |
| SS17 | Headless/tailless candles defined with exact wick/body equalities that almost never occur literally | Recorded; not implemented deterministically |
| SS19 | "same direction" could mean break direction or trend direction (section titles say both); "line at the doji" does not say which doji price | Detector uses break direction and the doji range edges (high/low) as the reference zone |
| SS20 | "Abnormal candle" and "big candle" undefined | Catalogued only |
| SS21 | "Successful breakout" not defined as wick or body; two-line vs one-line level description conflicts with the live example | Detector uses a **closing** break (conservative) at the single trend-side level |
| SS22 | "Engulf" not defined as body-vs-body or full range | Detector requires the full high/low range engulf (stricter reading) |
| SS24 | "The candle size should keep on increasing" not defined | Catalogued only |
| SS25 / SS26 | Sequence-to-direction mapping only shown in illustrations | Catalogued only |
| CH7_S1 | "Strong candle" never defined numerically; "breaks the EMA 5" does not say wick or close; stochastic "80/20" role unclear | Detector: strong = body above median of previous 10 candles (explicit metric); EMA break by close; stochastic gate = %K vs %D direction alignment — all three recorded as explicit readings |
| CH7_S2 | "In upper channel" could mean above midline or upper band; tailless equality needs a tolerance the book never gives | Catalogued, **not implemented** — tolerance unresolved |

## What the catalog never claims

- No win rate, accuracy or expectancy figure appears anywhere in the catalog —
  the book's marketing claims are not transcribed as statistics.
- No entry is `approved_for_decision_use`; enabling recognition for an entry in
  the admin dashboard only allows pattern *observations*, never trades.
- Martingale / loss-recovery is rejected for every entry (`mtg_policy` records
  the book's own stance, including where the book recommends recovery — that
  stance is transcribed as text, never as an implemented behaviour).

## Phase 13 continuation — research instrumentation on top of the catalog

The catalog itself is unchanged (still 32 entries, same keys, same recorded
contradictions/ambiguities, no fabricated statistics). Phase 13 was completed by
adding the *research machinery* that a catalog entry needs before any validation
claim could even be contemplated. None of it changes what an entry asserts:

- **Recognition vs prediction are separated** (`services/metrics.py`). Catalog
  entries produce `pattern_recognition` observations; a `recognition_accuracy`
  is **always `None`** with reason `NOT_COMPUTABLE_NO_GROUND_TRUTH` because the
  book's illustrations are not a labelled dataset. The only scope in which a
  numeric accuracy exists is `next_candle_direction`, which is explicitly **not**
  binary-option settlement.
- **The catalogued-only entries stay catalogued.** The ten implemented detectors
  (`ss1`, `ss2`, `ss3`, `ss5`, `ss6`, `ss19`, `ss21`, `ss22`, `ss23`, `ch7_s1`)
  are the only entries with a `detector_key`; the remaining 22 entries still
  evaluate to `INSUFFICIENT_DATA / NOT_EVALUATED` and never to a guessed
  detection. Nothing here silently promotes a catalogued entry to implemented.
- **Contradictions are still recorded, never repaired.** The continuation code
  reads the same `contradictions` / `ambiguities` fields the catalog documents;
  it does not rewrite them and does not use them to pick a winning reading.
- **Every research artefact is unapproved.** Backtest runs, comparisons, paper
  predictions and settlements all carry `approved_for_decision_use = False`;
  the dashboard toggle still flips only `recognition_enabled`. Advancing a
  `research_status` can move an entry at most to `backtested` — never to
  `oos_validated` and never to approved.
- **The catalog is rendered with a "Research metrics →" link** to
  `/dashboard/book-strategies/research/`, which shows the recognition-scope
  markers, paper-prediction summary, comparison table and dataset provenance
  for the entries above.

See `docs/BOOK-STRATEGY-IMPLEMENTATION-REPORT.md` for the component list and
`docs/BOOK-STRATEGY-VALIDATION-REPORT.md` for the genuine-data numbers.
