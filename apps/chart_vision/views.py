"""Chart-vision API views.

All endpoints require authentication and are ownership-scoped. Screenshot bytes
are streamed only through :class:`ScreenshotImageAPIView` after a permission
check; no public media URL is ever exposed. Analysis runs off the request cycle
via Celery, and duplicate requests are deduplicated by the analysis idempotency
key.
"""

from __future__ import annotations

from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.api.pagination import StandardResultsSetPagination
from apps.chart_vision import serializers
from apps.chart_vision.constants import AnalysisStatus, UploadStatus
from apps.chart_vision.models import ChartScreenshot, ScreenshotAnalysis
from apps.chart_vision.permissions import resolve_analysis, resolve_screenshot
from apps.chart_vision.services.exceptions import ImageValidationError
from apps.chart_vision.services.screenshot_analyzer import get_or_create_analysis
from apps.chart_vision.services.upload import create_screenshot_from_upload

_COMPLETED_STATES = {
    AnalysisStatus.COMPLETED,
    AnalysisStatus.PARTIAL,
    AnalysisStatus.INSUFFICIENT,
}

_TRUE_VALUES = {"1", "true", "yes", "on"}


class VisionReadMixin:
    """Authenticated, throttled read access."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "vision_read"


def _enqueue_analysis(analysis: ScreenshotAnalysis) -> None:
    from apps.chart_vision.tasks import analyze_screenshot_task

    analyze_screenshot_task.delay(analysis.pk)


def _launch_analysis(screenshot: ChartScreenshot) -> tuple[ScreenshotAnalysis, int, str]:
    """Create-or-reuse the analysis row and enqueue it exactly once.

    Returns ``(analysis, http_status, detail)``. A fresh analysis is enqueued; a
    queued/running analysis is returned unchanged (no duplicate job); a completed
    analysis is returned without re-running; a failed analysis is reset and
    re-enqueued on the same row.
    """
    analysis, created = get_or_create_analysis(screenshot)
    if created:
        _enqueue_analysis(analysis)
        return analysis, status.HTTP_202_ACCEPTED, "Analysis queued."
    if analysis.status in _COMPLETED_STATES:
        return (
            analysis,
            status.HTTP_200_OK,
            "This screenshot has already been analysed.",
        )
    if analysis.is_in_flight:
        return (
            analysis,
            status.HTTP_202_ACCEPTED,
            "An analysis for this screenshot is already queued.",
        )
    # A previous attempt failed: reuse the same row (no duplicate job).
    analysis.status = AnalysisStatus.QUEUED
    analysis.error_code = ""
    analysis.error_message = ""
    analysis.save(update_fields=["status", "error_code", "error_message", "updated_at"])
    _enqueue_analysis(analysis)
    return analysis, status.HTTP_202_ACCEPTED, "Analysis re-queued."


class ScreenshotUploadAPIView(APIView):
    """``POST`` a chart screenshot (validated, stored privately).

    ``GET`` lists the caller's screenshots.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "vision_upload"
    serializer_class = serializers.ScreenshotUploadSerializer

    def get(self, request) -> Response:
        queryset = ChartScreenshot.objects.filter(owner=request.user).order_by("-created_at")
        if request.user.is_superuser:
            queryset = ChartScreenshot.objects.all().order_by("-created_at")
        return Response(
            {
                "count": queryset.count(),
                "results": serializers.ChartScreenshotSerializer(queryset[:100], many=True).data,
            }
        )

    def post(self, request) -> Response:
        body = serializers.ScreenshotUploadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        uploaded = body.validated_data["image"]

        try:
            screenshot = create_screenshot_from_upload(request.user, uploaded)
        except ImageValidationError as exc:
            raise ValidationError({"detail": str(exc), "error_code": exc.code}) from exc

        analyze_requested = str(request.query_params.get("analyze", "")).lower() in _TRUE_VALUES
        response_payload = {
            "screenshot": serializers.ChartScreenshotSerializer(screenshot).data,
        }
        if analyze_requested:
            analysis, _code, _detail = _launch_analysis(screenshot)
            response_payload["analysis_id"] = analysis.pk
        return Response(response_payload, status=status.HTTP_201_CREATED)


