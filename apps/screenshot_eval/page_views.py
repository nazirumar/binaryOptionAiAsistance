# screenshot_eval/page_views.py
"""Server-rendered Phase 14 pages: forward testing, review queue, case detail.

Owner-scoped and login-required, matching the existing dashboard pages. Every
page reads persisted records only and never mixes recognition and prediction
scopes.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.screenshot_eval.constants import DEFAULT_MIN_LABELS, DEFAULT_MIN_VERIFIED
from apps.screenshot_eval.models import (
    ForwardPaperPrediction,
    ReviewQueueItem,
    ScreenshotCase,
)

PAGE_SIZE = 25


def _owned_case(user, pk: int) -> ScreenshotCase:
    case = ScreenshotCase.objects.filter(pk=pk).select_related("screenshot").first()
    if case is None or (case.owner_id != user.pk and not user.is_staff):
        raise Http404("Screenshot case not found.")
    return case


@login_required
@require_GET
def forward_testing(request: HttpRequest) -> HttpResponse:
    """Checkpoint 6 - Forward Testing page (recognition and prediction scopes)."""
    from apps.screenshot_eval.services.forward import PREDICTION_DISCLAIMER
    from apps.screenshot_eval.services.metrics import ScreenshotMetricsService
    from apps.screenshot_eval.services.recognition import RECOGNITION_DISCLAIMER

    metrics = ScreenshotMetricsService().build()
    segments = {
        dim: ScreenshotMetricsService().by_segment(dim)["buckets"]
        for dim in ("strategy", "instrument", "timeframe", "market_type")
    }
    predictions = list(
        ForwardPaperPrediction.objects.filter(owner=request.user)
        .select_related("outcome", "case")
        .order_by("-decision_timestamp")[:100]
    )
    context = {
        "metrics": metrics,
        "segments": segments,
        "predictions": predictions,
        "recognition_disclaimer": RECOGNITION_DISCLAIMER,
        "prediction_disclaimer": PREDICTION_DISCLAIMER,
        "min_labels": DEFAULT_MIN_LABELS,
        "min_verified": DEFAULT_MIN_VERIFIED,
        "total_cases": ScreenshotCase.objects.filter(owner=request.user).count(),
        "labelled_cases": ScreenshotCase.objects.filter(
            owner=request.user, review_state__in=("confirmed", "corrected")
        ).count(),
        "review_open": ReviewQueueItem.objects.filter(state="open").count(),
    }
    return render(request, "dashboard/forward_testing.html", context)


@login_required
@require_GET
def review_queue(request: HttpRequest) -> HttpResponse:
    """Checkpoint 7 - error review queue."""

    state = (request.GET.get("state") or "open").strip()
    qs = ReviewQueueItem.objects.select_related("case", "recognition", "prediction")
    if state and state != "all":
        qs = qs.filter(state=state)
    counts = {
        s: ReviewQueueItem.objects.filter(state=s).count()
        for s in ("open", "in_review", "resolved", "dismissed")
    }
    paginator = Paginator(qs.order_by("-created_at"), PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    context = {
        "page_obj": page,
        "items": page,
        "state": state,
        "counts": counts,
        "kinds": ReviewQueueItem.Kind.CHOICES,
    }
    return render(request, "dashboard/review_queue.html", context)


@login_required
@require_POST
def review_queue_scan(request: HttpRequest) -> HttpResponse:
    """Raise new review items from stored records."""
    from apps.screenshot_eval.services.review import ReviewQueueService

    owner = None if request.user.is_staff else request.user
    result = ReviewQueueService().scan(owner=owner)
    messages.success(request, f"Raised {result.created} review item(s).")
    return redirect("dashboard:review-queue")


@login_required
@require_POST
def review_resolve(request: HttpRequest, pk: int) -> HttpResponse:
    """Resolve or dismiss an item, optionally recording a correction.

    The correction is stored on the queue item only - the original prediction
    and recognition records are never rewritten.
    """
    from apps.screenshot_eval.services.review import ReviewQueueService

    item = ReviewQueueItem.objects.filter(pk=pk).first()
    if item is None or (item.owner_id != request.user.pk and not request.user.is_staff):
        raise Http404("Review item not found.")
    correction_text = (request.POST.get("correction") or "").strip()
    correction = {"note": correction_text} if correction_text else None
    ReviewQueueService().resolve(
        item=item,
        reviewer=request.user,
        resolution_note=(request.POST.get("note") or "").strip(),
        correction=correction,
        dismiss=(request.POST.get("action") == "dismiss"),
    )
    messages.success(request, "Review item updated.")
    return redirect(request.META.get("HTTP_REFERER") or "dashboard:review-queue")


@login_required
@require_GET
def case_list(request: HttpRequest) -> HttpResponse:
    """Dataset cases (Checkpoint 1) with review state."""
    qs = ScreenshotCase.objects.filter(owner=request.user).select_related("screenshot")
    paginator = Paginator(qs.order_by("-created_at"), PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    context = {
        "page_obj": page,
        "cases": page,
        "total": ScreenshotCase.objects.filter(owner=request.user).count(),
        "labelled": ScreenshotCase.objects.filter(
            owner=request.user, review_state__in=("confirmed", "corrected")
        ).count(),
    }
    return render(request, "dashboard/screenshot_cases.html", context)


@login_required
@require_GET
def case_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """One case: recognitions, annotations and forward predictions."""
    case = _owned_case(request.user, pk)
    runs = case.recognition_runs.order_by("-created_at")[:10]
    recognitions = (
        case.recognition_runs.order_by("-created_at")
        .first()
    )
    recognition_rows = (
        recognitions.recognitions.all() if recognitions is not None else []
    )
    context = {
        "case": case,
        "runs": runs,
        "recognition_rows": recognition_rows,
        "annotations": case.annotations.all(),
        "predictions": case.forward_predictions.select_related("outcome").all(),
    }
    return render(request, "dashboard/screenshot_case_detail.html", context)
