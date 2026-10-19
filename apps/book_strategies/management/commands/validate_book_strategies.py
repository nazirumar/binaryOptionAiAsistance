"""Run chronological book-strategy validation over stored market candles.

Reads genuine candles from the configured database (default: all symbols,
per timeframe; or an imported historical dataset via ``--dataset-id``),
replays each implemented detector forward in time with no future leakage,
and writes a JSON artifact the validation report can cite.

Every number in the artifact is computed from the actual candle rows - this
command can only report what the data supports, including "no signals".

Usage:
    python manage.py validate_book_strategies
    python manage.py validate_book_strategies --symbol EURUSD --timeframe M1
    python manage.py validate_book_strategies --dataset-id 3
    python manage.py validate_book_strategies --out docs/artifacts/book_validation.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.book_strategies.constants import IMPLEMENTED_SPEC_KEYS
from apps.book_strategies.services.sources import (
    dataset_candles,
    mt5_candle_groups,
    require_groups,
)
from apps.book_strategies.services.validation import (
    DEFAULT_MIN_SIGNALS,
    DEFAULT_PAYOUT_RATE,
    BookValidationService,
)


class Command(BaseCommand):
    help = "Chronological replay validation for implemented book strategies."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--symbol", default="", help="Canonical symbol (e.g. EURUSD).")
        parser.add_argument("--timeframe", default="", help="Timeframe (e.g. M1, M5).")
        parser.add_argument(
            "--dataset-id",
            type=int,
            default=0,
            help="Validate over an imported historical dataset instead of MT5 rows.",
        )
        parser.add_argument(
            "--out",
            default="docs/artifacts/book_validation.json",
            help="Path of the JSON artifact to write.",
        )
        parser.add_argument("--payout", type=float, default=DEFAULT_PAYOUT_RATE)

    def handle(self, *args: object, **options: object) -> str:
        symbol = str(options["symbol"] or "")
        timeframe = str(options["timeframe"] or "")
        out_path = Path(str(options["out"]))
        payout = float(options["payout"])
        dataset = None
        import_descriptor: dict[str, Any] | None = None

        if int(options["dataset_id"] or 0):
            try:
                dataset, loaded = dataset_candles(int(options["dataset_id"]))
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            groups = {
                (dataset.instrument or "imported", dataset.timeframe or "M1"): loaded
            }
            provenance = (dataset.metadata or {}).get("provenance", {})
            import_descriptor = {
                "dataset_id": dataset.pk,
                "name": dataset.name,
                "source": dataset.source,
                "source_file": provenance.get("source_file", ""),
                "source_sha256": provenance.get("source_sha256", ""),
            }
        else:
            groups = mt5_candle_groups(symbol=symbol, timeframe=timeframe)
            try:
                require_groups(groups)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc

        service = BookValidationService()
        reports: list[dict[str, Any]] = []
        lines: list[str] = []
        for (canonical, tf), candles in sorted(groups.items()):
            for strategy_key in IMPLEMENTED_SPEC_KEYS:
                report = service.validate(
                    strategy_key,
                    candles,
                    payout_rate=payout,
                    instrument=canonical,
                    timeframe=tf,
                )
                payload = report.as_dict()
                payload["dataset"]["symbol"] = canonical
                payload["dataset"]["timeframe"] = tf
                if import_descriptor is not None:
                    payload["dataset"]["import"] = dict(import_descriptor)
                reports.append(payload)
                pooled = payload["splits"]["pooled"]
                lines.append(
                    f"{strategy_key} {canonical}/{tf}: "
                    f"{pooled['n_signals']} signals, "
                    f"accuracy={pooled['accuracy']}, "
                    f"sufficient={payload['sufficient_data']}"
                    + (
                        f" ({payload['insufficient_reason']})"
                        if payload["insufficient_reason"]
                        else ""
                    )
                )

        artifact = {
            "generated_by": "manage.py validate_book_strategies",
            "metric_scope": "next_candle_direction",
            "min_signals_for_claim": DEFAULT_MIN_SIGNALS,
            "import": import_descriptor,
            "reports": reports,
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")

        summary = "\n".join(lines)
        self.stdout.write(summary)
        self.stdout.write(self.style.SUCCESS(f"\nwrote {out_path} ({len(reports)} reports)"))
        return f"{len(reports)} reports -> {out_path}"
