"""Phase 16 Checkpoint 3 - independent book-detector audit.

For every implemented detector (the ten priority strategies) this harness
reports, using independently reviewed fixtures:

  A. the reviewed positive example -> expected CONFIRMED_PATTERN + direction;
  B. deliberately constructed lookalikes -> expected NOT confirmed;
  C. truncation invariance (no lookahead): a detection at index i must be
     reproducible from the prefix candles[:i+1] alone;
  D. real-feed firing rate: how often each detector confirms on the actual
     stored EURUSD candles (no expectation - just what really happened).

The detector rules are NOT changed here: this is an audit, not a rewrite.

Run:  .venv\\Scripts\\python.exe scripts\\phase16_detector_audit.py
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from apps.book_strategies.constants import BookPatternState  # noqa: E402
from apps.book_strategies.services.detectors import (  # noqa: E402
    BOOK_DETECTORS,
    detect_ch7_s1,
    detect_ss1,
    detect_ss19,
    detect_ss22,
)
from apps.market_data.models import MarketCandle  # noqa: E402


def _load_fixtures():
    """Import the reviewed fixture builders from the test module."""
    sys.path.insert(0, str(ROOT / "tests"))
    import test_book_strategies as t

    return t


def section(title: str) -> None:
    print()
    print("=" * 74)
    print(title)
    print("=" * 74)


def main() -> int:
    t = _load_fixtures()
    confirmed = BookPatternState.CONFIRMED_PATTERN

    # --- A. reviewed positive examples -------------------------------------
    section("A. REVIEWED POSITIVE EXAMPLES (expect CONFIRMED + direction)")
    positives = [
        ("ss1", detect_ss1, t.ss1_up_series, "bullish"),
        ("ss3", BOOK_DETECTORS["ss3"], t.ss1_up_series, "bullish"),
        ("ss2", BOOK_DETECTORS["ss2"], None, "bullish"),  # needs decider append
        ("ss5", BOOK_DETECTORS["ss5"], t.ss5_up_series, "bullish"),
        ("ss6", BOOK_DETECTORS["ss6"], t.ss6_up_series, "bullish"),
        ("ss19", detect_ss19, t.ss19_series, "bearish"),
        ("ss21", BOOK_DETECTORS["ss21"], t.ss21_series, "bullish"),
        ("ss22", detect_ss22, t.ss22_series, "bullish"),
        ("ss23", BOOK_DETECTORS["ss23"], t.ss23_series, "bearish"),
        ("ch7_s1", detect_ch7_s1, t.legs, "bullish"),
    ]
    passed = 0
    for key, fn, builder, expect_dir in positives:
        if key == "ss2":
            base = t.ss1_up_series()
            level = max(base[-2]["high"], base[-1]["high"])
            candles = [*base, t.candle(level + 0.0009, level + 0.0014,
                                       level + 0.0008, level + 0.0013)]
        else:
            candles = builder()
        r = fn(candles)
        ok = r.state == confirmed and r.direction == expect_dir
        passed += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {key:7} state={r.state:20} "
              f"direction={r.direction:8} (expected {expect_dir})")
    print(f"  -> {passed}/{len(positives)} positive examples confirmed")

    # --- B. negative / lookalike examples ----------------------------------
    section("B. LOOKALIKES / NEGATIVES (expect NOT confirmed)")
    negatives = [
        ("ss5 laid-back", lambda: BOOK_DETECTORS["ss5"](t.downtrend(18))),
        ("ss1 no setup", lambda: detect_ss1(t.uptrend(18))),
        ("ss22 no setup", lambda: detect_ss22(t.legs(cycles=3))),
        ("ss6 wick-only break", lambda: BOOK_DETECTORS["ss6"](t.ss6_up_series(wick_only=True))),
        ("ch7_s1 monotonic (no cross)", lambda: detect_ch7_s1(t.uptrend(24))),
        ("empty series", lambda: detect_ss1([])),
        ("single candle", lambda: detect_ss1([t.candle(1.0, 1.001, 0.999, 1.0005)])),
    ]
    neg_pass = 0
    for label, fn in negatives:
        r = fn()
        ok = r.state != confirmed
        neg_pass += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {label:30} state={r.state:20} "
              f"direction={r.direction}")
    print(f"  -> {neg_pass}/{len(negatives)} lookalikes correctly NOT confirmed")

    # --- B2. forming last candle -------------------------------------------
    section("B2. FORMING LAST CANDLE MUST NEVER CONFIRM")
    series = {
        "ss1": t.ss1_up_series, "ss5": t.ss5_up_series, "ss19": t.ss19_series,
        "ss21": t.ss21_series, "ss22": t.ss22_series, "ss23": t.ss23_series,
    }
    form_pass = 0
    for key, builder in series.items():
        r = BOOK_DETECTORS[key](builder(), last_candle_forming=True)
        ok = r.state != confirmed
        form_pass += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {key:7} forming -> {r.state}")
    print(f"  -> {form_pass}/{len(series)} correctly downgraded when the "
          f"final candle is forming")

    # --- C. no-lookahead / truncation invariance ---------------------------
    section("C. TRUNCATION INVARIANCE (a detection must be reproducible from "
            "the prefix alone)")
    for key, builder in series.items():
        candles = builder()
        full = BOOK_DETECTORS[key](candles)
        if full.state != confirmed or full.completed_at is None:
            print(f"  [SKIP] {key:7} full-series state={full.state} "
                  f"(not a confirmed detection to cross-check)")
            continue
        prefix = candles[: full.completed_at + 1]
        pre = BOOK_DETECTORS[key](prefix)
        ok = pre.state == confirmed and pre.completed_at == full.completed_at \
            and pre.direction == full.direction
        print(f"  [{'PASS' if ok else 'FAIL'}] {key:7} completed_at="
              f"{full.completed_at} full_dir={full.direction} "
              f"prefix_dir={pre.direction} prefix_state={pre.state}")

    # --- D. real-feed firing rate ------------------------------------------
    section("D. REAL-FEED FIRING RATE (actual stored EURUSD candles)")
    strategy_keys = {
        "SS1": "ss1", "SS2": "ss2", "SS3": "ss3", "SS5": "ss5", "SS6": "ss6",
        "SS19": "ss19", "SS21": "ss21", "SS22": "ss22", "SS23": "ss23",
        "CH7_S1": "ch7_s1",
    }
    for timeframe in ("M5", "M1"):
        rows = list(
            MarketCandle.objects.filter(
                symbol__canonical="EURUSD", timeframe=timeframe,
                is_complete=True,
            ).order_by("open_time")
        )
        if not rows:
            print(f"  {timeframe}: no complete candles stored")
            continue
        candles = [
            {"open_time": r.open_time, "open": float(r.open), "high": float(r.high),
             "low": float(r.low), "close": float(r.close)}
            for r in rows
        ]
        print(f"  {timeframe}: {len(candles)} complete candles "
              f"({candles[0]['open_time']} .. {candles[-1]['open_time']})")
        states: Counter[str] = Counter()
        for book_key, det_key in strategy_keys.items():
            r = BOOK_DETECTORS[det_key](candles)
            states[r.state] += 1
            print(f"    {book_key:7} {det_key:7} state={r.state:20} "
                  f"direction={r.direction}")
        print(f"    state tally: {dict(states)}")

    print()
    print("=" * 74)
    print("AUDIT COMPLETE - rules were not modified; results are observations.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
