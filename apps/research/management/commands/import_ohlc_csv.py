"""Import OHLC candles from a CSV file with full data provenance.

Expected header (case-insensitive, common aliases accepted):

    open_time,open,high,low,close[,volume]

``open_time`` may be ``time`` / ``timestamp`` / ``datetime``; ISO-8601
timestamps (naive values are assumed UTC and flagged). Rows failing OHLC
validation or duplicating a timestamp are REJECTED and recorded - never
repaired or invented. Gaps against the timeframe interval are flagged on the
dataset; missing candles are never fabricated.

Provenance recorded on the dataset: source file name, SHA-256 of the file,
importer, import time, row counts, reject reasons and gap list.

Usage:
    python manage.py import_ohlc_csv data/eurusd_m5.csv --instrument EURUSD --timeframe M5
"""

from __future__ import annotations

import csv
import getpass
import hashlib
import io
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.research.services.dataset_builder import DatasetBuilder

TIME_ALIASES = ("open_time", "time", "timestamp", "datetime")
OHLC_ALIASES = {"open": ("open",), "high": ("high",), "low": ("low",), "close": ("close",)}


class Command(BaseCommand):
    help = "Import OHLC candles from CSV with data provenance (no fabricated rows)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("path", help="Path to the CSV file.")
        parser.add_argument("--instrument", required=True, help="e.g. EURUSD.")
        parser.add_argument("--timeframe", required=True, help="e.g. M5.")
        parser.add_argument("--name", default="", help="Dataset name (default: file name).")
        parser.add_argument("--source", default="csv", help="Provenance source label.")
        parser.add_argument("--market-type", dest="market_type", default="", choices=["", "regular", "otc"])

    def handle(self, *args: object, **options: object) -> str:
        path = Path(str(options["path"]))
        if not path.exists():
            raise CommandError(f"file not found: {path}")
        raw = path.read_bytes()
        if not raw:
            raise CommandError("file is empty - nothing to import")

        sha256 = hashlib.sha256(raw).hexdigest()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise CommandError("CSV has no header row")
        header_map = {(name or "").strip().lower(): name for name in reader.fieldnames}

        time_key = next((header_map[a] for a in TIME_ALIASES if a in header_map), None)
        if time_key is None:
            raise CommandError(
                f"missing timestamp column: expected one of {', '.join(TIME_ALIASES)}"
            )
        column_keys: dict[str, str] = {}
        for field, aliases in OHLC_ALIASES.items():
            found = next((header_map[a] for a in aliases if a in header_map), None)
            if found is None:
                raise CommandError(
                    f"missing column {field!r}; header was: "
                    f"{', '.join(reader.fieldnames)}"
                )
            column_keys[field] = found
        volume_key = header_map.get("volume", header_map.get("tick_volume"))

        rows: list[dict[str, Any]] = []
        for row in reader:
            record: dict[str, Any] = {"open_time": (row.get(time_key) or "").strip()}
            for field, key in column_keys.items():
                record[field] = (row.get(key) or "").strip()
            if volume_key:
                record["volume"] = (row.get(volume_key) or "").strip() or None
            rows.append(record)

        try:
            dataset, report = DatasetBuilder().import_ohlc(
                rows,
                name=str(options["name"] or path.name),
                instrument=str(options["instrument"]),
                timeframe=str(options["timeframe"]),
                source=str(options["source"]),
                source_file=path.name,
                source_sha256=sha256,
                importer=self._importer(),
                market_type=str(options["market_type"] or ""),
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        provenance = report["provenance"]
        self.stdout.write(
            f"imported {report['candles_imported']} candles into dataset "
            f"#{dataset.pk} '{dataset.name}' ({dataset.instrument} {dataset.timeframe})"
        )
        self.stdout.write(
            f"rejected {report['rows_rejected']} rows "
            f"({report['reject_reasons'] or 'no reject reasons'}), "
            f"gaps detected: {report['gap_count']}, "
            f"is_validated={report['is_validated']}"
        )
        self.stdout.write(
            f"provenance: source_file={provenance['source_file']} "
            f"sha256={provenance['source_sha256']} importer={provenance['importer']} "
            f"imported_at={provenance['imported_at']}"
        )
        for flag in dataset.data_quality_flags[:10]:
            self.stdout.write(f"flag: {flag}")
        self.stdout.write(self.style.SUCCESS(f"dataset #{dataset.pk} ready"))
        return f"dataset {dataset.pk}: {report['candles_imported']} candles"

    @staticmethod
    def _importer() -> str:
        try:
            return getpass.getuser()
        except Exception:
            return "unknown"
