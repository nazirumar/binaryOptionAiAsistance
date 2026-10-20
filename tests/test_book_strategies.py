# tests/test_book_strategies.py
"""Phase 13 — Binary Options Trading Bible book strategies.

Covers the 30 Sure Shot patterns + 2 Chapter 7 strategies catalogued from the
supplied PDF, the deterministic detectors for the 10 priority strategies, the
state machine (FORMING / AWAITING_CONFIRMATION / CONFIRMED_PATTERN /
INVALIDATED / INSUFFICIENT_DATA), the screenshot->candidate mapper (which never
invents OHLC and refuses OTC mismatches), the knowledge-grounded explainer, the
no-future-leakage validation machinery, the dashboard pages (staff-only
recognition toggle that never enables trading) and the assistant's bounded
book context.

Hermetic throughout: SQLite, hand-built candles, no network, no MT5, no LLM.
"""

from __future__ import annotations

import pytest

from apps.book_strategies.constants import (
    BOOK_STRATEGIES,
    DECISION_NO_TRADE,
    PROBABILITY_STATUS,
    SPEC_BY_KEY,
    BookPatternState,
    DataVerification,
    ResearchStatus,
)
from apps.book_strategies.models import BookStrategy, BookStrategyDetection
from apps.book_strategies.services import (
    BookStrategyRecognizer,
    build_book_candidates,
)
from apps.book_strategies.services.detectors import (
    BOOK_DETECTORS,
    detect_ch7_s1,
    detect_ss1,
    detect_ss2,
    detect_ss3,
    detect_ss5,
    detect_ss6,
    detect_ss19,
    detect_ss21,
    detect_ss22,
    detect_ss23,
)
from apps.book_strategies.services.explainer import explain
from apps.book_strategies.services.validation import (
    BookValidationService,
    wilson_interval,
)
from apps.price_action.services.indicators import (
    ema,
    parabolic_sar,
    stochastic,
    stochastic_supported,
)
from apps.price_action.services.market_structure import infer_trend
from tests.factories import UserFactory
from tests.pa_fakes import candle, downtrend, uptrend
from tests.vision_fakes import full_payload, make_screenshot

pytestmark = pytest.mark.django_db

VALID_STATES = {
    BookPatternState.FORMING,
    BookPatternState.AWAITING_CONFIRMATION,
    BookPatternState.CONFIRMED_PATTERN,
    BookPatternState.INVALIDATED,
    BookPatternState.INSUFFICIENT_DATA,
}


@pytest.fixture(autouse=True)
def _seed_catalog():
    """The test DB starts empty; seed the catalog for every test."""
    from django.core.management import call_command

    call_command("seed_book_strategies")


# ---------------------------------------------------------------------------
# Fixture builders (verified against infer_trend -> "uptrend")
# ---------------------------------------------------------------------------
def legs(start: float = 1.0, cycles: int = 4, leg: int = 3,
         step: float = 0.0008, pull: float = 0.0005) -> list[dict]:
    """Rising market with real swing structure (3-candle legs).

    Swing highs sit at up-leg tops and swing lows at down-leg bottoms; each
    cycle nets 3*(step-pull) so HH/HL labels exceed the 0.0005 relative
    tolerance -> ``infer_trend`` returns "uptrend".
    """
    out: list[dict] = []
    price = start

    def up_leg() -> None:
        nonlocal price
        for _ in range(leg):
            o = price
            c = price + step
            # low == open (no lower wick) so turn candles never tie the
            # previous leg's extreme (duplicate EQ swings break infer_trend).
            out.append(candle(o, c + 0.0001, o, c))
            price = c

    def down_leg() -> None:
        nonlocal price
        for _ in range(leg):
            o = price
            c = price - pull
            out.append(candle(o, o, c - 0.0001, c))
            price = c

    for _ in range(cycles):
        up_leg()
        down_leg()
    up_leg()
    return out


def ss1_up_series() -> list[dict]:
    """Zigzag + green,red,red + breakout candle: the SS1/SS3 up setup."""
    c = legs()
    base = c[-1]["close"]
    c.append(candle(base, base + 0.0004, base - 0.0001, base + 0.0003))  # green
    pair_top = base + 0.0004
    c.append(candle(base + 0.0003, pair_top, base - 0.0004, base - 0.0003))  # red 1
    c.append(candle(base - 0.0003, base + 0.0001, base - 0.0008, base - 0.0007))  # red 2
    level = max(c[-2]["high"], c[-1]["high"])
    c.append(candle(base - 0.0007, level + 0.0010, base - 0.0008, level + 0.0009))
    return c


