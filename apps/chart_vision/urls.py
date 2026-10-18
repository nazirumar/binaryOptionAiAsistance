"""Chart-vision API URLs (mounted under ``/api/vision/``)."""

from __future__ import annotations

from django.urls import path

from apps.chart_vision import views

app_name = "chart_vision"

urlpatterns = [
    path("screenshots/", views.ScreenshotUploadAPIView.as_view(), name="screenshots"),
    path(
        "screenshots/<int:pk>/",
        views.ScreenshotDetailAPIView.as_view(),
        name="screenshot-detail",
    ),
    path(
        "screenshots/<int:pk>/image/",
        views.ScreenshotImageAPIView.as_view(),
        name="screenshot-image",
    ),
    path(
        "screenshots/<int:pk>/analyze/",
        views.ScreenshotAnalyzeAPIView.as_view(),
        name="screenshot-analyze",
    ),
    path("analyses/<int:pk>/", views.AnalysisDetailAPIView.as_view(), name="analysis-detail"),
    path(
        "analyses/<int:pk>/events/",
        views.AnalysisEventsAPIView.as_view(),
        name="analysis-events",
    ),
    path("history/", views.AnalysisHistoryAPIView.as_view(), name="history"),
    path("status/<int:pk>/", views.AnalysisStatusAPIView.as_view(), name="status"),
]