class ScreenshotDetailAPIView(VisionReadMixin, APIView):
    """``GET`` one screenshot's metadata (owner only)."""

    serializer_class = serializers.ChartScreenshotSerializer

    def get(self, request, pk: int) -> Response:
        screenshot = resolve_screenshot(request.user, pk)
        if screenshot is None:
            raise NotFound("Screenshot not found.")
        return Response(serializers.ChartScreenshotSerializer(screenshot).data)


class ScreenshotImageAPIView(VisionReadMixin, APIView):
    """Stream the private screenshot bytes to the owner.

    This is the **only** way to read a screenshot; the bytes are never served
    from a public media URL.
    """

    serializer_class = serializers.ChartScreenshotSerializer

    def get(self, request, pk: int):
        screenshot = resolve_screenshot(request.user, pk)
        if screenshot is None or not screenshot.image:
            raise Http404("Screenshot not found.")
        try:
            handle = screenshot.image.storage.open(screenshot.image.name, "rb")
        except FileNotFoundError as exc:  # pragma: no cover - storage inconsistency
            raise Http404("Screenshot file is missing.") from exc
        response = FileResponse(handle, content_type=screenshot.content_type or "image/png")
        response["Content-Disposition"] = f'inline; filename="screenshot-{screenshot.pk}"'
        response["Cache-Control"] = "private, no-store"
        return response


class ScreenshotAnalyzeAPIView(APIView):
    """``POST`` to start (or deduplicate) analysis for a screenshot."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "vision_upload"
    serializer_class = serializers.ScreenshotAnalysisSummarySerializer

    def post(self, request, pk: int) -> Response:
        screenshot = resolve_screenshot(request.user, pk)
        if screenshot is None:
            raise NotFound("Screenshot not found.")
        if screenshot.status != UploadStatus.ACCEPTED:
            raise ValidationError({"detail": "Only accepted screenshots can be analysed."})
        analysis, code, detail = _launch_analysis(screenshot)
        return Response(
            {"analysis_id": analysis.pk, "status": analysis.status, "detail": detail},
            status=code,
        )


class AnalysisDetailAPIView(VisionReadMixin, APIView):
    """``GET`` a full analysis result (owner only)."""

    serializer_class = serializers.ScreenshotAnalysisSerializer

    def get(self, request, pk: int) -> Response:
        analysis = resolve_analysis(request.user, pk)
        if analysis is None:
            raise NotFound("Analysis not found.")
        return Response(serializers.ScreenshotAnalysisSerializer(analysis).data)


class AnalysisEventsAPIView(VisionReadMixin, APIView):
    """``GET`` the processing-event trail for an analysis (owner only)."""

    serializer_class = serializers.VisionProcessingEventSerializer

    def get(self, request, pk: int) -> Response:
        analysis = resolve_analysis(request.user, pk)
        if analysis is None:
            raise NotFound("Analysis not found.")
        events = analysis.events.order_by("occurred_at")
        return Response(
            {
                "count": events.count(),
                "results": serializers.VisionProcessingEventSerializer(events, many=True).data,
            }
        )


class AnalysisStatusAPIView(VisionReadMixin, APIView):
    """``GET`` a lightweight analysis status (for polling)."""

    serializer_class = serializers.VisionStatusSerializer

    def get(self, request, pk: int) -> Response:
        analysis = resolve_analysis(request.user, pk)
        if analysis is None:
            raise NotFound("Analysis not found.")
        return Response(serializers.VisionStatusSerializer(analysis).data)


class AnalysisHistoryAPIView(VisionReadMixin, APIView):
    """``GET`` the caller's analysis history (paginated)."""

    serializer_class = serializers.ScreenshotAnalysisSummarySerializer

    def get(self, request) -> Response:
        params = serializers.HistoryQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data

        queryset = ScreenshotAnalysis.objects.filter(owner=request.user)
        if request.user.is_superuser:
            queryset = ScreenshotAnalysis.objects.all()
        queryset = queryset.select_related("screenshot")
        if data.get("status"):
            queryset = queryset.filter(status=data["status"])
        queryset = queryset.order_by(data.get("ordering") or "-created_at")

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = serializers.ScreenshotAnalysisSummarySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


__all__ = [
    "AnalysisDetailAPIView",
    "AnalysisEventsAPIView",
    "AnalysisHistoryAPIView",
    "AnalysisStatusAPIView",
    "ScreenshotAnalyzeAPIView",
    "ScreenshotDetailAPIView",
    "ScreenshotImageAPIView",
    "ScreenshotUploadAPIView",
]