def ss5_up_series(*, break_top: bool = False) -> list[dict]:
    """Run of 4 greens + shallow red pullback (+ hold or breaking candle)."""
    c = legs()
    p = c[-1]["close"]
    for _ in range(4):
        o = p
        c.append(candle(o, o + 0.0004, o - 0.0001, o + 0.0003))
        p = o + 0.0003
    c.append(candle(p, p, p - 0.0002, p - 0.00015))  # shallow red pullback, top = p
    if break_top:
        c.append(candle(p - 0.00015, p + 0.0005, p - 0.0003, p + 0.0004))
    else:
        # green hold: touches level p but never exceeds (no break)
        c.append(candle(p - 0.00015, p, p - 0.0002, p))
    return c


def ss6_up_series(*, wick_only: bool = False) -> list[dict]:
    """Run of 4 greens + pullback + (body close above | wick-only touch)."""
    c = legs()
    p = c[-1]["close"]
    for _ in range(4):
        o = p
        c.append(candle(o, o + 0.0004, o - 0.0001, o + 0.0003))
        p = o + 0.0003
    top = max(x["high"] for x in c[-4:])
    c.append(candle(p, p, p - 0.0002, p - 0.00015))  # pullback
    if wick_only:
        c.append(candle(p - 0.00015, top + 0.0008, p - 0.0003, top - 0.0002))
    else:
        c.append(candle(p - 0.00015, top + 0.0008, p - 0.0003, top + 0.0007))
    return c


def ss19_series() -> list[dict]:
    """Run of 4 greens + doji + candle closing below the doji low."""
    c = legs()
    p = c[-1]["close"]
    for _ in range(4):
        o = p
        c.append(candle(o, o + 0.0004, o - 0.0001, o + 0.0003))
        p = o + 0.0003
    doji_lo, doji_hi = p - 0.0003, p + 0.0003
    c.append(candle(p - 0.0002, doji_hi, doji_lo, p - 0.00015))  # doji
    c.append(candle(p - 0.00015, p - 0.0001, doji_lo - 0.0009, doji_lo - 0.0008))
    return c


def ss21_series() -> list[dict]:
    """Run of 5 greens + red reference + close above the reference high."""
    c = legs()
    p = c[-1]["close"]
    for _ in range(5):
        o = p
        c.append(candle(o, o + 0.0004, o - 0.0001, o + 0.0003))
        p = o + 0.0003
    ref_top = p + 0.0003
    c.append(candle(p, ref_top, p - 0.0005, p - 0.0004))  # red reference
    c.append(candle(p - 0.0004, ref_top + 0.0009, p - 0.0005, ref_top + 0.0008))
    return c


def ss22_series() -> list[dict]:
    """Rising three: 3 greens + 3 contained reds + engulfing green."""
    c = legs()
    p = c[-1]["close"]
    for _ in range(3):
        o = p
        c.append(candle(o, o + 0.0004, o - 0.0001, o + 0.0003))
        p = o + 0.0003
    g_top = max(x["high"] for x in c[-3:])
    g_lo = min(x["low"] for x in c[-3:])
    for _ in range(3):
        o = p
        c.append(candle(o, o + 0.0001, o - 0.0003, o - 0.0002))
        p = o - 0.0002
    c.append(candle(g_lo, g_top + 0.0004, g_lo - 0.0001, g_top + 0.0003))
    return c


def ss23_series() -> list[dict]:
    """Falling three mirror: 3 reds + 3 contained greens + engulfing red."""
    c = legs()
    p = c[-1]["close"]
    for _ in range(3):
        o = p
        c.append(candle(o, o + 0.0001, o - 0.0004, o - 0.0003))
        p = o - 0.0003
    r_top = max(x["high"] for x in c[-3:])
    r_lo = min(x["low"] for x in c[-3:])
    for _ in range(3):
        o = p
        c.append(candle(o, o + 0.0003, o - 0.0001, o + 0.0002))
        p = o + 0.0002
    c.append(candle(r_top, r_top + 0.0001, r_lo - 0.0004, r_lo - 0.0003))
    return c


