"""Dashboard views."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

#: Roadmap surfaced on the dashboard; kept in one place for easy updating.
PHASES = [
    {"number": 1, "name": "Foundation", "status": "complete"},
    {"number": 2, "name": "MT5 integration", "status": "complete"},
    {"number": 3, "name": "Screenshot vision", "status": "complete"},
    {"number": 4, "name": "Data synchronization", "status": "complete"},
    {"number": 5, "name": "Price-action knowledge engine", "status": "complete"},
    {"number": 6, "name": "Strategy evaluation", "status": "complete"},
    {"number": 7, "name": "Backtesting & probability calibration", "status": "complete"},
    {"number": 8, "name": "AI assistant", "status": "complete"},
    {"number": 9, "name": "Dashboard & analytics", "status": "complete"},
    {"number": 10, "name": "Security, integration testing & deployment", "status": "planned"},
]


@login_required
@require_GET
def index(request: HttpRequest) -> HttpResponse:
    """Main dashboard shell."""
    from apps.dashboard.services.overview_service import OverviewService

    return render(
        request,
        "dashboard/index.html",
        {"phases": PHASES, "overview": OverviewService(request.user).build()},
    )


@login_required
@require_GET
def status_fragment(request: HttpRequest) -> HttpResponse:
    """HTMX fragment: system status card, polled periodically."""
    from apps.market_data.dashboard import derived_connection_state

    return render(
        request,
        "dashboard/partials/status.html",
        {"mt5_state": derived_connection_state()},
    )


@login_required
@require_GET
def mt5(request: HttpRequest) -> HttpResponse:
    """MT5 market-data connection dashboard."""
    from apps.market_data.dashboard import dashboard_context
    from apps.market_data.permissions import accessible_profiles

    profile = accessible_profiles(request.user).order_by("-is_default", "name").first()
    return render(request, "dashboard/mt5.html", dashboard_context(profile))


# ---------------------------------------------------------------------------
# Chart vision (Phase 3)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def vision(request: HttpRequest) -> HttpResponse:
    """Screenshot upload + analysis history."""
    from apps.chart_vision.dashboard import overview_context

    return render(request, "dashboard/vision.html", overview_context(request.user))


@login_required
@require_POST
def vision_upload(request: HttpRequest) -> HttpResponse:
    """Handle a dashboard screenshot upload and enqueue its analysis."""
    from apps.chart_vision.services.exceptions import ImageValidationError
    from apps.chart_vision.services.screenshot_analyzer import (
        get_or_create_analysis,
        record_event,
    )
    from apps.chart_vision.services.upload import create_screenshot_from_upload

    uploaded = request.FILES.get("image")
    if uploaded is None:
        messages.error(request, "Please choose an image file to upload.")
        return redirect("dashboard:vision")
    try:
        screenshot = create_screenshot_from_upload(request.user, uploaded)
    except ImageValidationError as exc:
        messages.error(request, f"Upload rejected: {exc}")
        return redirect("dashboard:vision")

    from apps.chart_vision.constants import EventKind

    analysis, _ = get_or_create_analysis(screenshot)
    record_event(
        analysis=analysis,
        kind=EventKind.QUEUE,
        message="Analysis enqueued from the dashboard.",
    )
    from apps.chart_vision.tasks import analyze_screenshot_task

    analyze_screenshot_task.delay(analysis.pk)
    messages.success(request, "Screenshot uploaded. Analysis queued.")
    return redirect("dashboard:vision-detail", pk=screenshot.pk)


@login_required
@require_GET
def vision_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Per-screenshot analysis detail page."""
    from apps.chart_vision.dashboard import screenshot_detail_context
    from apps.chart_vision.permissions import resolve_screenshot

    screenshot = resolve_screenshot(request.user, pk)
    if screenshot is None:
        raise Http404("Screenshot not found.")
    return render(
        request, "dashboard/vision_detail.html", screenshot_detail_context(request.user, screenshot)
    )


@login_required
@require_POST
def vision_analyze(request: HttpRequest, pk: int) -> HttpResponse:
    """(Re-)start analysis for a screenshot from the dashboard."""
    from apps.chart_vision.constants import AnalysisStatus
    from apps.chart_vision.permissions import resolve_screenshot
    from apps.chart_vision.services.screenshot_analyzer import get_or_create_analysis

    screenshot = resolve_screenshot(request.user, pk)
    if screenshot is None:
        raise Http404("Screenshot not found.")
    analysis, _ = get_or_create_analysis(screenshot)
    if analysis.is_terminal and analysis.status == AnalysisStatus.FAILED:
        analysis.status = AnalysisStatus.QUEUED
        analysis.save(update_fields=["status", "updated_at"])
    if analysis.is_in_flight:
        from apps.chart_vision.tasks import analyze_screenshot_task

        analyze_screenshot_task.delay(analysis.pk)
    messages.success(request, "Analysis queued.")
    return redirect("dashboard:vision-detail", pk=screenshot.pk)


@login_required
@require_GET
def vision_status(request: HttpRequest, pk: int) -> HttpResponse:
    """HTMX fragment: analysis status + results for polling."""
    from apps.chart_vision.dashboard import screenshot_detail_context
    from apps.chart_vision.permissions import resolve_screenshot

    screenshot = resolve_screenshot(request.user, pk)
    if screenshot is None:
        raise Http404("Screenshot not found.")
    context = screenshot_detail_context(request.user, screenshot)
    return render(request, "dashboard/partials/vision_status.html", context)


# ---------------------------------------------------------------------------
# Market synchronization (Phase 4)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def sync(request: HttpRequest) -> HttpResponse:
    """Synchronization history + a picker to verify an existing analysis."""
    from apps.market_sync.dashboard import overview_context

    return render(request, "dashboard/sync.html", overview_context(request.user))


@login_required
@require_GET
def sync_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Per-session synchronization detail page."""
    from apps.market_sync.dashboard import session_detail_context
    from apps.market_sync.permissions import resolve_session

    session = resolve_session(request.user, pk)
    if session is None:
        raise Http404("Synchronization session not found.")
    return render(
        request, "dashboard/sync_detail.html", session_detail_context(request.user, session)
    )


@login_required
@require_POST
def sync_verify(request: HttpRequest) -> HttpResponse:
    """Run a verification for a chosen analysis and redirect to the result."""
    from apps.chart_vision.permissions import accessible_analyses
    from apps.market_sync.services.synchronization_service import SynchronizationService

    analysis_id = request.POST.get("analysis_id")
    if not analysis_id or not str(analysis_id).isdigit():
        messages.error(request, "Please choose an analysis to verify.")
        return redirect("dashboard:sync")

    analysis = accessible_analyses(request.user).filter(pk=int(analysis_id)).first()
    if analysis is None:
        messages.error(request, "That analysis could not be found.")
        return redirect("dashboard:sync")

    session = SynchronizationService().verify(analysis=analysis, owner=request.user)
    messages.success(request, f"Synchronization complete: {session.get_outcome_display()}.")
    return redirect("dashboard:sync-detail", pk=session.pk)
