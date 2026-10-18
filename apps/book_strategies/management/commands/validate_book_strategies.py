"""Run chronological book-strategy validation over stored market candles.

Reads genuine candles from the configured database (default: all symbols,
per timeframe), replays each implemented detector forward in time with no
future leakage, and writes a JSON artifact the validation report can cite.

Every number in the artifact is computed from the actual candle rows - this
command can only report what the data supports, including "no signals".

Usage:
    python manage.py validate_book_strategies
    python manage.py validate_book_strategies --symbol EURUSD --timeframe M1
    python manage.py validate_book_strategies --out docs/artifacts/book_validation.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import QuerySet

from apps.book_strategies.constants import IMPLEMENTED_SPEC_KEYS
from apps.book_strategies.services.validation import (
    DEFAULT_MIN_SIGNALS,
    DEFAULT_PAYOUT_RATE,
    BookValidationService,
)
from apps.market_data.models import MarketCandle


class Command(BaseCommand):
    help = "Chronological replay validation for implemented book strategies."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--symbol", default="", help="Canonical symbol (e.g. EURUSD).")
        parser.add_argument("--timeframe", default="", help="Timeframe (e.g. M1, M5).")
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

        qs: QuerySet[MarketCandle] = MarketCandle.objects.filter(
            is_complete=True, quality_status="ok"
        )
        if symbol:
            qs = qs.filter(symbol__canonical=symbol)
        if timeframe:
            qs = qs.filter(timeframe=timeframe)
        if not qs.exists():
            raise CommandError(
                "no complete candles matched the filter - validation needs a "
                "real dataset (nothing is fabricated when data is absent)"
            )

        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in qs.order_by("symbol__canonical", "timeframe", "open_time"):
            key = (row.symbol.canonical, row.timeframe)
            groups.setdefault(key, []).append(
                {
                    "open": float(row.open),
                    "high": float(row.high),
                    "low": float(row.low),
                    "close": float(row.close),
                }
            )

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
            "reports": reports,
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

        summary = "\n".join(lines)
        self.stdout.write(summary)
        self.stdout.write(self.style.SUCCESS(f"\nwrote {out_path} ({len(reports)} reports)"))
        return f"{len(reports)} reports -> {out_path}"