# ---------------------------------------------------------------------------
# Catalog (Step 2-4): completeness, page refs, contradictions recorded
# ---------------------------------------------------------------------------
class TestCatalog:
    def test_thirty_two_entries_catalogued(self):
        assert len(BOOK_STRATEGIES) == 32  # 30 Sure Shots + 2 Chapter 7

    def test_every_entry_has_pdf_page_reference(self):
        for spec in BOOK_STRATEGIES:
            assert spec.pdf_pages, f"{spec.key} missing PDF page reference"

    def test_sure_shots_numbered_1_to_30(self):
        numbers = sorted(s.number for s in BOOK_STRATEGIES if s.chapter == "6")
        assert numbers == list(range(1, 31))

    def test_chapter7_has_two_indicator_strategies(self):
        ch7 = [s for s in BOOK_STRATEGIES if s.chapter == "7"]
        assert len(ch7) == 2

    def test_priority_keys_are_implemented(self):
        from apps.book_strategies.constants import PRIORITY_KEYS

        assert set(PRIORITY_KEYS) == {
            "ss21", "ss19", "ss6", "ss22", "ss23", "ss1", "ss2", "ss3",
            "ss5", "ch7_s1",
        }

    def test_implemented_specs_have_detectors(self):
        for spec in BOOK_STRATEGIES:
            if spec.detector_key:
                assert spec.detector_key in BOOK_DETECTORS

    def test_known_contradictions_recorded_not_dropped(self):
        # The brief named these specific book conflicts; they must survive
        # extraction as recorded contradictions, not silent repairs.
        by_key = {s.key: s for s in BOOK_STRATEGIES}
        assert by_key["SS23"].contradictions or by_key["SS23"].ambiguities
        assert by_key["SS5"].contradictions or by_key["SS5"].ambiguities
        assert by_key["SS27"].contradictions
        assert by_key["SS28"].contradictions
        assert by_key["SS29"].contradictions or by_key["SS29"].ambiguities
        assert by_key["SS6"].ambiguities

    def test_gap_patterns_catalogued_but_not_implemented(self):
        by_key = {s.key: s for s in BOOK_STRATEGIES}
        assert by_key["SS10"].detector_key == ""
        assert by_key["SS11"].detector_key == ""

    def test_spec_by_key_covers_all(self):
        assert len(SPEC_BY_KEY) == len(BOOK_STRATEGIES)


# ---------------------------------------------------------------------------
# Detectors (Step 2-3): state machine + positive/negative/incomplete/lookalike
# ---------------------------------------------------------------------------
class TestDetectors:
    def test_fixture_trend_is_uptrend(self):
        assert infer_trend(legs()) == "uptrend"

    # -- positive -----------------------------------------------------------
    def test_ss1_up_confirms(self):
        r = detect_ss1(ss1_up_series())
        assert r.state == BookPatternState.CONFIRMED_PATTERN
        assert r.direction == "bullish"
        assert r.completed_at is not None
        assert r.reference_level is not None
        assert r.missing_conditions == []

    def test_ss3_trades_the_breakout_candle(self):
        r = detect_ss3(ss1_up_series())
        assert r.state == BookPatternState.CONFIRMED_PATTERN
        assert r.direction == "bullish"

    def test_ss2_waits_for_one_candle_and_confirms(self):
        base = ss1_up_series()
        level = max(base[-2]["high"], base[-1]["high"])
        c = [*base, candle(level + 0.0009, level + 0.0014, level + 0.0008, level + 0.0013)]
        r = detect_ss2(c)
        assert r.state == BookPatternState.CONFIRMED_PATTERN
        assert r.direction == "bullish"

    def test_ss2_without_decider_is_awaiting(self):
        r = detect_ss2(ss1_up_series())
        assert r.state == BookPatternState.AWAITING_CONFIRMATION
        assert any("ONE candle" in m for m in r.missing_conditions)

    def test_ss5_up_hold_confirms(self):
        r = detect_ss5(ss5_up_series())
        assert r.state == BookPatternState.CONFIRMED_PATTERN
        assert r.direction == "bullish"

    def test_ss6_body_break_confirms(self):
        r = detect_ss6(ss6_up_series())
        assert r.state == BookPatternState.CONFIRMED_PATTERN
        assert r.direction == "bullish"

    def test_ss19_doji_break_confirms_bearish(self):
        r = detect_ss19(ss19_series())
        assert r.state == BookPatternState.CONFIRMED_PATTERN
        assert r.direction == "bearish"
        assert r.level_kind  # the doji range edges form the reference zone

    def test_ss21_confirms(self):
        r = detect_ss21(ss21_series())
        assert r.state == BookPatternState.CONFIRMED_PATTERN
        assert r.direction == "bullish"

    def test_ss22_rising_three_confirms(self):
        r = detect_ss22(ss22_series())
        assert r.state == BookPatternState.CONFIRMED_PATTERN
        assert r.direction == "bullish"

    def test_ss23_falling_three_confirms(self):
        r = detect_ss23(ss23_series())
        assert r.state == BookPatternState.CONFIRMED_PATTERN
        assert r.direction == "bearish"

    def test_ch7_s1_cross_confirms(self):
        r = detect_ch7_s1(legs())
        assert r.state == BookPatternState.CONFIRMED_PATTERN
        assert r.direction == "bullish"
        assert r.stochastic_supported is True

    # -- negative / lookalike ----------------------------------------------
    def test_ss5_no_setup_is_forming_not_confirmation(self):
        r = detect_ss5(downtrend(18))
        assert r.state == BookPatternState.FORMING
        assert r.direction == "neutral"

    def test_ss1_no_setup_is_forming(self):
        r = detect_ss1(uptrend(18))
        assert r.state == BookPatternState.FORMING

    def test_ss22_no_setup_is_forming(self):
        r = detect_ss22(legs(cycles=3))
        assert r.state == BookPatternState.FORMING

    def test_ss6_wick_only_is_not_a_breakout(self):
        r = detect_ss6(ss6_up_series(wick_only=True))
        assert r.state != BookPatternState.CONFIRMED_PATTERN
        assert any("wick-only" in m for m in r.missing_conditions)

    def test_ch7_s1_monotonic_needs_a_cross(self):
        r = detect_ch7_s1(uptrend(24))
        assert r.state == BookPatternState.FORMING

    # -- invalidation -------------------------------------------------------
    def test_ss5_break_is_invalidated(self):
        r = detect_ss5(ss5_up_series(break_top=True))
        assert r.state == BookPatternState.INVALIDATED
        assert r.direction == "neutral"

    # -- insufficient data --------------------------------------------------
    def test_empty_series_is_insufficient(self):
        for fn in (detect_ss1, detect_ss5, detect_ss19, detect_ss22):
            r = fn([])
            assert r.state == BookPatternState.INSUFFICIENT_DATA

    def test_too_short_series_is_insufficient(self):
        r = detect_ss1([candle(1.0, 1.001, 0.999, 1.0005)])
        assert r.state == BookPatternState.INSUFFICIENT_DATA

    # -- forming last candle downgrades ------------------------------------
    def test_forming_last_candle_never_confirms(self):
        c = ss22_series()
        for fn in (detect_ss1, detect_ss5, detect_ss19, detect_ss21, detect_ss22, detect_ss23):
            r = fn(c, last_candle_forming=True)
            assert r.state != BookPatternState.CONFIRMED_PATTERN, fn.__name__

    # -- state validity ------------------------------------------------------
    def test_all_results_use_valid_states(self):
        series = [legs(), uptrend(5), [], ss22_series(), ss19_series()]
        for fn in BOOK_DETECTORS.values():
            for s in series:
                assert fn(s).state in VALID_STATES


