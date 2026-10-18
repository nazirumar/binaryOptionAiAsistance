# PHASE 12 CHECKLIST — Strategy Knowledge & Screenshot Pattern Recognition

Date: 2026-10-18. Status: COMPLETE — awaiting user approval (CP17 report written).
This file records the CP0 repository audit (coverage matrix) and the checkpoint
progress. Detectors are deterministic observations only; nothing here changes
the NO TRADE policy or the decision engine.

## CP0 — Repository audit (coverage matrix)

### Existing deterministic detectors (apps/price_action/services/)

| Area | Existing | Missing for Phase 12 |
| --- | --- | --- |
| Candlestick | bullish/bearish engulfing, hammer, shooting star, doji, bullish/bearish harami, inside bar, outside bar, piercing, dark cloud cover, morning star, evening star, three white soldiers, three black crows | bullish/bearish pin bar, inverted hammer, hanging man, dragonfly doji, gravestone doji, spinning top, tweezer top, tweezer bottom |
| Support/resistance | zones (clustered, multi-touch), wick rejection, breakout close-confirmation, retest, SBR/RBS (valid break + retest), invalidation | staged SBR/RBS lifecycle (formation→break→retest→acceptance/rejection→completed/invalidated), false breakout at a zone, failed support/resistance test, engulfing-at-level, doji above/below validated level, support/resistance rejection strategies |
| Market structure | swings (no look-ahead), HH/HL/LH/LL labels, trend inference, BOS, failed breakout, consolidation | CHOCH, MSS, trend exhaustion, reversal candidate, failed structural break distinction, narrative builder |
| Liquidity / ICT | prev-high/low sweeps, sweep outcomes, FVG (3-candle, states, sweep confluence), order blocks (teacher + ICT definitions, lifecycle) | equal highs/lows, swing-point sweeps, inducement, displacement, FVG retest, breaker block, mitigation, premium/discount zones |
| Market cycle | motive/counter/reversal candidates from swing labels, documented ambiguities | candle progress, run count, strong/weak close, failed continuation |
| Buyer/seller failure | support/resistance creation events, attempts & failures, source strength | (covered; wire to knowledge DB) |
| Sequences | reference runs, similar sequences (past-only), lonely candles, 8 psych templates as hypotheses | (covered; wire to knowledge DB) |
| Candle geometry | ratios, strength classification, rejection footprint, sweep candidacy | (covered) |
| ABC formation | — | generic ABC pivot detector (CP7) |

### Existing vision pipeline (apps/chart_vision)

- Models: ChartScreenshot, ScreenshotAnalysis, VisionObservation,
  DetectedPattern, DetectedPriceZone, VisionProcessingEvent.
- Schema v1 validator: strips fabricated OHLC numbers, forbids probability
  fields, clamps confidence. Candles carry *reliable pixel coordinates*
  (high_px/low_px/body_top_px/body_bottom_px) when the model reports them.
- pattern_observer converts payload → observations/patterns/zones.
- Missing: strategy-candidate recognition, deterministic verification layer,
  visual annotation, dataset workflow, metrics.

### Existing strategy engine / assistant / dashboard

- strategy_engine: decision engine owns UP/DOWN/NO TRADE (untouched).
- ai_assistant: reasoning provider (Groq/Gemini), conversation models.
- dashboard: vision upload/analyze/status pages exist; knowledge page exists.
- research: knowledge entries (separate concept from strategy definitions).

### Duplicate implementations

- `detect_ob` is a backwards-compatible alias of `detect_order_blocks`; `body_ratio`
  aliases `body_range_ratio`; `detect_market_cycle` aliases `classify_cycle`.
  Kept for compatibility — Phase 12 adds no new duplicates.

### Visual annotation support

- None existing. CP13 adds PIL annotation that consumes only model-reported
  pixel coordinates or level coordinates; original images are never modified.

## Checkpoints

- [x] CP0 repository audit (this file)
- [x] CP1 strategy knowledge database (apps/strategy_knowledge)
- [x] CP2 candlestick pattern library (9 new detectors)
- [x] CP3 support/resistance strategies (staged SBR/RBS, false breaks, …)
- [x] CP4 market structure (CHOCH, MSS, exhaustion, candidates)
- [x] CP5 liquidity & ICT (equal levels, inducement, breaker, premium/discount…)
- [x] CP6 cycles & candle psychology (progress, close quality, failed continuation)
- [x] CP7 ABC pattern (generic, labelled generic)
- [x] CP8 vision strategy recognition (candidates w/ provenance)
- [x] CP9 PatternVerificationService (DETECTED/POSSIBLE/REJECTED/INSUFFICIENT)
- [x] CP10 multi-strategy recognition + dedup
- [x] CP11 knowledge retrieval for the assistant
- [x] CP12 strategy library dashboard pages
- [x] CP13 pattern visualisation (coordinate-safe annotation)
- [x] CP14 strategy dataset workflow (reviewer-approved labels)
- [x] CP15 detection validation metrics (precision/recall/F1; separate from prediction)
- [x] CP16 tests (new + full regression: 1025 passed / 3 skipped)
- [x] CP17 completion report (docs/PHASE-12-COMPLETION-REPORT.md)

Knowledge-base seed: `python manage.py seed_strategy_knowledge` creates one
knowledge-only definition per registry key (all draft, all disabled, honest
validation notes) plus the deterministic vision-label mappings. Idempotent.

## Design guardrails (Phase 12)

1. Strategy rules are structured data validated against whitelisted schemas;
   no arbitrary Python expressions are ever evaluated from the database.
2. `detector_key` on a definition maps into a fixed registry of deterministic
   functions — unknown keys are inert (the definition cannot run).
3. Vision candidates are never "confirmed" by the LLM naming a pattern;
   confirmation requires deterministic OHLC evidence or is labelled
   screenshot-only/possible.
4. OTC feeds are never confirmed with normal MT5 prices.
5. Experimental/unapproved definitions cannot influence decisions; the
   decision engine is not modified.
