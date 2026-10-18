"""Read-only context builders for the market-synchronization dashboard page."""

from __future__ import annotations

from typing import Any

from apps.chart_vision.constants import AnalysisStatus
from apps.chart_vision.models import ScreenshotAnalysis
from apps.market_sync.constants import SyncStatus
from apps.market_sync.models import MarketSyncSession
from apps.market_sync.services.mismatch_reporter import status_message

DISCLAIMER = (
    "Synchronization compares AI screenshot observations with stored MT5 data. "
    "Only \u201cVerified alignment\u201d counts as a successful dual-source verification; "
    "every other status is unverified. No trading signal is produced here."
)

_COMPLETED_STATES = (
    AnalysisStatus.COMPLETED,
    AnalysisStatus.PARTIAL,
    AnalysisStatus.INSUFFICIENT,
)


def history_for_user(user, *, limit: int = 12):
    queryset = MarketSyncSession.objects.select_related("screenshot", "reference_symbol").order_by(
        "-created_at"
    )
    if not user.is_superuser:
        queryset = queryset.filter(owner=user)
    return list(queryset[:limit])


def verifiable_analyses(user, *, limit: int = 50):
    queryset = (
        ScreenshotAnalysis.objects.select_related("screenshot")
        .filter(status__in=_COMPLETED_STATES)
        .order_by("-created_at")
    )
    if not user.is_superuser:
        queryset = queryset.filter(owner=user)
    return list(queryset[:limit])


def overview_context(user) -> dict[str, Any]:
    return {
        "disclaimer": DISCLAIMER,
        "sessions": history_for_user(user),
        "analyses": verifiable_analyses(user),
        "outcome_choices": SyncStatus.choices,
    }


def session_detail_context(user, session: MarketSyncSession) -> dict[str, Any]:
    """Everything the detail page needs for one session."""
    alignments = list(session.alignments.all().select_related("mt5_candle"))
    issues = list(session.issues.all())
    audit_logs = list(session.audit_logs.all())
    feed = getattr(session, "feed_assessment", None)

    screenshot = session.screenshot
    analysis = session.analysis

    return {
        "disclaimer": DISCLAIMER,
        "session": session,
        "status_message": status_message(session.outcome),
        "is_verified": session.is_verified,
        "screenshot": screenshot,
        "analysis": analysis,
        "chart_metadata": analysis.chart_metadata if analysis else {},
        "feed": feed,
        "alignments": alignments,
        "issues": issues,
        "audit_logs": audit_logs,
        "reasons": session.reasons,
        "metrics": session.metrics,
        "mt5_snapshot": session.mt5_snapshot,
        "show_verified_badge": session.outcome == SyncStatus.VERIFIED_ALIGNMENT,
    }


__all__ = [
    "DISCLAIMER",
    "history_for_user",
    "overview_context",
    "session_detail_context",
    "verifiable_analyses",
]