# ---------------------------------------------------------------------------
# Indicators (Step 2 support): causal, no lookahead
# ---------------------------------------------------------------------------
class TestIndicators:
    def test_stochastic_causal(self):
        c = legs()
        full_k, full_d = stochastic(c)
        prefix_k, prefix_d = stochastic(c[: len(c) - 5])
        assert prefix_k == full_k[: len(c) - 5]
        assert prefix_d == full_d[: len(c) - 5]

    def test_ema_causal(self):
        c = legs()
        closes = [x["close"] for x in c]
        full = ema(closes, period=5)
        prefix = ema(closes[:-5], period=5)
        assert prefix == full[: len(c) - 5]

    def test_psar_causal(self):
        c = legs()
        full = parabolic_sar(c)
        prefix = parabolic_sar(c[: len(c) - 5])
        assert prefix == full[: len(c) - 5]

    def test_stochastic_supported_needs_both_lines(self):
        short = uptrend(3)
        assert stochastic_supported(short, len(short) - 1, direction="bullish") is None
        c = legs()
        assert stochastic_supported(c, len(c) - 1, direction="bullish") is not None


# ---------------------------------------------------------------------------
# No-future-leakage property (Step 6): replay[i] == detector(prefix)
# ---------------------------------------------------------------------------
class TestNoLeakage:
    @pytest.mark.parametrize(
        "key,builder",
        [
            ("SS5", ss5_up_series),
            ("SS19", ss19_series),
            ("SS22", ss22_series),
            ("SS23", ss23_series),
        ],
    )
    def test_replay_signal_matches_standalone_prefix(self, key, builder):
        candles = builder()
        service = BookValidationService()
        signals = {s.index: s for s in service.replay(key, candles)}
        for i in range(20, len(candles) - 1):
            if i not in signals:
                continue
            prefix_result = BOOK_DETECTORS[SPEC_BY_KEY[key].detector_key](candles[: i + 1])
            assert prefix_result.state == BookPatternState.CONFIRMED_PATTERN
            assert prefix_result.completed_at == i
            assert prefix_result.direction == signals[i].direction

    def test_future_candles_cannot_change_a_past_signal(self):
        candles = ss22_series()
        short = candles[: len(candles) - 1]
        r_before = detect_ss22(short)
        # Append unrelated future candles; the earlier evaluation is stable
        # because the detector only ever saw the truncated series.
        r_after = detect_ss22(candles)
        assert r_after.completed_at == len(candles) - 1
        if r_before.state == BookPatternState.CONFIRMED_PATTERN:
            assert r_before.completed_at == len(short) - 1


