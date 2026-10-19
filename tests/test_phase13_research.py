# tests/test_phase13_research.py
"""Phase 13 continuation regression tests (requirements R1-R10).

Hermetic: SQLite, hand-built candles, no MT5, no network, no LLM.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from apps.book_strategies.constants import (
    IMPLEMENTED_SPEC_KEYS,
    PROBABILITY_STATUS,
    SPEC_BY_KEY,
    BookPatternState,
    DataVerification,
    ResearchStatus,
)
from apps.book_strategies.models import (
    BookStrategy,
    BookStrategyDetection,
    PaperForwardPrediction,
    PredictionImmutableError,
    payload_digest,
)
from apps.book_strategies.services.backtest import (
    BOOK_RUN_KIND,
    COMPARISON_RUN_KIND,
    BookBacktestService,
)
from apps.book_strategies.services.comparison import (
    TIER_BELOW_BASELINE,
    TIER_CANDIDATE,
    TIER_INSUFFICIENT,
    BookComparisonService,
)
from apps.book_strategies.services.decision_integration import (
    book_strategy_candidates,
)
from apps.book_strategies.services.detectors import BOOK_DETECTORS, detect_ss1
from apps.book_strategies.services.metrics import (
    NOT_COMPUTABLE_STATUS,
    PREDICTION_METRIC_SCOPE,
    RECOGNITION_METRIC_SCOPE,
    RecognitionMetricsService,
    assert_prediction_scope,
    assert_recognition_scope,
)
from apps.book_strategies.services.paper_forward import PaperForwardService
from apps.book_strategies.services.settlement import (
    SETTLEMENT_METRIC_SCOPE,
    BookSettlementService,
)
from apps.book_strategies.services.validation import (
    DEFAULT_MIN_SIGNALS,
    METRIC_SCOPE,
    BookValidationService,
)
from apps.book_strategies.services.walk_forward import BookWalkForwardService
from apps.research.models import BacktestRun, HistoricalCandle, HistoricalDataset
from apps.research.services.dataset_builder import DatasetBuilder
from apps.research.services.walk_forward_validation import WalkForwardValidation
from apps.strategy_engine.constants import (
    CandidateStatus,
    EvaluationDirection,
    InvalidationReasonCode,
    ProbabilityStatus,
    StrategyFamily,
)
from apps.strategy_engine.services.evaluation_service import EvaluationService
from tests.factories import UserFactory
from tests.pa_fakes import candle, flat

pytestmark = pytest.mark.django_db

START = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
M5 = timedelta(minutes=5)


@pytest.fixture(autouse=True)
def _seed_catalog_fixture():
    """Seed catalog for every test."""
    call_command("seed_book_strategies")


def _legs(start: float = 1.0, cycles: int = 4, leg: int = 3,
          step: float = 0.0008, pull: float = 0.0005) -> list[dict]:
    """Rising market with real swing structure (3-candle legs).

    Mirrors the verified ``tests.test_book_strategies.legs`` fixture so
    ``infer_trend`` returns "uptrend".
    """
    out: list[dict] = []
    price = start

    def up_leg() -> None:
        nonlocal price
        for _ in range(leg):
            o = price
            c = price + step
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
    c = _legs()
    base = c[-1]["close"]
    c.append(candle(base, base + 0.0004, base - 0.0001, base + 0.0003))  # green
    pair_top = base + 0.0004
    c.append(candle(base + 0.0003, pair_top, base - 0.0004, base - 0.0003))  # red 1
    c.append(candle(base - 0.0003, base + 0.0001, base - 0.0008, base - 0.0007))  # red 2
    level = max(c[-2]["high"], c[-1]["high"])
    c.append(candle(base - 0.0007, level + 0.0010, base - 0.0008, level + 0.0009))
    return c


def with_outcome(series: list[dict]) -> list[dict]:
    """Append one outcome candle closing above the breakout close."""
    s = list(series)
    if not s:
        return s
    last = s[-1]
    s.append(
        candle(
            last["close"] - 0.0001,
            last["close"] + 0.0003,
            min(last["low"], last["close"] - 0.0001),
            last["close"] + 0.0002,
        )
    )
    return s


def stamped(series: list[dict], *, start: datetime = START) -> list[dict]:
    out: list[dict] = []
    for i, c in enumerate(series):
        row = dict(c)
        row["open_time"] = start + i * M5
        row["complete"] = True
        out.append(row)
    return out


def _rows(series: list[dict], *, start: datetime = START, step: timedelta = M5) -> list[dict]:
    return [
        {
            "open_time": (start + i * step).isoformat(),
            "open": c["open"],
            "high": c["high"],
            "low": c["low"],
            "close": c["close"],
        }
        for i, c in enumerate(series)
    ]


def book_candles(series: list[dict], *, final_complete: bool = True) -> list[dict]:
    out = [dict(c) for c in series]
    for row in out:
        row["complete"] = True
    if out and not final_complete:
        out[-1]["complete"] = False
    return out


def eval_candles(*, count: int = 6, final_complete: bool = True) -> list[dict]:
    candles: list[dict] = []
    for index in range(count):
        open_px = 1.1000 + index * 0.0002
        close_px = open_px + 0.0003
        candles.append(
            {
                "open": round(open_px, 5),
                "high": round(close_px + 0.0002, 5),
                "low": round(open_px - 0.0002, 5),
                "close": round(close_px, 5),
                "complete": True,
            }
        )
    if not final_complete and candles:
        candles[-1]["complete"] = False
    return candles


def eval_input(**overrides) -> dict:
    base = {
        "instrument": "EURUSD",
        "timeframe": "M1",
        "market_type": "regular",
        "sync_status": "verified_alignment",
        "candles": eval_candles(),
        "price_action_result": {"evidence": [], "conflicts": [], "context": {}},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# R1 - historical dataset import with provenance
# ---------------------------------------------------------------------------
class TestDatasetImport:
    def test_import_records_provenance_and_candles(self):
        rows = _rows(ss1_up_series())
        dataset, report = DatasetBuilder().import_ohlc(
            rows,
            name="bible-ss1",
            instrument="EURUSD",
            timeframe="M5",
            source="test_csv",
            source_file="eurusd_m5.csv",
            source_sha256="abc123",
            importer="tester",
        )
        assert dataset.candle_count == len(rows)
        assert dataset.is_validated is True
        assert dataset.source == "test_csv"
        assert report["candles_imported"] == len(rows)
        provenance = dataset.metadata["provenance"]
        assert provenance["source_sha256"] == "abc123"
        assert provenance["source_file"] == "eurusd_m5.csv"
        assert provenance["importer"] == "tester"
        assert provenance["tool"] == "DatasetBuilder.import_ohlc"
        assert provenance["rows_presented"] == len(rows)
        assert provenance["rows_imported"] == len(rows)
        assert provenance["rows_rejected"] == 0
        assert provenance["gap_count"] == 0
        assert HistoricalCandle.objects.filter(dataset=dataset).count() == len(rows)
        stored = HistoricalCandle.objects.filter(dataset=dataset).order_by("open_time").first()
        assert stored.is_complete is True

    def test_invalid_rows_rejected_not_repaired(self):
        rows = _rows(ss1_up_series())
        # low above high - impossible candle; must be rejected, never fixed.
        rows[3] = dict(rows[3])
        rows[3]["low"] = rows[3]["high"] + 0.001
        dataset, report = DatasetBuilder().import_ohlc(
            rows, instrument="EURUSD", timeframe="M5"
        )
        assert report["rows_rejected"] == 1
        assert "ohlc_relationship_violated" in report["reject_reasons"]
        assert dataset.candle_count == len(rows) - 1
        assert dataset.is_validated is False

    def test_duplicate_timestamps_rejected(self):
        rows = _rows(ss1_up_series())
        rows.append(dict(rows[0]))
        dataset, report = DatasetBuilder().import_ohlc(
            rows, instrument="EURUSD", timeframe="M5"
        )
        assert "duplicate_timestamp" in report["reject_reasons"]
        assert dataset.candle_count == len(rows) - 1

    def test_gaps_flagged_but_never_fabricated(self):
        rows = _rows(ss1_up_series())
        del rows[10]  # one M5 hole
        dataset, report = DatasetBuilder().import_ohlc(
            rows, instrument="EURUSD", timeframe="M5"
        )
        assert report["gap_count"] == 1
        assert dataset.candle_count == len(rows)  # missing candle NOT invented
        assert dataset.is_validated is False
        assert any(flag.get("type") == "gap" for flag in dataset.data_quality_flags)

    def test_unsorted_input_sorted_and_flagged(self):
        rows = _rows(ss1_up_series())
        shuffled = [rows[5], rows[0], *rows[1:5], *rows[6:]]
        dataset, _report = DatasetBuilder().import_ohlc(
            shuffled, instrument="EURUSD", timeframe="M5"
        )
        times = list(
            HistoricalCandle.objects.filter(dataset=dataset)
            .order_by("open_time")
            .values_list("open_time", flat=True)
        )
        assert times == sorted(times)
        assert any(
            flag.get("type") == "unsorted_input_reordered"
            for flag in dataset.data_quality_flags
        )

    def test_naive_timestamps_assumed_utc_and_flagged(self):
        rows = _rows(ss1_up_series())
        rows[0] = dict(rows[0])
        rows[0]["open_time"] = rows[0]["open_time"].replace("+00:00", "")
        dataset, _ = DatasetBuilder().import_ohlc(
            rows, instrument="EURUSD", timeframe="M5"
        )
        assert any(
            flag.get("type") == "naive_timestamps_assumed_utc"
            for flag in dataset.data_quality_flags
        )
        stored = HistoricalCandle.objects.filter(dataset=dataset).order_by("open_time").first()
        assert stored.open_time.tzinfo is not None

    def test_every_row_rejected_writes_nothing(self):
        bad = [
            {"open_time": "not-a-date", "open": 1, "high": 1, "low": 1, "close": 1},
            {"open": 1, "high": 1, "low": 1, "close": 1},  # no timestamp
        ]
        with pytest.raises(ValueError, match="rejected every row"):
            DatasetBuilder().import_ohlc(bad, instrument="EURUSD", timeframe="M5")
        assert HistoricalDataset.objects.count() == 0
        assert HistoricalCandle.objects.count() == 0

    def test_csv_command_end_to_end(self, tmp_path):
        path = tmp_path / "eurusd_m5.csv"
        lines = ["open_time,open,high,low,close"]
        for row in _rows(ss1_up_series()):
            lines.append(
                f"{row['open_time']},{row['open']},{row['high']},"
                f"{row['low']},{row['close']}"
            )
        path.write_text("\n".join(lines), encoding="utf-8")

        call_command(
            "import_ohlc_csv",
            str(path),
            instrument="EURUSD",
            timeframe="M5",
            source="csv",
        )
        dataset = HistoricalDataset.objects.get()
        assert dataset.candle_count == 31
        provenance = dataset.metadata["provenance"]
        assert provenance["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert provenance["source_file"] == "eurusd_m5.csv"
        assert provenance["importer"]  # getpass user, never blank

    def test_csv_command_missing_column_errors(self, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text(
            "open_time,open,high,close\n2026-01-05T10:00:00+00:00,1,1,1\n",
            encoding="utf-8",
        )
        with pytest.raises(CommandError, match="missing column"):
            call_command("import_ohlc_csv", str(path), instrument="EURUSD", timeframe="M5")


# ---------------------------------------------------------------------------
# R2 - deterministic leak-free backtesting, persisted
# ---------------------------------------------------------------------------
class TestBacktest:
    def test_backtest_persists_run_with_payload_and_signals(self):
        candles = with_outcome(ss1_up_series())
        run = BookBacktestService().run(
            "SS1", candles, instrument="EURUSD", timeframe="M5"
        )
        assert run.status == "completed"
        assert run.strategy_config["kind"] == BOOK_RUN_KIND
        assert run.strategy_config["strategy_key"] == "SS1"
        payload = run.results["validation"]
        assert payload["metric_scope"] == METRIC_SCOPE
        assert payload["approved_for_decision_use"] is False
        assert payload["dataset"]["n_candles"] == len(candles)
        assert payload["dataset"]["detector_key"] == "ss1"
        assert payload["signals"], "the SS1 setup must yield at least one replay signal"
        assert run.sample_count == len(payload["signals"]) >= 1
        assert all(signal["index"] == signal["completed_at"] for signal in payload["signals"])
        assert run.metrics["metric_scope"] == METRIC_SCOPE
        assert run.metrics["approved_for_decision_use"] is False
        assert run.metrics["accuracy_status"] == "measured"
        assert BacktestRun.objects.filter(pk=run.pk).exists()

    def test_backtest_is_deterministic(self):
        candles = with_outcome(ss1_up_series())
        service = BookBacktestService()
        first = service.run("SS1", candles, instrument="EURUSD", timeframe="M5")
        second = service.run("SS1", candles, instrument="EURUSD", timeframe="M5")
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.results == second.results
        assert first.metrics == second.metrics
        assert first.sample_count == second.sample_count

    def test_backtest_signals_match_standalone_replay(self):
        candles = with_outcome(ss1_up_series())
        run = BookBacktestService().run("SS1", candles)
        replayed = [asdict(signal) for signal in BookValidationService().replay("SS1", candles)]
        assert run.results["validation"]["signals"] == replayed
        # Prefix causality: the stored signal exists on its own prefix only.
        signal = run.results["validation"]["signals"][0]
        prefix = candles[: signal["index"] + 1]
        prefix_result = detect_ss1(prefix)
        assert prefix_result.state == BookPatternState.CONFIRMED_PATTERN
        assert prefix_result.completed_at == signal["index"]
        assert prefix_result.direction == signal["direction"]

    def test_backtest_rejects_unimplemented_key(self):
        unimplemented = next(
            key for key, spec in SPEC_BY_KEY.items() if not spec.detector_key
        )
        with pytest.raises(KeyError):
            BookBacktestService().run(unimplemented, ss1_up_series())

    def test_no_signals_reports_none_not_zero(self):
        run = BookBacktestService().run("SS1", flat(40))
        assert run.sample_count == 0
        pooled = run.results["validation"]["splits"]["pooled"]
        assert pooled["n_signals"] == 0
        assert pooled["accuracy"] is None
        assert pooled["wilson_95"] == [None, None]
        assert run.results["validation"]["sufficient_data"] is False
        assert run.metrics["accuracy_status"] == "no_signals"

    def test_advance_status_only_to_backtested(self):
        service = BookBacktestService()
        row = BookStrategy.objects.get(key="SS1")
        row.research_status = ResearchStatus.RECOGNITION_TESTED
        row.save(update_fields=["research_status", "updated_at"])

        assert service.advance_research_status(row) is True
        row.refresh_from_db()
        assert row.research_status == ResearchStatus.BACKTESTED
        assert row.decision_use_approved is False

        # never advances beyond backtested, even when called again
        assert service.advance_research_status(row) is False
        row.refresh_from_db()
        assert row.research_status == ResearchStatus.BACKTESTED

        # a catalogued-only row has no detector: it never advances
        row.detector_key = ""
        assert service.advance_research_status(row) is False
        row.refresh_from_db()
        assert row.research_status == ResearchStatus.BACKTESTED


# ---------------------------------------------------------------------------
# R3 - chronological out-of-sample + walk-forward
# ---------------------------------------------------------------------------
class TestWalkForward:
    def test_folds_are_ordered_disjoint_and_bounded(self):
        folds = WalkForwardValidation().chronological_folds(300, window=60, burn_in=20)
        assert folds
        assert folds[0]["start"] == 20
        assert folds[0]["fold"] == 0
        previous_end = 0
        for fold in folds:
            assert fold["start"] >= previous_end
            assert fold["end"] <= 299
            assert fold["end"] > fold["start"]
            previous_end = fold["end"]
        # default step == window -> non-overlapping
        assert folds[0]["start"] == 20 and folds[0]["end"] == 80
        assert folds[1]["start"] == 80 and folds[1]["end"] == 140

    def test_folds_edge_cases(self):
        wfv = WalkForwardValidation()
        assert wfv.chronological_folds(1, window=60) == []
        assert wfv.chronological_folds(0, window=60) == []
        assert wfv.chronological_folds(10, window=1) == []  # window too small
        assert wfv.chronological_folds(10, window=60, burn_in=20) == []  # burn-in swallows series

    def test_walk_forward_signal_fn_only_sees_prefix(self):
        candles = list(range(50))
        seen_lengths: list[int] = []

        def signal_fn(prefix, index):
            seen_lengths.append(len(prefix))
            assert prefix == candles[: index + 1]
            return {"index": index} if index % 7 == 0 else None

        windows = WalkForwardValidation().walk_forward(
            candles, window=10, burn_in=5, signal_fn=signal_fn
        )
        assert windows
        for window in windows:
            assert window["start"] >= 5
            assert window["end"] <= 49
            for record in window["signals"]:
                assert window["start"] <= record["index"] < window["end"]

    def test_walk_forward_partitions_the_causal_replay(self):
        candles = with_outcome(ss1_up_series())
        service = BookWalkForwardService()
        report = service.run("SS1", candles, window=8, burn_in=20)
        replayed = BookValidationService().replay("SS1", candles, burn_in=20)
        fold_indices = {
            index
            for fold in report.folds
            for index in range(fold["start"], fold["end"])
        }
        stored = sum(fold["n_signals"] for fold in report.folds)
        assert stored == report.pooled["n_signals"] == len(replayed)
        for signal in replayed:
            assert signal.index in fold_indices
        assert report.leakage_control

    def test_insufficient_below_threshold_keeps_reason(self):
        report = BookWalkForwardService().run(
            "SS1", with_outcome(ss1_up_series()), window=8, min_signals=30
        )
        assert report.sufficient_data is False
        assert report.insufficient_reason is not None
        assert "below the 30-signal threshold" in report.insufficient_reason
        # a point estimate may exist, but the report is explicit about status
        assert report.pooled["n_signals"] >= 1
        assert report.as_dict()["approved_for_decision_use"] is False

    def test_no_signals_reports_none_not_zero(self):
        report = BookWalkForwardService().run("SS1", flat(60), window=10)
        assert report.pooled["n_signals"] == 0
        assert report.pooled["accuracy"] is None
        assert report.pooled["wilson_95"] == [None, None]
        assert report.sufficient_data is False
        assert "no completed pattern signals" in report.insufficient_reason
        assert report.as_dict()["approved_for_decision_use"] is False

    def test_too_short_series_reports_reason(self):
        report = BookWalkForwardService().run("SS1", ss1_up_series()[:10], window=60, burn_in=20)
        assert report.folds == []
        assert report.sufficient_data is False
        assert "too short for walk-forward windows" in report.insufficient_reason

    def test_walk_forward_declares_scope_and_disclaimer(self):
        payload = BookWalkForwardService().run(
            "SS1", with_outcome(ss1_up_series()), window=8
        ).as_dict()
        assert payload["metric_scope"] == METRIC_SCOPE
        assert "NOT binary-option settlement" in payload["disclaimer"]
        assert "forward" in payload["disclaimer"].lower()
        for fold in payload["folds"]:
            assert fold["wilson_95"] is not None


# ---------------------------------------------------------------------------
# R5 - comparison and research ranking
# ---------------------------------------------------------------------------
def _sufficient_entry(key: str, accuracy: float, baseline: float, n_oos: int = 40) -> dict:
    oos = {
        "n_signals": n_oos,
        "accuracy": accuracy,
        "wilson_95": [0.3, 0.7],
        "baseline_accuracy": baseline,
        "n_outcome_candles": 100,
    }
    return {
        "strategy_key": key,
        "name": key,
        "validation": {
            "sufficient_data": True,
            "insufficient_reason": None,
            "splits": {"pooled": {**oos, "n_signals": 100}, "out_of_sample": oos},
        },
        "walk_forward": {
            "sufficient_data": True,
            "insufficient_reason": None,
            "pooled": {
                "n_signals": 35,
                "accuracy": accuracy,
                "wilson_95": [0.3, 0.7],
                "baseline_accuracy": baseline,
                "folds_scored": 4,
            },
        },
    }


def _insufficient_entry(key: str) -> dict:
    return {
        "strategy_key": key,
        "name": key,
        "validation": {
            "sufficient_data": False,
            "insufficient_reason": "no completed pattern signals",
            "splits": {
                "pooled": {
                    "n_signals": 0,
                    "accuracy": None,
                    "wilson_95": [None, None],
                    "baseline_accuracy": 0.5,
                },
                "out_of_sample": {"n_signals": 0, "accuracy": None, "baseline_accuracy": 0.5},
            },
        },
        "walk_forward": {
            "sufficient_data": False,
            "insufficient_reason": "no completed pattern signals",
            "pooled": {"n_signals": 0, "accuracy": None},
        },
    }


class TestComparison:
    def test_insufficient_strategies_unranked_and_key_sorted(self):
        candles = with_outcome(ss1_up_series())
        entries = [
            {
                "strategy_key": key,
                "name": SPEC_BY_KEY[key].name,
                "validation": BookValidationService().validate(key, candles).as_dict(),
                "walk_forward": BookWalkForwardService()
                .run(key, candles, window=8)
                .as_dict(),
            }
            for key in ("SS1", "SS3", "SS5")
        ]
        report = BookComparisonService().compare(entries)
        assert report.ranked_count == 0
        assert report.unranked_count == 3
        assert [row.strategy_key for row in report.rows] == ["SS1", "SS3", "SS5"]
        assert all(row.rank is None for row in report.rows)
        assert {row.tier for row in report.rows} == {TIER_INSUFFICIENT}
        assert all(row.approved_for_decision_use is False for row in report.rows)
        payload = report.as_dict()
        assert payload["approved_for_decision_use"] is False
        assert payload["ranked_count"] == 0
        assert all(r["approved_for_decision_use"] is False for r in payload["rows"])
        assert all("UNRANKED" in w for w in payload["warnings"] if "UNRANKED" in w)

    def test_ranking_orders_sufficient_entries_by_margin(self):
        report = BookComparisonService().compare(
            [
                _sufficient_entry("SS1", 0.60, 0.55),
                _sufficient_entry("SS3", 0.70, 0.55),
                _sufficient_entry("SS5", 0.50, 0.55),
            ]
        )
        rows = {row.strategy_key: row for row in report.rows}
        assert rows["SS3"].rank == 1
        assert rows["SS3"].tier == TIER_CANDIDATE
        assert rows["SS1"].rank == 2
        assert rows["SS5"].rank == 3
        assert rows["SS5"].tier == TIER_BELOW_BASELINE
        assert rows["SS5"].beats_baseline is False
        assert rows["SS1"].oos_margin == pytest.approx(0.05)
        assert rows["SS3"].oos_margin == pytest.approx(0.15)
        assert report.ranked_count == 3
        assert report.unranked_count == 0
        # a rank is never approval
        assert all(row.approved_for_decision_use is False for row in report.rows)
        assert "not approval" in report.ranking_rule

    def test_unranked_entries_listed_by_key_after_ranked(self):
        report = BookComparisonService().compare(
            [_sufficient_entry("SS1", 0.70, 0.50), _insufficient_entry("SS3")]
        )
        assert [row.strategy_key for row in report.rows] == ["SS1", "SS3"]
        assert report.rows[0].rank == 1
        assert report.rows[1].rank is None
        assert report.rows[1].tier == TIER_INSUFFICIENT

    def test_comparison_carries_scope_separation(self):
        payload = BookComparisonService().compare([]).as_dict()
        assert payload["metric_scope"] == METRIC_SCOPE
        assert "recognition" in payload["recognition_scope_note"]
        assert "settlement" in payload["settlement_disclaimer"].lower()
        assert "state_counts" not in payload
        assert "recognition_accuracy" not in payload


# ---------------------------------------------------------------------------
# R6 - recognition vs prediction metric separation
# ---------------------------------------------------------------------------
class TestMetricSeparation:
    def _detections(self) -> None:
        ss1 = BookStrategy.objects.get(key="SS1")
        ss3 = BookStrategy.objects.get(key="SS3")
        BookStrategyDetection.objects.create(
            strategy=ss1,
            state=BookPatternState.CONFIRMED_PATTERN,
            direction="bullish",
            data_verification=DataVerification.OHLC_VERIFIED,
        )
        BookStrategyDetection.objects.create(
            strategy=ss1,
            state=BookPatternState.FORMING,
            direction="neutral",
            data_verification=DataVerification.SCREENSHOT_ONLY,
        )
        BookStrategyDetection.objects.create(
            strategy=ss3,
            state=BookPatternState.CONFIRMED_PATTERN,
            direction="bullish",
            data_verification=DataVerification.OHLC_VERIFIED,
        )

    def test_recognition_report_counts_with_accuracy_none(self):
        self._detections()
        payload = RecognitionMetricsService().build().as_dict()
        assert payload["metric_scope"] == RECOGNITION_METRIC_SCOPE == "pattern_recognition"
        assert payload["n_detections"] == 3
        assert payload["n_strategies"] == 2
        assert payload["state_counts"][BookPatternState.CONFIRMED_PATTERN] == 2
        assert payload["state_counts"][BookPatternState.FORMING] == 1
        assert payload["data_verification_counts"][DataVerification.OHLC_VERIFIED] == 2
        assert payload["recognition_accuracy"] is None
        assert payload["recognition_accuracy_status"] == NOT_COMPUTABLE_STATUS
        assert "reviewer" in payload["recognition_accuracy_reason"]
        assert payload["approved_for_decision_use"] is False
        assert "no next-candle" in payload["separation_statement"]

    def test_scope_guards_block_cross_contamination(self):
        self._detections()
        recognition = RecognitionMetricsService().build().as_dict()
        assert_recognition_scope(recognition)

        prediction = BookValidationService().validate(
            "SS1", with_outcome(ss1_up_series())
        ).as_dict()
        assert_prediction_scope(prediction)

        leaked = dict(recognition)
        leaked["splits"] = {}
        with pytest.raises(ValueError, match="prediction-scope"):
            assert_recognition_scope(leaked)

        leaked2 = dict(recognition)
        leaked2["accuracy"] = 0.9
        with pytest.raises(ValueError):
            assert_recognition_scope(leaked2)

        contaminated = dict(prediction)
        contaminated["n_detections"] = 5
        with pytest.raises(ValueError, match="recognition-scope"):
            assert_prediction_scope(contaminated)

        wrong_scope = dict(prediction)
        wrong_scope["metric_scope"] = RECOGNITION_METRIC_SCOPE
        with pytest.raises(ValueError, match="metric_scope"):
            assert_prediction_scope(wrong_scope)

    def test_scopes_are_distinct_constants(self):
        assert RECOGNITION_METRIC_SCOPE != PREDICTION_METRIC_SCOPE
        assert PREDICTION_METRIC_SCOPE == METRIC_SCOPE == "next_candle_direction"

    def test_reproducibility_is_recognition_scope_not_accuracy(self):
        payload = RecognitionMetricsService().verify_reproducibility(
            "SS1", ss1_up_series()
        )
        assert payload["available"] is True
        assert payload["runs"] == 2
        assert payload["reproduced"] is True
        assert payload["identical"] == 2
        assert "not a predictive accuracy" in payload["note"]

    def test_reproducibility_unavailable_without_detector(self):
        unimplemented = next(
            key for key, spec in SPEC_BY_KEY.items() if not spec.detector_key
        )
        payload = RecognitionMetricsService().verify_reproducibility(
            unimplemented, ss1_up_series()
        )
        assert payload["available"] is False


# ---------------------------------------------------------------------------
# R7 - binary settlement evaluation
# ---------------------------------------------------------------------------
class TestSettlement:
    def test_missing_quotes_is_unverifiable(self):
        record = BookSettlementService().evaluate(direction="bullish")
        assert record["status"] == "unverifiable"
        assert record["verifiable"] is False
        assert "platform" in record["reason"]
        summary = BookSettlementService().summarize([record])
        assert summary["win_rate"] is None
        assert summary["verifiable"] == 0
        assert summary["unverifiable"] == 1
        assert summary["overall_status"] == "UNVERIFIABLE"
        assert summary["approved_for_decision_use"] is False

    def test_otc_prediction_refuses_mt5_source(self):
        record = BookSettlementService().evaluate(
            direction="bullish",
            entry_quote=1.1,
            settlement_quote=1.2,
            price_source="mt5",
            market_type="otc",
        )
        assert record["status"] == "refused"
        assert record["verifiable"] is False
        assert record["reason_code"] == "INCOMPATIBLE_FEEDS"
        assert "OTC" in record["reason"]

    def test_otc_prediction_allows_platform_quotes(self):
        record = BookSettlementService().evaluate(
            direction="bullish",
            entry_quote=1.1,
            settlement_quote=1.2,
            price_source="platform_otc",
            market_type="otc",
        )
        assert record["status"] == "win"
        assert record["verifiable"] is True

    def test_win_loss_tie_math(self):
        service = BookSettlementService()
        win = service.evaluate(
            direction="bullish",
            entry_quote=1.1000,
            settlement_quote=1.1005,
            price_source="platform",
            payout_rate=80,
            stake=1.0,
        )
        assert win["status"] == "win"
        assert win["payout"] == pytest.approx(1.8)
        assert win["net"] == pytest.approx(0.8)

        loss = service.evaluate(
            direction="bearish",
            entry_quote=1.1000,
            settlement_quote=1.1005,
            price_source="platform",
            stake=1.0,
        )
        assert loss["status"] == "loss"
        assert loss["payout"] == 0.0
        assert loss["net"] == pytest.approx(-1.0)

        tie = service.evaluate(
            direction="bullish",
            entry_quote=1.1000,
            settlement_quote=1.1000,
            price_source="platform",
        )
        assert tie["status"] == "tie"
        assert tie["verifiable"] is True

    def test_summarize_counts_only_verified_settlements(self):
        service = BookSettlementService()
        records = [
            service.evaluate(
                direction="bullish",
                entry_quote=1.1,
                settlement_quote=1.2,
                price_source="platform",
            ),
            service.evaluate(direction="bullish"),  # unverifiable
            service.evaluate(
                direction="bullish",
                entry_quote=1.1,
                settlement_quote=1.0,
                price_source="platform",
            ),
        ]
        summary = service.summarize(records)
        assert summary["verifiable"] == 2
        assert summary["wins"] == 1
        assert summary["losses"] == 1
        assert summary["unverifiable"] == 1
        assert summary["win_rate"] == pytest.approx(0.5)
        assert summary["overall_status"] == "PARTIAL"
        assert summary["sufficient_data"] is False
        assert "below the" in summary["insufficient_reason"]
        assert "never counted as wins" in summary["warning"]

    def test_summarize_threshold_with_enough_settlements(self):
        service = BookSettlementService()
        records = [
            service.evaluate(
                direction="bullish",
                entry_quote=1.0,
                settlement_quote=1.1,
                price_source="platform",
            )
            for _ in range(DEFAULT_MIN_SIGNALS)
        ]
        summary = service.summarize(records)
        assert summary["sufficient_data"] is True
        assert summary["win_rate"] == 1.0
        lo, hi = summary["wilson_95"]
        assert lo is not None and hi is not None and lo < 1.0

    def test_settlement_scope_is_not_direction_scope(self):
        assert SETTLEMENT_METRIC_SCOPE == "binary_settlement"
        assert SETTLEMENT_METRIC_SCOPE != METRIC_SCOPE


# ---------------------------------------------------------------------------
# R8 - immutable paper forward predictions
# ---------------------------------------------------------------------------
class TestPaperForward:
    @staticmethod
    def _enable_ss1() -> BookStrategy:
        BookStrategy.objects.filter(key="SS1").update(recognition_enabled=True)
        return BookStrategy.objects.get(key="SS1")

    def _prediction(self, **kwargs) -> PaperForwardPrediction:
        self._enable_ss1()
        created = PaperForwardService().record(
            stamped(ss1_up_series()),
            instrument="EURUSD",
            timeframe="M5",
            source="mt5:EURUSD:M5",
            last_candle_closed=True,
            **kwargs,
        )
        assert created, "expected the SS1 setup to record one prediction"
        return created[0]

    def test_record_writes_frozen_pending_prediction(self):
        self._enable_ss1()
        candles = stamped(ss1_up_series())
        created = PaperForwardService().record(
            candles,
            instrument="EURUSD",
            timeframe="M5",
            market_type="regular",
            source="mt5:EURUSD:M5",
            last_candle_closed=True,
        )
        assert len(created) == 1
        prediction = created[0]
        assert prediction.strategy.key == "SS1"
        assert prediction.direction == "bullish"
        assert prediction.status == PaperForwardPrediction.PENDING
        assert prediction.payload_sha256 == payload_digest(prediction.prediction_payload)
        assert prediction.verify_integrity() is True
        assert prediction.prediction_payload["written_before_outcome"] is True
        assert prediction.signal_candle_close_time == (
            prediction.signal_candle_open_time + M5
        )
        assert prediction.signal_close_price == candles[-1]["close"]
        assert prediction.outcome_basis == "next_candle_close_vs_signal_close"
        assert prediction.settlement_status == "not_evaluated"

    def test_record_dedupes_same_signal_candle(self):
        self._enable_ss1()
        candles = stamped(ss1_up_series())
        service = PaperForwardService()
        first = service.record(
            candles,
            instrument="EURUSD",
            timeframe="M5",
            source="mt5:EURUSD:M5",
            last_candle_closed=True,
        )
        second = service.record(
            candles,
            instrument="EURUSD",
            timeframe="M5",
            source="mt5:EURUSD:M5",
            last_candle_closed=True,
        )
        assert len(first) == 1
        assert second == []
        assert PaperForwardPrediction.objects.count() == 1

    def test_record_gates(self):
        service = PaperForwardService()
        self._enable_ss1()
        candles = stamped(ss1_up_series())
        assert service.record(
            candles, instrument="EURUSD", timeframe="M5", source="s",
            last_candle_closed=False,
        ) == []
        assert service.record(
            candles, instrument="EURUSD", timeframe="X1", source="s",
            last_candle_closed=True,
        ) == []
        no_time = [{k: v for k, v in c.items() if k != "open_time"} for c in candles]
        assert service.record(
            no_time, instrument="EURUSD", timeframe="M5", source="s",
            last_candle_closed=True,
        ) == []

    def test_record_requires_recognition_enabled(self):
        # nobody enabled -> nothing recorded
        assert PaperForwardService().record(
            stamped(ss1_up_series()),
            instrument="EURUSD",
            timeframe="M5",
            source="s",
            last_candle_closed=True,
        ) == []

    def test_stale_confirmation_never_recorded(self):
        self._enable_ss1()
        stale = stamped(with_outcome(ss1_up_series()))
        assert PaperForwardService().record(
            stale,
            instrument="EURUSD",
            timeframe="M5",
            source="s",
            last_candle_closed=True,
        ) == []

    def test_prediction_identity_is_immutable(self):
        prediction = self._prediction()

        prediction.direction = "bearish"
        with pytest.raises(PredictionImmutableError, match="direction is immutable"):
            prediction.save()

        prediction.refresh_from_db()
        prediction.signal_close_price = 9.99
        with pytest.raises(PredictionImmutableError):
            prediction.save()

        prediction.refresh_from_db()
        prediction.instrument = "GBPUSD"
        with pytest.raises(PredictionImmutableError):
            prediction.save()

        prediction.refresh_from_db()
        prediction.prediction_payload = {"tampered": True}
        with pytest.raises(PredictionImmutableError):
            prediction.save()

    def test_manual_status_change_blocked(self):
        prediction = self._prediction()
        prediction.status = PaperForwardPrediction.RESOLVED
        with pytest.raises(PredictionImmutableError, match="status may only change"):
            prediction.save()

    def test_resolve_once_from_exact_outcome_window(self):
        prediction = self._prediction()
        service = PaperForwardService()
        candles = stamped(with_outcome(ss1_up_series()))
        resolved = service.resolve(
            candles, instrument="EURUSD", timeframe="M5", source="mt5:EURUSD:M5"
        )
        assert len(resolved) == 1
        prediction.refresh_from_db()
        assert prediction.status == PaperForwardPrediction.RESOLVED
        assert prediction.outcome_up is True  # outcome closes above the signal close
        assert prediction.outcome_correct is True
        assert prediction.outcome_candle_open_time == prediction.signal_candle_close_time
        assert prediction.resolved_at is not None

        # one-shot: same window resolves nothing the second time
        assert service.resolve(
            candles, instrument="EURUSD", timeframe="M5", source="mt5:EURUSD:M5"
        ) == []
        with pytest.raises(PredictionImmutableError, match="already resolved"):
            prediction.resolve(
                outcome_candle={
                    "open_time": prediction.signal_candle_close_time,
                    "close": 1.0,
                    "complete": True,
                }
            )

    def test_resolve_refuses_forming_and_off_by_one_windows(self):
        prediction = self._prediction()
        service = PaperForwardService()

        # outcome candle not present yet
        assert service.resolve(
            stamped(ss1_up_series()),
            instrument="EURUSD",
            timeframe="M5",
            source="mt5:EURUSD:M5",
        ) == []

        # forming outcome candle is never read as an outcome
        forming = stamped(with_outcome(ss1_up_series()))
        forming[-1]["complete"] = False
        assert service.resolve(
            forming, instrument="EURUSD", timeframe="M5", source="mt5:EURUSD:M5"
        ) == []
        prediction.refresh_from_db()
        assert prediction.status == PaperForwardPrediction.PENDING

        # off-by-one window is rejected outright
        with pytest.raises(PredictionImmutableError, match="window mismatch"):
            prediction.resolve(
                outcome_candle={
                    "open_time": prediction.signal_candle_open_time,
                    "close": 1.5,
                    "complete": True,
                }
            )

    def test_resolve_scopes_to_its_own_feed(self):
        prediction = self._prediction()
        service = PaperForwardService()
        candles = stamped(with_outcome(ss1_up_series()))
        # a different source label cannot resolve this prediction
        assert service.resolve(
            candles, instrument="EURUSD", timeframe="M5", source="other:feed"
        ) == []
        prediction.refresh_from_db()
        assert prediction.status == PaperForwardPrediction.PENDING

    def test_resolved_outcome_is_immutable(self):
        prediction = self._prediction()
        PaperForwardService().resolve(
            stamped(with_outcome(ss1_up_series())),
            instrument="EURUSD",
            timeframe="M5",
            source="mt5:EURUSD:M5",
        )
        prediction.refresh_from_db()
        prediction.outcome_up = False
        with pytest.raises(PredictionImmutableError, match="outcome_up is immutable"):
            prediction.save()

    def test_payload_tampering_is_detectable(self):
        prediction = self._prediction()
        PaperForwardPrediction.objects.filter(pk=prediction.pk).update(
            prediction_payload={"tampered": True}
        )
        prediction.refresh_from_db()
        assert prediction.verify_integrity() is False
        summary = PaperForwardService().summary([prediction])
        assert summary["integrity"]["mismatches"] == 1

    def test_summary_reports_pending_and_insufficiency_honestly(self):
        self._prediction()
        service = PaperForwardService()
        service.resolve(
            stamped(with_outcome(ss1_up_series())),
            instrument="EURUSD",
            timeframe="M5",
            source="mt5:EURUSD:M5",
        )
        pending = service.record(
            stamped(ss1_up_series(), start=START - M5),
            instrument="EURUSD",
            timeframe="M5",
            source="other",
            last_candle_closed=True,
        )
        assert len(pending) == 1

        summary = service.summary()
        assert summary["metric_scope"] == "next_candle_direction"
        assert summary["recorded"] == 2
        assert summary["resolved"] == 1
        assert summary["pending"] == 1
        assert summary["correct"] == 1
        assert summary["accuracy"] == 1.0
        assert summary["sufficient_data"] is False
        assert "below the" in summary["insufficient_reason"]
        assert summary["approved_for_decision_use"] is False
        assert "never change research_status" in summary["approval_effect"]
        assert summary["settlement_status_counts"].get("not_evaluated") == 2

    def test_settlement_bridge_gates_quotes_and_is_write_once(self):
        prediction = self._prediction()
        service = PaperForwardService()

        unverifiable = service.settle(prediction)
        assert unverifiable["status"] == "unverifiable"
        prediction.refresh_from_db()
        assert prediction.settlement_status == "unverifiable"

        # non-verified settlements may be re-evaluated once quotes arrive
        verified = service.settle(
            prediction,
            entry_quote=1.1,
            settlement_quote=1.2,
            price_source="platform",
            payout_rate=80,
        )
        assert verified["status"] == "win"
        prediction.refresh_from_db()
        assert prediction.settlement_status == "win"

        # verified settlements are frozen
        with pytest.raises(PredictionImmutableError, match="verified settlement"):
            service.settle(
                prediction,
                entry_quote=1.1,
                settlement_quote=1.0,
                price_source="platform",
            )

    def test_settlement_refuses_otc_on_mt5_quotes(self):
        prediction = self._prediction(market_type="otc")
        result = PaperForwardService().settle(
            prediction, entry_quote=1.1, settlement_quote=1.2, price_source="mt5"
        )
        assert result["status"] == "refused"
        assert result["reason_code"] == "INCOMPATIBLE_FEEDS"
        prediction.refresh_from_db()
        assert prediction.settlement_status == "refused"

    def test_paper_records_never_touch_research_or_approval(self):
        before = BookStrategy.objects.get(key="SS1")
        self._prediction()
        after = BookStrategy.objects.get(key="SS1")
        assert after.research_status == before.research_status
        assert after.decision_use_approved is False


# ---------------------------------------------------------------------------
# R9 - decision-engine integration, gated by approval
# ---------------------------------------------------------------------------
class TestDecisionIntegration:
    CONFLICTED = {
        "evidence": [
            {"rule_id": "pa.sr.zone.support", "detector": "support_resistance"},
            {
                "rule_id": "pa.sr.rejection.bullish",
                "detector": "support_resistance",
                "direction": "bullish",
            },
            {
                "rule_id": "pa.structure.bearish",
                "detector": "market_structure",
                "direction": "bearish",
            },
        ],
        "conflicts": [],
        "context": {},
    }

    @staticmethod
    def _approve_ss1() -> BookStrategy:
        BookStrategy.objects.filter(key="SS1").update(
            decision_use_approved=True, recognition_enabled=True
        )
        return BookStrategy.objects.get(key="SS1")

    def test_default_world_has_no_book_candidates(self):
        candles = book_candles(ss1_up_series())
        # sanity: the detector DOES confirm, so emptiness comes from the gate
        assert detect_ss1(candles).state == BookPatternState.CONFIRMED_PATTERN
        assert book_strategy_candidates(candles, last_candle_forming=False) == []

    def test_approval_gate_requires_both_switches(self):
        candles = book_candles(ss1_up_series())
        BookStrategy.objects.filter(key="SS1").update(decision_use_approved=True)
        assert book_strategy_candidates(candles, last_candle_forming=False) == []

        BookStrategy.objects.filter(key="SS1").update(
            decision_use_approved=False, recognition_enabled=True
        )
        assert book_strategy_candidates(candles, last_candle_forming=False) == []

    def test_approved_enabled_yields_fresh_confirmed_candidate(self):
        self._approve_ss1()
        candles = book_candles(ss1_up_series())
        candidates = book_strategy_candidates(
            candles, last_candle_forming=False, instrument="EURUSD", timeframe="M1"
        )
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.direction == EvaluationDirection.UP
        assert candidate.strategy_family == StrategyFamily.BOOK_PATTERN
        assert candidate.status == CandidateStatus.VALID
        assert candidate.metrics["book_key"] == "SS1"
        assert candidate.metrics["probability_status"] == PROBABILITY_STATUS
        assert candidate.metrics["decision_use_approved"] is True
        assert "explicit human approval" in candidate.supporting_evidence[0]["note"]

    def test_forming_candle_blocks_candidates(self):
        self._approve_ss1()
        candles = book_candles(ss1_up_series())
        assert book_strategy_candidates(candles, last_candle_forming=True) == []

    def test_stale_confirmation_never_offered(self):
        self._approve_ss1()
        full = book_candles(with_outcome(ss1_up_series()))
        result = detect_ss1(full)
        assert result.state == BookPatternState.CONFIRMED_PATTERN
        assert result.completed_at != len(full) - 1  # stale, not fresh
        assert book_strategy_candidates(full, last_candle_forming=False) == []

    def test_detector_exception_degrades_to_no_candidates(self, monkeypatch):
        row = self._approve_ss1()

        def boom(*args, **kwargs):
            raise RuntimeError("detector crashed")

        monkeypatch.setitem(BOOK_DETECTORS, row.detector_key, boom)
        assert book_strategy_candidates(
            book_candles(ss1_up_series()), last_candle_forming=False
        ) == []

    def test_engine_default_unchanged(self):
        result = EvaluationService().evaluate(eval_input())
        assert result["direction"] == EvaluationDirection.NO_TRADE
        assert result["statistical_probability_status"] == (
            ProbabilityStatus.UNAVAILABLE_UNCALIBRATED
        )
        assert all(
            candidate["strategy_family"] != StrategyFamily.BOOK_PATTERN
            for candidate in result["candidates"]
        )

    def test_engine_appends_book_candidate_when_approved(self):
        self._approve_ss1()
        result = EvaluationService().evaluate(
            eval_input(candles=book_candles(ss1_up_series()))
        )
        assert result["statistical_probability_status"] == (
            ProbabilityStatus.UNAVAILABLE_UNCALIBRATED
        )
        book = [
            candidate
            for candidate in result["candidates"]
            if candidate["strategy_family"] == StrategyFamily.BOOK_PATTERN
        ]
        assert len(book) == 1
        assert book[0]["direction"] == EvaluationDirection.UP
        assert book[0]["metrics"]["book_key"] == "SS1"

    def test_no_trade_safeguards_survive_book_candidate(self):
        self._approve_ss1()
        result = EvaluationService().evaluate(
            eval_input(
                candles=book_candles(ss1_up_series()),
                price_action_result=self.CONFLICTED,
            )
        )
        assert result["direction"] == EvaluationDirection.NO_TRADE
        assert result["primary_reason_code"] == (
            InvalidationReasonCode.STRONG_CONTRADICTION
        )
        # the book candidate is present but the decision stayed NO TRADE
        assert any(
            candidate["strategy_family"] == StrategyFamily.BOOK_PATTERN
            for candidate in result["candidates"]
        )
        assert result["statistical_probability_status"] == (
            ProbabilityStatus.UNAVAILABLE_UNCALIBRATED
        )

    def test_unfinished_candle_blocks_engine_book_candidate(self):
        self._approve_ss1()
        result = EvaluationService().evaluate(
            eval_input(candles=book_candles(ss1_up_series(), final_complete=False))
        )
        assert all(
            candidate["strategy_family"] != StrategyFamily.BOOK_PATTERN
            for candidate in result["candidates"]
        )


# ---------------------------------------------------------------------------
# R10 - research dashboard
# ---------------------------------------------------------------------------
class TestResearchDashboard:
    @pytest.fixture
    def member(self):
        return UserFactory(username="book-research-member")

    def test_research_page_requires_login(self, client):
        response = client.get(reverse("dashboard:book-strategies-research"))
        assert response.status_code == 302

    def test_research_page_renders_honest_metrics(self, client, member):
        client.force_login(member)
        response = client.get(reverse("dashboard:book-strategies-research"))
        assert response.status_code == 200
        content = response.content.decode()
        assert "pattern_recognition" in content
        assert NOT_COMPUTABLE_STATUS in content
        assert "No strategy is approved" in content
        assert "NO TRADE" in content
        # no approval control of any kind on this page
        assert "book-strategy-toggle" not in content
        assert "decision_use_approved=True" not in content

    def test_research_page_shows_persisted_runs_and_ranking(self, client, member):
        candles = with_outcome(ss1_up_series())
        BookBacktestService().run("SS1", candles, instrument="EURUSD", timeframe="M5")
        entry = {
            "strategy_key": "SS1",
            "name": "SS1",
            "validation": BookValidationService().validate("SS1", candles).as_dict(),
            "walk_forward": BookWalkForwardService()
            .run("SS1", candles, window=8)
            .as_dict(),
        }
        comparison = BookComparisonService().compare([entry])
        BacktestRun.objects.create(
            name="book comparison (1 run)",
            status="completed",
            strategy_config={"kind": COMPARISON_RUN_KIND},
            results={"comparison": comparison.as_dict()},
            sample_count=1,
        )

        client.force_login(member)
        content = client.get(reverse("dashboard:book-strategies-research")).content.decode()
        assert "Research ranking" in content
        assert TIER_INSUFFICIENT in content
        assert "not binary-option settlement" in content
        assert "SS1" in content

    def test_book_list_links_to_research(self, client, member):
        client.force_login(member)
        content = client.get(reverse("dashboard:book-strategies")).content.decode()
        assert reverse("dashboard:book-strategies-research") in content


# ---------------------------------------------------------------------------
# Commands - end-to-end integration for R1/R2/R8
# ---------------------------------------------------------------------------
class TestResearchCommands:
    @staticmethod
    def _import_dataset(series: list[dict], *, name: str = "bible-import") -> HistoricalDataset:
        dataset, _ = DatasetBuilder().import_ohlc(
            _rows(series),
            name=name,
            instrument="EURUSD",
            timeframe="M5",
            source="test_csv",
            source_file="eurusd.csv",
            source_sha256="deadbeef",
            importer="tester",
        )
        return dataset

    def test_backtest_command_dataset_mode(self, tmp_path):
        dataset = self._import_dataset(with_outcome(ss1_up_series()))
        out = tmp_path / "book_research.json"
        call_command(
            "backtest_book_strategies",
            "--dataset-id",
            str(dataset.pk),
            "--out",
            str(out),
            "--window",
            "8",
        )
        assert (
            BacktestRun.objects.filter(strategy_config__kind=BOOK_RUN_KIND).count()
            == len(IMPLEMENTED_SPEC_KEYS)
        )
        assert (
            BacktestRun.objects.filter(strategy_config__kind=COMPARISON_RUN_KIND).count()
            == 1
        )
        artifact = json.loads(out.read_text(encoding="utf-8"))
        assert artifact["metric_scope"] == METRIC_SCOPE
        assert artifact["dataset"]["kind"] == "historical_import"
        assert artifact["dataset"]["source_sha256"] == "deadbeef"
        assert len(artifact["backtests"]) == len(IMPLEMENTED_SPEC_KEYS)
        assert artifact["ranking"]["approved_for_decision_use"] is False

        ss1 = BookStrategy.objects.get(key="SS1")
        assert ss1.research_status == ResearchStatus.BACKTESTED
        assert ss1.decision_use_approved is False
        assert not BookStrategy.objects.filter(decision_use_approved=True).exists()
        assert not BookStrategy.objects.filter(
            research_status__in=[ResearchStatus.OOS_VALIDATED, ResearchStatus.APPROVED]
        ).exists()

    def test_backtest_command_keep_status(self, tmp_path):
        dataset = self._import_dataset(with_outcome(ss1_up_series()))
        call_command(
            "backtest_book_strategies",
            "--dataset-id",
            str(dataset.pk),
            "--out",
            str(tmp_path / "r.json"),
            "--keep-status",
        )
        assert BookStrategy.objects.get(key="SS1").research_status == ResearchStatus.IMPLEMENTED

    def test_backtest_command_requires_candles(self, tmp_path):
        with pytest.raises(CommandError, match="no complete candles"):
            call_command(
                "backtest_book_strategies", "--out", str(tmp_path / "r.json")
            )

    def test_backtest_command_missing_dataset_errors(self, tmp_path):
        with pytest.raises(CommandError, match="not found"):
            call_command(
                "backtest_book_strategies",
                "--dataset-id",
                "9999",
                "--out",
                str(tmp_path / "r.json"),
            )

    def test_validate_command_dataset_mode(self, tmp_path):
        dataset = self._import_dataset(with_outcome(ss1_up_series()))
        out = tmp_path / "validation.json"
        call_command(
            "validate_book_strategies",
            "--dataset-id",
            str(dataset.pk),
            "--out",
            str(out),
        )
        artifact = json.loads(out.read_text(encoding="utf-8"))
        assert artifact["import"]["source_sha256"] == "deadbeef"
        assert artifact["import"]["dataset_id"] == dataset.pk
        assert len(artifact["reports"]) == len(IMPLEMENTED_SPEC_KEYS)
        assert artifact["reports"][0]["dataset"]["import"]["dataset_id"] == dataset.pk
        assert artifact["reports"][0]["metric_scope"] == METRIC_SCOPE

    def test_record_and_resolve_commands_end_to_end(self):
        record_set = self._import_dataset(ss1_up_series(), name="record-window")
        BookStrategy.objects.filter(key="SS1").update(recognition_enabled=True)

        call_command("record_paper_predictions", "--dataset-id", str(record_set.pk))
        assert PaperForwardPrediction.objects.count() == 1
        prediction = PaperForwardPrediction.objects.get()
        assert prediction.status == PaperForwardPrediction.PENDING
        assert prediction.source == f"historical_import:{record_set.name}"

        # the record dataset has no outcome candle yet - nothing is guessed
        call_command("resolve_paper_predictions", "--dataset-id", str(record_set.pk))
        prediction.refresh_from_db()
        assert prediction.status == PaperForwardPrediction.PENDING

        # a superset dataset under the same import label resolves the outcome
        full = self._import_dataset(with_outcome(ss1_up_series()), name=record_set.name)
        call_command("resolve_paper_predictions", "--dataset-id", str(full.pk))
        prediction.refresh_from_db()
        assert prediction.status == PaperForwardPrediction.RESOLVED
        assert prediction.outcome_up is True
        assert prediction.outcome_correct is True





