# Price-Action Knowledge Base — Index

This is the authoritative index of every concept the strategy engine implements. Each
concept is implemented as a deterministic, unit-tested detector in `apps.price_action`
(Phase 5); see [`PHASE-5-REPORT.md`](PHASE-5-REPORT.md) and the machine-readable
`apps/price_action/knowledge/catalogue.py`.

**Nothing here is asserted as fact where the course definition is ambiguous**: such items
are recorded as *configurable research hypotheses* with a proposed measurable
interpretation, and remain `PROPOSED` where unresolved (the two order-block definitions
are the clearest example and are deliberately **not** merged).

Legend: ✅ implemented · 🔬 research hypothesis (proposed measurable interpretation) ·
⚠️ partial / limited · 📋 specified (not yet implemented)

## Market structure — `services/market_structure.py`
- ✅ Bullish / bearish trends (`infer_trend`)
- ✅ Higher highs & higher lows (`label_swings`)
- ✅ Lower highs & lower lows (`label_swings`)
- ✅ Consolidation (`detect_consolidation`)
- ✅ Structure breaks (`detect_structure_break`, plus failed breakouts)
- ✅ Market-cycle transitions (`market_cycle.classify_cycle`)

## Support & resistance — `services/support_resistance.py`, `buyer_seller_failure.py`
- ✅ Support / resistance identification (`detect_zones`)
- ✅ Repeated rejection (`detect_rejection`, touch counts)
- ✅ Buyer & seller source identification (`buyers_create_support`, `sellers_create_resistance`)
- ✅ Buyer failure to break resistance (`detect_failures`)
- ✅ Seller failure to break support (`detect_failures`)
- ✅ Support → resistance · Resistance → support (`detect_sbr_rbs`)
- ✅ Breakout & retest (`detect_breakout_confirmation`, `detect_retest`)
- ✅ Source-failure validation (`source_strength`)

## Candlestick analysis — `services/candle_math.py`, `candlestick_patterns.py`
- ✅ Body & wick analysis (`candle_math`)
- ✅ Candle strength classification (`classify_strength`)
- ✅ Engulfing patterns (bullish / bearish)
- ✅ Harami & inside bars (bullish / bearish harami, inside bar)
- ✅ Outside bars
- ✅ Hammer & shooting star
- ✅ Doji
- ✅ Piercing & dark-cloud
- ✅ Morning & evening stars
- ✅ Multi-candle reversal patterns (three white soldiers, three black crows)

## Sequence analysis — `services/candle_sequences.py`
- ✅ Reference sequences (`analyze_reference_sequences`)
- ✅ Similar sequences (`similar_sequences`, no predictive claim)
- ✅ Lonely candles (`lonely_candles`)
- ✅ Consecutive buyer/seller runs (`directional_runs`, `consecutive_*`)
- ✅ Eight psychological candle sequences (`psych_sequences`)
- ✅ Contradictory sequence filtering (`conflict_detector.detect_conflicts` —
  contradictions are surfaced, never resolved by probability)

## Market cycle — `services/market_cycle.py`
- ✅ Motive waves
- ✅ Counter waves
- ✅ Last-effort moves
- ✅ Failed support/resistance tests (`market_structure.detect_failed_breakout`,
  `buyer_seller_failure.detect_failures`)
- ⚠️ Reversal confirmation (breakout confirmation + failure events; no standalone
  confirmed-reversal detector)

## Liquidity & zones — `services/liquidity_sweeps.py`, `order_blocks.py`, `fair_value_gaps.py`, `opening_gaps.py`
- ✅ Liquidity sweeps (`detect_sweep`)
- ✅ Previous high/low sweeps (`prev_high_sweep`, `prev_low_sweep`)
- ✅ Order-block candidates (`detect_order_blocks`)
  - 🔬 Two course definitions exist (`teacher_pattern`, `ict_style`); kept **separate**
    and never merged. The ICT style additionally requires an imbalance.
- ✅ Fair value gaps (`detect_fvg`, true 3-candle definition; state annotation)
- ✅ Opening gaps (`detect_opening_gaps`, reaction annotation)
- 📋 Trendline rejection
- 📋 Round-number confluence

## Volume — `services/volume_analysis.py`
- ✅ Single-candle effort vs result (`volume_effort_result`)
- ✅ Two-candle volume comparisons (`detect_volume_patterns`)
- ✅ Multi-candle volume sequences (`detect_volume_patterns`)
- ✅ Volume anomalies (high/low volume × narrow/wide range)
- ✅ Reversal volume confirmation (`reversal_pattern_volume_context`)
- ✅ Real vs tick volume never merged (`volume_of`)

## Market conditions — `services/market_context.py`
- ✅ Trading sessions (`classify_session`, `session_overlap`)
- ✅ News avoidance (`news_status`; `UNKNOWN` without a provider — never invented)
- ✅ Market-regime classification (`classify_regime`)
- ✅ Volatility (`classify_volatility`)
- ✅ Data freshness (`freshness_status`)

---

## Required shape of every concept

Every implemented concept provides (and the catalogue records):

1. **Definition** — plain-language statement aligned with the course.
2. **Input requirements** — exact OHLCV/history it needs.
3. **Detection rules** — deterministic thresholds/parameters (all in `PriceActionConfig`).
4. **Interpretation** — bullish/bearish/neutral meaning where applicable.
5. **Invalidation conditions** — what makes the signal void.
6. **Evidence output** — structured, machine-readable evidence (`Evidence`).
7. **Unit tests** — including boundary and negative cases.

Ambiguous definitions are marked `PROPOSED` with a measurable interpretation and default
parameters surfaced in configuration, never hard-coded as fact.