# ---------------------------------------------------------------------------
# Screenshot -> book candidates (Step 3-4): no invented OHLC, OTC refusal
# ---------------------------------------------------------------------------
class TestMapper:
    @staticmethod
    def _analysis(user, payload):
        from apps.chart_vision.services.screenshot_analyzer import (
            ScreenshotAnalyzer,
            get_or_create_analysis,
        )
        from tests.vision_fakes import StaticVisionProvider

        screenshot = make_screenshot(user)
        analysis, _ = get_or_create_analysis(screenshot)
        ScreenshotAnalyzer(provider=StaticVisionProvider(payload=payload)).analyze(
            screenshot, analysis
        )
        analysis.refresh_from_db()
        return analysis

    @pytest.fixture
    def analysis(self):
        return self._analysis(
            UserFactory(username="book-mapper"), full_payload()
        )

    def test_candidates_capped_at_awaiting(self):
        candidates = build_book_candidates(self.analysis)
        for candidate in candidates:
            assert candidate.state == BookPatternState.AWAITING_CONFIRMATION

    def test_candidates_are_screenshot_only(self):
        for candidate in build_book_candidates(self.analysis):
            assert candidate.data_verification == DataVerification.SCREENSHOT_ONLY

    def test_candidates_never_carry_ohlc(self):
        for candidate in build_book_candidates(self.analysis):
            payload = candidate.as_dict()
            for banned in ("open", "high", "low", "close", "ohlc"):
                assert banned not in str(payload).lower()

    def test_unknown_labels_map_to_nothing(self):
        # The static payload's labels map through a fixed table; anything not
        # in the table produces no candidate (no guessing).
        candidates = build_book_candidates(self.analysis)
        keys = {c.strategy_key for c in candidates}
        assert keys.issubset(
            {"SS4", "SS12", "SS15", "SS16", "SS19", "SS20", "SS22", "SS23"}
        )

    def test_every_candidate_lists_missing_conditions(self):
        for candidate in build_book_candidates(self.analysis):
            assert candidate.missing_conditions, candidate.strategy_key

    def test_otc_analysis_flag_detected(self):
        payload = full_payload()
        payload["chart_metadata"]["otc_status"] = "otc"
        analysis = self._analysis(UserFactory(username="book-otc"), payload)
        from apps.book_strategies.services.recognition import analysis_is_otc

        assert analysis_is_otc(analysis) is True

    def test_regular_market_is_not_otc(self):
        from apps.book_strategies.services.recognition import analysis_is_otc

        assert analysis_is_otc(self.analysis) is False


# ---------------------------------------------------------------------------
# Recognizer (Step 9): structured response, NO_TRADE invariant, OTC refusal
# ---------------------------------------------------------------------------
class TestRecognizer:
    def test_confirmed_pattern_still_no_trade(self):
        detection = BookStrategyRecognizer().evaluate(
            "SS22", ss22_series(), instrument="EURUSD", timeframe="M1",
            market_type="real", persist=False,
        )
        assert detection.recognition_status == BookPatternState.CONFIRMED_PATTERN
        assert detection.decision == DECISION_NO_TRADE
        assert detection.probability is None
        assert detection.probability_status == PROBABILITY_STATUS

    def test_step9_shape(self):
        detection = BookStrategyRecognizer().evaluate(
            "SS22", ss22_series(), persist=False,
        )
        payload = detection.as_dict()
        for field in (
            "strategy_id", "strategy_name", "recognition_status",
            "observed_evidence", "missing_conditions", "data_verification",
            "decision", "probability", "probability_status",
        ):
            assert field in payload
        assert payload["strategy_id"] == "BOOK_SS22"

    def test_catalog_only_key_is_not_evaluated(self):
        detection = BookStrategyRecognizer().evaluate("SS10", legs(), persist=False)
        assert detection.recognition_status == BookPatternState.INSUFFICIENT_DATA
        assert detection.data_verification == DataVerification.NOT_EVALUATED

    def test_otc_mismatch_refuses_verification(self):
        detection = BookStrategyRecognizer().evaluate(
            "SS22", ss22_series(),
            screenshot_is_otc=True, feed_market_type="real",
            persist=False,
        )
        assert detection.data_verification == DataVerification.INCOMPATIBLE_FEEDS
        assert detection.recognition_status == BookPatternState.INSUFFICIENT_DATA

    def test_otc_with_otc_feed_is_allowed(self):
        detection = BookStrategyRecognizer().evaluate(
            "SS22", ss22_series(),
            screenshot_is_otc=True, feed_market_type="otc",
            persist=False,
        )
        assert detection.data_verification == DataVerification.OHLC_VERIFIED

    def test_evaluate_enabled_respects_admin_switch(self):
        BookStrategy.objects.filter(key="SS22").update(recognition_enabled=True)
        BookStrategy.objects.filter(key="SS1").update(recognition_enabled=True)
        detections = BookStrategyRecognizer().evaluate_enabled(
            ss22_series(), persist=False,
        )
        keys = {d.strategy_key for d in detections}
        assert keys == {"SS22", "SS1"}

    def test_persist_writes_detection_row(self):
        BookStrategy.objects.filter(key="SS22").update(recognition_enabled=True)
        BookStrategyRecognizer().evaluate("SS22", ss22_series(), instrument="EURUSD")
        row = BookStrategyDetection.objects.get(strategy__key="SS22")
        assert row.decision == DECISION_NO_TRADE
        assert row.probability is None
        assert row.data_verification == DataVerification.OHLC_VERIFIED


