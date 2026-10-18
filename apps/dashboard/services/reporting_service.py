# apps/dashboard/services/reporting_service.py
"""Exports and reports (Phase 9, Step 14).

Every generated file is scoped to the requesting user, records the data source,
the date range and a generation timestamp, and states the report's limitations.
No other user's data is ever included.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

from django.http import HttpResponse
from django.utils import timezone

from apps.dashboard.services import analytics_service, overview_service
from apps.dashboard.services.pdf import Line, body, build_pdf, heading, spacer
from apps.strategy_engine.models import StrategyEvaluation
from apps.trading_journal.constants import PROVENANCE_LABELS
from apps.trading_journal.models import JournalTrade
from apps.trading_journal.services.journal_performance import JournalPerformance

#: Generic limitation text appended to every report.
GENERAL_LIMITATIONS = [
    "This report contains analysis and research output only; it does not place trades.",
    "Figures are derived solely from data recorded in this application.",
    "Absence of a metric means insufficient validated data, not a zero value.",
]

#: Leading characters that spreadsheet applications interpret as the start of
#: a formula (CSV / "formula injection"). A notes or instrument field
#: containing ``=HYPERLINK(...)`` or ``@SUM(...)`` would otherwise be executed
#: when the export is opened in Excel/LibreOffice.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):  # type: ignore[no-untyped-def]
    """Neutralise spreadsheet formula injection in a CSV cell.

    Only *string* cells are modified. Numeric types (``Decimal``, ``int``) are
    passed through untouched so a loss of ``-10.00`` stays a valid negative
    number instead of being rewritten as ``'-10.00``.
    """
    if not isinstance(value, str):
        return value
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def write_row(writer, row) -> None:  # type: ignore[no-untyped-def]
    """Write one CSV row with every string cell sanitised."""
    writer.writerow([safe_cell(cell) for cell in row])


@dataclass
class ReportMeta:
    """Metadata embedded into every report."""

    title: str
    owner: str
    generated_at: datetime
    source: str
    date_from: datetime | None = None
    date_to: datetime | None = None
    limitations: list[str] = field(default_factory=list)

    def as_rows(self) -> list[tuple[str, str]]:
        rows = [
            ("Report", self.title),
            ("Owner", self.owner),
            ("Generated at (UTC)", self.generated_at.strftime("%Y-%m-%d %H:%M:%S")),
            ("Data source", self.source),
            (
                "Date range",
                (
                    f"{self.date_from:%Y-%m-%d} to {self.date_to:%Y-%m-%d}"
                    if self.date_from and self.date_to
                    else "All recorded data"
                ),
            ),
        ]
        return rows


class ReportingService:
    """Generate CSV exports and PDF reports for a single user."""

    def __init__(self, user) -> None:  # type: ignore[no-untyped-def]
        self.user = user

    # -- Journal exports --------------------------------------------------
    def journal_csv(
        self,
        trade_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> HttpResponse:
        queryset = JournalTrade.objects.filter(owner=self.user)
        if trade_type:
            queryset = queryset.filter(trade_type=trade_type)
        if date_from:
            queryset = queryset.filter(entry_timestamp__gte=date_from)
        if date_to:
            queryset = queryset.filter(entry_timestamp__lte=date_to)
        queryset = queryset.order_by("-entry_timestamp")

        meta = ReportMeta(
            title="Trading journal export",
            owner=str(self.user),
            generated_at=timezone.now(),
            source="trading_journal.JournalTrade",
            date_from=date_from,
            date_to=date_to,
            limitations=[
                *list(GENERAL_LIMITATIONS),
                "Each row's trade_type states whether it is real, demo, backtested "
                "or hypothetical; these must not be combined.",
            ],
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for key, value in meta.as_rows():
            write_row(writer, [f"# {key}", value])
        writer.writerow([])
        write_row(
            writer,
            [
                "id",
                "trade_type",
                "provenance",
                "instrument",
                "market_type",
                "direction",
                "strategy_family",
                "entry_timestamp",
                "expiration_timestamp",
                "entry_quote",
                "settlement_quote",
                "stake",
                "payout_percent",
                "result",
                "profit_loss",
                "notes",
                "mistakes",
                "lessons_learned",
            ],
        )
        for trade in queryset:
            write_row(
                writer,
                [
                    trade.pk,
                    trade.trade_type,
                    PROVENANCE_LABELS.get(trade.trade_type, trade.trade_type),
                    trade.instrument,
                    trade.market_type,
                    trade.direction,
                    trade.strategy_family,
                    trade.entry_timestamp.isoformat() if trade.entry_timestamp else "",
                    trade.expiration_timestamp.isoformat() if trade.expiration_timestamp else "",
                    trade.entry_quote,
                    trade.settlement_quote,
                    trade.stake,
                    trade.payout_percent,
                    trade.result,
                    trade.profit_loss,
                    trade.notes,
                    trade.mistakes,
                    trade.lessons_learned,
                ],
            )
        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="journal_export.csv"'
        return response

    # -- Analysis exports -------------------------------------------------
    def analyses_csv(self) -> HttpResponse:
        evaluations = StrategyEvaluation.objects.filter(owner=self.user).order_by("-created_at")
        meta = ReportMeta(
            title="Strategy evaluation export",
            owner=str(self.user),
            generated_at=timezone.now(),
            source="strategy_engine.StrategyEvaluation",
            limitations=list(GENERAL_LIMITATIONS),
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for key, value in meta.as_rows():
            write_row(writer, [f"# {key}", value])
        writer.writerow([])
        write_row(
            writer,
            [
                "id",
                "instrument",
                "timeframe",
                "market_type",
                "direction",
                "strategy_family",
                "status",
                "market_context",
                "confluence_score",
                "probability_status",
                "primary_reason_code",
                "created_at",
            ],
        )
        for evaluation in evaluations:
            write_row(
                writer,
                [
                    evaluation.pk,
                    evaluation.instrument,
                    evaluation.timeframe,
                    evaluation.market_type,
                    evaluation.direction,
                    evaluation.strategy_family,
                    evaluation.status,
                    evaluation.market_context,
                    evaluation.confluence_score,
                    evaluation.probability_status,
                    evaluation.primary_reason_code,
                    evaluation.created_at.isoformat(),
                ],
            )
        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="strategy_evaluations.csv"'
        return response

    # -- PDF report -------------------------------------------------------
    def performance_pdf(self) -> HttpResponse:
        """A performance summary PDF, segmented by provenance."""
        meta = ReportMeta(
            title="Performance summary",
            owner=str(self.user),
            generated_at=timezone.now(),
            source="trading_journal + strategy_engine",
            limitations=[
                *list(GENERAL_LIMITATIONS),
                "Performance is segmented by provenance and never combined across "
                "real, demo, backtest and hypothetical records.",
            ],
        )
        lines: list[Line] = [heading(meta.title), spacer()]
        for key, value in meta.as_rows():
            lines.append(body(f"{key}: {value}"))
        lines.append(spacer())

        overview = overview_service.OverviewService(self.user).build()
        lines.append(heading("Overview"))
        counts = overview["counts"]
        lines.append(body(f"Screenshot analyses: {counts['screenshot_analyses']}"))
        lines.append(body(f"Strategy evaluations: {counts['strategy_evaluations']}"))
        decisions = overview["decisions"]
        lines.append(
            body(
                f"Decisions - UP: {decisions['up']}, DOWN: {decisions['down']}, "
                f"NO_TRADE: {decisions['no_trade']}"
            )
        )
        lines.append(spacer())

        perf = overview["performance"]
        lines.append(heading("Validated performance"))
        if perf["has_valid_outcomes"]:
            lines.append(body(f"Settled real trades: {perf['settled_real_trades']}"))
            lines.append(body(f"Net profit/loss: {perf['net_profit_loss']}"))
            win_rate = perf.get("win_rate")
            lines.append(body(f"Win rate: {win_rate}" if win_rate is not None else "Win rate: n/a"))
        else:
            lines.append(body(perf["message"]))
        lines.append(spacer())

        lines.append(heading("Journal performance by provenance"))
        performance = JournalPerformance(JournalTrade.objects.filter(owner=self.user))
        for segment, summary in performance.segmented_summary().items():
            lines.append(
                body(
                    f"[{segment}] recorded={summary.total_recorded} "
                    f"settled={summary.settled} wins={summary.wins} "
                    f"losses={summary.losses} ties={summary.ties} "
                    f"net={summary.net_profit_loss} drawdown={summary.max_drawdown}"
                )
            )
        lines.append(spacer())

        analytics = analytics_service.StrategyAnalytics(self.user).build()
        lines.append(heading("Strategy analytics"))
        totals = analytics["totals"]
        lines.append(
            body(
                f"Evaluations: {totals['total_evaluations']} "
                f"accepted: {totals['accepted']} rejected: {totals['rejected']}"
            )
        )
        for row in analytics["by_family"]:
            lines.append(body(f"  {row['label']}: {row['total']}"))

        lines.append(spacer())
        lines.append(heading("Limitations"))
        for limitation in meta.limitations:
            lines.append(body(f"- {limitation}"))

        pdf_bytes = build_pdf(lines, title=meta.title)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="performance_summary.pdf"'
        return response


__all__ = ["GENERAL_LIMITATIONS", "ReportMeta", "ReportingService"]
