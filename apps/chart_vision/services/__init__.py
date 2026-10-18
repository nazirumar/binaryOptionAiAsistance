"""Chart-vision service layer.

Services are decoupled from the ORM and the network (as far as is practical) so
they can be unit-tested in isolation with fakes. See
:mod:`apps.chart_vision.services.vision_provider` for the provider protocol and
:mod:`apps.chart_vision.services.screenshot_analyzer` for the orchestration.
"""

from __future__ import annotations

from apps.chart_vision.services.exceptions import (
    AnalysisInProgressError,
    ChartVisionError,
    CorruptedImageError,
    ImageTooLargeError,
    ImageValidationError,
    SchemaValidationError,
    UnsupportedImageFormatError,
    VisionProviderError,
    VisionProviderUnavailableError,
    VisionRateLimitError,
    VisionResponseError,
    VisionTimeoutError,
)

__all__ = [
    "AnalysisInProgressError",
    "ChartVisionError",
    "CorruptedImageError",
    "ImageTooLargeError",
    "ImageValidationError",
    "SchemaValidationError",
    "UnsupportedImageFormatError",
    "VisionProviderError",
    "VisionProviderUnavailableError",
    "VisionRateLimitError",
    "VisionResponseError",
    "VisionTimeoutError",
]