# ---------------------------------------------------------------------------
# Validation (Step 6): honesty, uncertainty, baseline, OOS
# ---------------------------------------------------------------------------
class TestValidation:
    def test_wilson_interval_no_trials(self):
        assert wilson_interval(0, 0) == (None, None)

    def test_wilson_interval_bounds(self):
        lo, hi = wilson_interval(16, 31)
        assert 0.0 <= lo < 16 / 31 < hi <= 1.0

    def test_no_signals_reports_no_accuracy(self):
        report = BookValidationService().validate(
            "SS22", legs(), instrument="EURUSD", timeframe="M5",
        )
        assert report.splits["pooled"]["n_signals"] == 0
        assert report.splits["pooled"]["accuracy"] is None
        assert report.sufficient_data is False
        assert report.insufficient_reason
        assert report.hypothetical_expectancy_per_trade is None

    def test_report_never_claims_approval(self):
        report = BookValidationService().validate("SS1", ss1_up_series() * 3)
        assert report.as_dict()["approved_for_decision_use"] is False

    def test_metric_scope_is_next_candle_not_settlement(self):
        report = BookValidationService().validate("SS1", ss1_up_series() * 3)
        assert "NEXT candle" in report.disclaimer
        assert "NOT binary-option settlement" in report.disclaimer

    def test_oos_split_is_chronological(self):
        candles = ss1_up_series() * 6
        report = BookValidationService().validate(
            "SS1", candles, oos_fraction=0.3,
        )
        split = report.dataset["split_index"]
        in_sample = [s.index for s in report.signals if s.index < split]
        out_of_sample = [s.index for s in report.signals if s.index >= split]
        assert all(i < split for i in in_sample)
        assert all(i >= split for i in out_of_sample)
        assert all(
            s1.index <= s2.index
            for s1, s2 in zip(report.signals, report.signals[1:], strict=False)
        ), "signals must stay in chronological order (no shuffling)"

    def test_small_sample_marks_insufficient(self):
        report = BookValidationService().validate("SS1", ss1_up_series() * 3)
        assert report.sufficient_data is False
        assert "below the" in report.insufficient_reason

    def test_baseline_present_in_every_split(self):
        report = BookValidationService().validate("SS5", ss5_up_series() * 4)
        for split in report.splits.values():
            assert "baseline_accuracy" in split
            assert "n_outcome_candles" in split

    def test_expectancy_only_when_sufficient(self):
        report = BookValidationService().validate("SS1", ss1_up_series() * 3)
        if not report.sufficient_data:
            assert report.hypothetical_expectancy_per_trade is None


