"""Domain exceptions for the chart-vision application.

Every failure mode has a distinct type so the API and Celery task can map it to a
stable ``error_code`` without inspecting message strings.
"""

from __future__ import annotations


class ChartVisionError(Exception):
    """Base class for all chart-vision errors."""

    #: Stable, machine-readable code persisted on the analysis/event.
    code = "chart_vision_error"


class ImageValidationError(ChartVisionError):
    """An uploaded file failed validation and must be rejected."""

    code = "image_invalid"


class UnsupportedImageFormatError(ImageValidationError):
    """The file is not one of the supported image formats."""

    code = "image_format_unsupported"


class ImageTooLargeError(ImageValidationError):
    """The file exceeds a configured size/dimension/pixel bound."""

    code = "image_too_large"


class CorruptedImageError(ImageValidationError):
    """The bytes could not be safely decoded as an image."""

    code = "image_corrupted"


class VisionProviderError(ChartVisionError):
    """Base class for vision-provider failures (never yields a result)."""

    code = "provider_error"


class VisionProviderUnavailableError(VisionProviderError):
    """The provider is not configured, unreachable or unavailable."""

    code = "provider_unavailable"

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class VisionRateLimitError(VisionProviderError):
    """The provider rejected the request due to rate limiting."""

    code = "provider_rate_limited"

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class VisionTimeoutError(VisionProviderError):
    """The provider did not respond within the configured timeout."""

    code = "provider_timeout"


class VisionResponseError(VisionProviderError):
    """The provider responded, but not with usable structured JSON."""

    code = "provider_response_invalid"


class SchemaValidationError(ChartVisionError):
    """The structured output did not satisfy the versioned schema."""

    code = "schema_invalid"

    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class AnalysisInProgressError(ChartVisionError):
    """A duplicate analysis was requested while one is already queued/running."""

    code = "analysis_in_progress"


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
