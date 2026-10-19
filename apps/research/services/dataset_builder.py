# apps/research/services/dataset_builder.py
"""Historical dataset management (Step 3), OHLC import with provenance (Phase 13)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from django.utils.dateparse import parse_datetime

from apps.research.models import HistoricalCandle, HistoricalDataset

#: Expected candle interval per timeframe code, used ONLY to *detect* gaps.
#: Missing candles are recorded as flags - never fabricated.
TIMEFRAME_INTERVALS: dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

#: Cap so one pathological file cannot bloat the flags list.
MAX_FLAGGED_ROWS = 50


class DatasetBuilder:
    """Build and validate historical datasets.

    Validation includes: missing intervals, duplicates, invalid OHLC,
    timezone errors, feed changes. Never fabricate missing data.
    """

    def build_dataset(
        self,
        candles_data: list[dict[str, Any]],
        name: str = "",
        instrument: str = "",
        timeframe: str = "",
        owner=None,
    ) -> HistoricalDataset:
        dataset = HistoricalDataset(
            name=name or f"Dataset {datetime.utcnow().isoformat()}",
            instrument=instrument,
            timeframe=timeframe,
            owner=owner,
            candle_count=len(candles_data),
            start_time=self._get_start(candles_data),
            end_time=self._get_end(candles_data),
            is_validated=False,
        )
        dataset.save()
        return dataset

    def validate_ohlc(self, open_p, high_p, low_p, close_p) -> bool:
        """Validate OHLC relationships."""
        if low_p > high_p:
            return False
        if not (low_p <= open_p <= high_p and low_p <= close_p <= high_p):
            return False
        return True

    def check_duplicates(self, candles_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Check for duplicate timestamps."""
        seen = set()
        issues = []
        for i, c in enumerate(candles_data):
            ts = c.get("open_time")
            if ts and ts in seen:
                issues.append({"index": i, "type": "duplicate_timestamp", "time": ts})
            seen.add(ts)
        return issues

    def check_gaps(
        self, candles_data: list[dict[str, Any]], timeframe: str
    ) -> list[dict[str, Any]]:
        """Check for missing intervals. Never fabricate."""
        issues = []
        if len(candles_data) < 2:
            return issues
        expected = TIMEFRAME_INTERVALS.get(timeframe.upper())
        if expected is None:
            return issues
        previous: datetime | None = None
        for i, c in enumerate(candles_data):
            ts = c.get("open_time")
            if not isinstance(ts, datetime) or previous is None:
                previous = ts if isinstance(ts, datetime) else None
                continue
            delta = (ts - previous).total_seconds()
            if delta > expected:
                missing = int(delta // expected) - 1
                issues.append(
                    {
                        "type": "gap",
                        "after_index": i - 1,
                        "from": previous.isoformat(),
                        "to": ts.isoformat(),
                        "missing_intervals": missing,
                    }
                )
            previous = ts
        return issues

    # ------------------------------------------------------------------
    # Historical OHLC import with data provenance (Phase 13, requirement 1)
    # ------------------------------------------------------------------
    def import_ohlc(
        self,
        candles_data: list[dict[str, Any]],
        *,
        name: str = "",
        instrument: str = "",
        timeframe: str = "",
        source: str = "unknown",
        source_file: str = "",
        source_sha256: str = "",
        importer: str = "",
        market_type: str = "",
        owner=None,
    ) -> tuple[HistoricalDataset, dict[str, Any]]:
        """Validate, import and record provenance for a raw OHLC series.

        Every row is validated (timestamp parseable, OHLC relationship holds,
        no duplicate timestamp) and rows are accepted in chronological order.
        Rejected rows and detected gaps are *recorded* - nothing is repaired,
        forward-filled or invented. The dataset row carries the source label
        and a full provenance block (file name, SHA-256, importer, import
        time, row counts, reject reasons, gap list) in ``metadata``.
        """
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        flags: list[dict[str, Any]] = []
        assumed_utc = False

        def _reject(index: int, reason: str, raw: Any) -> None:
            rejected.append({"index": index, "reason": reason, "raw": repr(raw)[:120]})

        for index, raw in enumerate(candles_data):
            if not isinstance(raw, dict):
                _reject(index, "row_is_not_an_object", raw)
                continue
            open_time = raw.get("open_time")
            if isinstance(open_time, str):
                parsed = parse_datetime(open_time)
                if parsed is None:
                    _reject(index, "unparseable_timestamp", open_time)
                    continue
                open_time = parsed
            if not isinstance(open_time, datetime):
                _reject(index, "missing_timestamp", raw.get("open_time"))
                continue
            if open_time.tzinfo is None:
                open_time = open_time.replace(tzinfo=UTC)
                assumed_utc = True
            try:
                open_p = float(raw["open"])
                high_p = float(raw["high"])
                low_p = float(raw["low"])
                close_p = float(raw["close"])
            except (KeyError, TypeError, ValueError):
                _reject(index, "missing_or_non_numeric_ohlc", raw)
                continue
            if not self.validate_ohlc(open_p, high_p, low_p, close_p):
                _reject(index, "ohlc_relationship_violated", raw)
                continue
            tick_volume = raw.get("volume", raw.get("tick_volume"))
            try:
                tick_volume = float(tick_volume) if tick_volume is not None else None
            except (TypeError, ValueError):
                tick_volume = None
            accepted.append(
                {
                    "open_time": open_time,
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "close": close_p,
                    "tick_volume": tick_volume,
                }
            )

        original_order = [row["open_time"] for row in accepted]
        accepted.sort(key=lambda row: row["open_time"])
        if [row["open_time"] for row in accepted] != original_order:
            flags.append({"type": "unsorted_input_reordered"})

        seen: set[datetime] = set()
        deduped: list[dict[str, Any]] = []
        duplicates = 0
        for row in accepted:
            if row["open_time"] in seen:
                duplicates += 1
                rejected.append(
                    {
                        "index": -1,
                        "reason": "duplicate_timestamp",
                        "raw": row["open_time"].isoformat(),
                    }
                )
                continue
            seen.add(row["open_time"])
            deduped.append(row)
        accepted = deduped

        if assumed_utc:
            flags.append({"type": "naive_timestamps_assumed_utc"})

        # Gap detection (flags only - missing candles are never invented).
        gaps = self.check_gaps(accepted, timeframe)
        flags.extend(gaps[:MAX_FLAGGED_ROWS])
        if len(gaps) > MAX_FLAGGED_ROWS:
            flags.append(
                {
                    "type": "gap_list_truncated",
                    "total_gaps": len(gaps),
                    "listed": MAX_FLAGGED_ROWS,
                }
            )

        reject_reasons: dict[str, int] = {}
        for item in rejected:
            reject_reasons[item["reason"]] = reject_reasons.get(item["reason"], 0) + 1

        provenance = {
            "tool": "DatasetBuilder.import_ohlc",
            "source": source,
            "source_file": source_file,
            "source_sha256": source_sha256,
            "importer": importer,
            "imported_at": datetime.now(UTC).isoformat(),
            "timeframe": timeframe,
            "market_type": market_type,
            "rows_presented": len(candles_data),
            "rows_imported": len(accepted),
            "rows_rejected": len(rejected),
            "reject_reasons": reject_reasons,
            "gap_count": len(gaps),
            "expected_interval_seconds": TIMEFRAME_INTERVALS.get(timeframe.upper()),
        }

        if not accepted:
            raise ValueError(
                "import rejected every row - nothing was written (no candle is "
                f"fabricated; reject reasons: {reject_reasons})"
            )

        dataset = HistoricalDataset(
            name=name or f"import {source_file or source} {provenance['imported_at']}",
            instrument=instrument,
            timeframe=timeframe,
            market_type=market_type,
            owner=owner,
            source=source[:64],
            candle_count=len(accepted),
            start_time=accepted[0]["open_time"],
            end_time=accepted[-1]["open_time"],
            data_quality_flags=flags,
            is_validated=(len(rejected) == 0 and len(gaps) == 0),
            metadata={"provenance": provenance},
        )
        dataset.save()
        HistoricalCandle.objects.bulk_create(
            [
                HistoricalCandle(
                    dataset=dataset,
                    open_time=row["open_time"],
                    close_time=row["open_time"] + timedelta(seconds=TIMEFRAME_INTERVALS.get(timeframe.upper(), 0)),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    tick_volume=row["tick_volume"],
                    is_complete=True,
                )
                for row in accepted
            ],
            batch_size=500,
        )

        report = {
            "dataset_id": dataset.pk,
            "name": dataset.name,
            "instrument": instrument,
            "timeframe": timeframe,
            "candles_imported": len(accepted),
            "rows_rejected": len(rejected),
            "reject_reasons": reject_reasons,
            "rejected_examples": rejected[:MAX_FLAGGED_ROWS],
            "gap_count": len(gaps),
            "gaps": gaps[:MAX_FLAGGED_ROWS],
            "is_validated": dataset.is_validated,
            "provenance": provenance,
        }
        return dataset, report

    def _get_start(self, candles_data: list[dict[str, Any]]):
        if not candles_data:
            return None
        return candles_data[0].get("open_time")

    def _get_end(self, candles_data: list[dict[str, Any]]):
        if not candles_data:
            return None
        return candles_data[-1].get("open_time")


__all__ = ["DatasetBuilder"]