# ---------------------------------------------------------------------------
# Explainer (Step 5): ten questions, hallucination resistance
# ---------------------------------------------------------------------------
class TestExplainer:
    def test_no_detection_text_when_empty(self):
        detection = BookStrategyRecognizer().evaluate("SS22", [], persist=False)
        out = explain(detection)
        assert "No book strategy is detected" in out["which_strategy"]
        assert out["pattern_number"] is None
        assert out["decision"] == DECISION_NO_TRADE

    def test_forming_candidate_named_but_not_detected(self):
        detection = BookStrategyRecognizer().evaluate(
            "SS22", legs(cycles=3), persist=False,
        )
        out = explain(detection)
        assert "has not formed" in out["which_strategy"] or "No book strategy" in out["which_strategy"]

    def test_confirmed_answers_all_questions(self):
        detection = BookStrategyRecognizer().evaluate(
            "SS22", ss22_series(), persist=False,
        )
        out = explain(detection)
        for key in (
            "which_strategy", "pattern_number", "pattern_candles",
            "reference_level", "breakout_happened", "last_candle_complete",
            "missing_conditions", "invalidation", "direction_rationale",
            "no_trade_rationale",
        ):
            assert key in out
        assert out["pattern_number"] == 22
        assert out["decision"] == DECISION_NO_TRADE
        assert "not a calibrated prediction" in out["no_trade_rationale"]

    def test_invalidation_rationale(self):
        detection = BookStrategyRecognizer().evaluate(
            "SS5", ss5_up_series(break_top=True), persist=False,
        )
        out = explain(detection)
        assert "invalidation rule fired" in out["no_trade_rationale"]

    def test_forming_last_candle_appears_in_missing(self):
        detection = BookStrategyRecognizer().evaluate(
            "SS22", ss22_series(), last_candle_forming=True, persist=False,
        )
        out = explain(detection, last_candle_complete=False)
        assert any("still forming" in m for m in out["missing_conditions"])


# ---------------------------------------------------------------------------
# Dashboard (Step 8): list, detail, staff-only recognition toggle
# ---------------------------------------------------------------------------
class TestDashboard:
    @pytest.fixture
    def staff(self):
        return UserFactory(username="book-admin", is_staff=True)

    @pytest.fixture
    def member(self):
        return UserFactory(username="book-member")

    def test_list_page_shows_catalog(self, client, member):
        client.force_login(member)
        response = client.get("/dashboard/book-strategies/")
        assert response.status_code == 200
        assert b"Book strategies" in response.content

    def test_detail_page_shows_book_fields(self, client, member):
        client.force_login(member)
        response = client.get("/dashboard/book-strategies/SS22/")
        assert response.status_code == 200
        assert b"Rising Three Method" in response.content

    def test_detail_missing_strategy_404(self, client, member):
        client.force_login(member)
        response = client.get("/dashboard/book-strategies/NOPE/")
        assert response.status_code == 404

    def test_toggle_requires_login(self, client):
        response = client.post("/dashboard/book-strategies/SS22/toggle/")
        assert response.status_code == 302  # redirected to login

    def test_toggle_blocked_for_non_staff(self, client, member):
        client.force_login(member)
        row = BookStrategy.objects.get(key="SS22")
        before = row.recognition_enabled
        response = client.post("/dashboard/book-strategies/SS22/toggle/")
        assert response.status_code == 302
        row.refresh_from_db()
        assert row.recognition_enabled == before

    def test_toggle_flips_recognition_for_staff(self, client, staff):
        client.force_login(staff)
        row = BookStrategy.objects.get(key="SS22")
        before = row.recognition_enabled
        client.post("/dashboard/book-strategies/SS22/toggle/")
        row.refresh_from_db()
        assert row.recognition_enabled == (not before)

    def test_toggle_never_touches_decision_approval(self, client, staff):
        client.force_login(staff)
        row = BookStrategy.objects.get(key="SS22")
        row.decision_use_approved = False
        row.save(update_fields=["decision_use_approved"])
        client.post("/dashboard/book-strategies/SS22/toggle/")
        row.refresh_from_db()
        assert row.decision_use_approved is False

    def test_toggle_is_post_only(self, client, staff):
        client.force_login(staff)
        response = client.get("/dashboard/book-strategies/SS22/toggle/")
        assert response.status_code == 405

    def test_list_marks_unapproved(self, client, member):
        client.force_login(member)
        response = client.get("/dashboard/book-strategies/")
        assert b"Not approved for decisions" in response.content


