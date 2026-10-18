# PHASE 7 — IMPLEMENTATION CHECKLIST: Historical Backtesting and Probability Calibration

**Project:** Nazbeen Academy Binary Ai Asisstance
**Phase:** 7
**Status:** In Progress

## STEP 1 — AUDIT PREVIOUS PHASES ✅
- [x] Phases 1-6 verified complete
- [x] Tests pass (497 passed, 2 skipped)
- [x] Migrations clean, system checks pass
- [x] Strategy evaluation engine functional

## STEP 2 — CREATE RESEARCH MODULES
- [ ] Create `apps/research/` app (or `research/` package structure)
- [ ] Create directory structure: models.py, services/, tests/, schemas/, migrations/, admin.py, views.py, urls.py, apps.py
- [ ] Register in INSTALLED_APPS
- [ ] Add URL routes

## STEP 3 — HISTORICAL DATA MANAGEMENT
- [ ] Models for HistoricalDataset, HistoricalCandle, DataQualityIssue
- [ ] DatasetBuilder service - import/validate OHLC
- [ ] Validation: gaps, duplicates, OHLC validity, timezone, feed changes
- [ ] Never fabricate missing data

## STEP 4 — POINT-IN-TIME STRATEGY REPLAY
- [ ] HistoricalReplay service - event-driven replay with no future leakage
- [ ] SignalReconstructor - reconstruct signals at evaluation points using only available data
- [ ] Prevent lookahead in all detectors

## STEP 5 — SCREENSHOT TRACKS
- [ ] Track A (OHLC-only), Track B (vision accuracy), Track C (end-to-end) - separate metrics

## STEP 6 — DIRECTIONAL OUTCOMES
- [ ] DirectionalOutcomes service - identify target candle, classify UP/DOWN/TIE/UNCERTAIN
- [ ] Explicit doji/tie policy

## STEP 7 — BINARY SETTLEMENT
- [ ] BinarySettlement service + PayoutEngine
- [ ] CALL/PUT, entry/expiry/settlement, win/loss/tie
- [ ] Mark as UNVERIFIABLE if target-platform data unavailable; don't substitute MT5 silently

## STEP 8 — PERFORMANCE METRICS
- [ ] PerformanceMetrics calculator (accuracy, win rate, expectancy, drawdown, streaks, by segments)
- [ ] Include uncertainty intervals and sample counts

## STEP 9 — BASELINES
- [ ] BaselineComparison against naive/random/momentum/mean-reversion on same periods

## STEP 10 — DATASET PARTITIONING
- [ ] Chronological splits (train/val/test), walk-forward validation
- [ ] No random shuffle, prevent leakage

## STEP 11 — PROBABILITY MODEL
- [ ] ProbabilityModel (interpretable baseline first - logistic regression/empirical)
- [ ] Features from pre-prediction data only

## STEP 12 — CALIBRATION
- [ ] ProbabilityCalibrator (Platt/isotonic), Brier/log-loss, reliability, calibration error
- [ ] Separate calibration data from fitting/test

## STEP 13 — ABSTENTION POLICY
- [ ] Abstention rules with reason codes (strategy/data/statistical/expired)

## STEP 14 — MODEL REGISTRY
- [ ] ModelRegistry to store/version models, datasets, periods, approval status, rollback

## STEP 15 — RESEARCH DASHBOARD
- [ ] Views/templates for datasets, backtests, performance, calibration, models

## STEP 16 — API ENDPOINTS
- [ ] POST/GET backtests, performance, calibration, models

## STEP 17 — TESTS
- [ ] Comprehensive tests for ordering, leakage, outcomes, settlement, splits, calibration

## ACCEPTANCE
- [ ] All components implemented, tested, Ruff clean, docs updated, report created