# ---------------------------------------------------------------------------
# Admin: explicit, justified approval action (never a single untracked click)
# ---------------------------------------------------------------------------
class TestAdminApprovalAction:
    @pytest.fixture
    def admin_client(self, client):
        superuser = UserFactory(
            username="book-superuser", is_staff=True, is_superuser=True
        )
        client.force_login(superuser)
        return client

    def _run(self, admin_client, keys, justification, *, action="approve_for_decision_use"):
        rows = BookStrategy.objects.filter(key__in=keys)
        return admin_client.post(
            "/admin/book_strategies/bookstrategy/",
            {
                "action": action,
                "_selected_action": [str(r.pk) for r in rows],
                "apply": "1",
                "justification": justification,
            },
            follow=True,
        )

    def test_approval_refused_while_pipeline_incomplete(self, admin_client):
        """Status below oos_validated cannot be approved, even with evidence."""
        BookStrategy.objects.filter(key="SS1").update(research_status="implemented")
        self._run(admin_client, ["SS1"], "accuracy 70% Wilson [60,80] n=40 OOS 65%")
        row = BookStrategy.objects.get(key="SS1")
        assert row.decision_use_approved is False
        assert row.research_status == "implemented"

    def test_approval_refused_without_justification(self, admin_client):
        BookStrategy.objects.filter(key="SS1").update(research_status="oos_validated")
        self._run(admin_client, ["SS1"], "too short")
        row = BookStrategy.objects.get(key="SS1")
        assert row.decision_use_approved is False
        assert row.research_status == "oos_validated"

    def test_approval_succeeds_with_evidence_and_stores_it(self, admin_client):
        note = "SS1 EURUSD M5: 46 signals, 61% next-candle accuracy, Wilson [46,74], OOS 52%"
        BookStrategy.objects.filter(key="SS1").update(research_status="oos_validated")
        self._run(admin_client, ["SS1"], note)
        row = BookStrategy.objects.get(key="SS1")
        assert row.decision_use_approved is True
        assert row.research_status == "approved"
        assert row.validation_notes == note

    def test_approval_page_renders_justification_form(self, admin_client):
        BookStrategy.objects.filter(key="SS1").update(research_status="oos_validated")
        row = BookStrategy.objects.get(key="SS1")
        response = admin_client.post(
            "/admin/book_strategies/bookstrategy/",
            {"action": "approve_for_decision_use", "_selected_action": [str(row.pk)]},
        )
        assert response.status_code == 200
        assert b"Validation evidence" in response.content
        # The intermediate page must not have approved anything yet.
        row.refresh_from_db()
        assert row.decision_use_approved is False

    def test_revoke_action_clears_approval(self, admin_client):
        BookStrategy.objects.filter(key="SS1").update(
            research_status="approved", decision_use_approved=True
        )
        self._run(admin_client, ["SS1"], "", action="revoke_decision_use_approval")
        row = BookStrategy.objects.get(key="SS1")
        assert row.decision_use_approved is False
        # Never overstates progress: steps back to the last completed stage.
        assert row.research_status == "oos_validated"



# ---------------------------------------------------------------------------
# Seed command: idempotent, knowledge-only, switches stay off
# ---------------------------------------------------------------------------
class TestSeedCommand:
    def test_seed_is_idempotent_and_keeps_switches_off(self):
        from django.core.management import call_command

        call_command("seed_book_strategies")
        call_command("seed_book_strategies")
        assert BookStrategy.objects.count() == 32
        assert BookStrategy.objects.filter(recognition_enabled=True).count() == 0
        assert BookStrategy.objects.filter(decision_use_approved=True).count() == 0

    def test_seed_marks_implemented_status(self):
        from django.core.management import call_command

        call_command("seed_book_strategies")
        implemented = BookStrategy.objects.filter(
            research_status=ResearchStatus.IMPLEMENTED
        )
        assert implemented.count() == 10

    def test_seed_preserves_advanced_status(self):
        from django.core.management import call_command

        call_command("seed_book_strategies")
        BookStrategy.objects.filter(key="SS22").update(
            research_status=ResearchStatus.RECOGNITION_TESTED,
        )
        call_command("seed_book_strategies")
        row = BookStrategy.objects.get(key="SS22")
        assert row.research_status == ResearchStatus.RECOGNITION_TESTED


# ---------------------------------------------------------------------------
# Assistant boundedness (CP13): book context is compact and honest
# ---------------------------------------------------------------------------
class TestAssistantBookContext:
    def test_unrelated_message_gets_no_book_context(self):
        from apps.ai_assistant.services.assistant_service import AssistantService

        service = AssistantService()
        assert service._book_context("hello there") == ""

    def test_book_mention_gets_bounded_context(self):
        from django.core.management import call_command

        from apps.ai_assistant.services.assistant_service import (
            MAX_BOOK_CONTEXT_CHARS,
            AssistantService,
        )

        call_command("seed_book_strategies")
        service = AssistantService()
        block = service._book_context("what does SS22 say?")
        assert block
        assert len(block) <= MAX_BOOK_CONTEXT_CHARS
        assert "SS22" in block
        assert "NO TRADE" in block
        assert "uncalibrated" in block

    def test_context_contains_no_accuracy_claims(self):
        from django.core.management import call_command

        from apps.ai_assistant.services.assistant_service import AssistantService

        call_command("seed_book_strategies")
        service = AssistantService()
        for mention in ("SS1 magic v", "SS19 doji", "sure shot 21"):
            block = service._book_context(mention)
            lowered = block.lower()
            assert "win rate" not in lowered
            assert "accuracy" not in lowered
            assert "%" not in block
