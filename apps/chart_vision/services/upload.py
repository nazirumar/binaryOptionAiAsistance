"""Screenshot storage: validate an upload and persist it privately.

Shared by the REST API and the dashboard so both paths apply identical
validation, ownership and retention rules.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.chart_vision.constants import EventKind, UploadStatus
from apps.chart_vision.models import ChartScreenshot
from apps.chart_vision.services.events import record_event
from apps.chart_vision.services.image_validator import (
    content_type_for,
    read_upload_bytes,
    validate_image,
)


def create_screenshot_from_upload(owner, uploaded_file) -> ChartScreenshot:
    """Validate and store an uploaded screenshot in private storage.

    Raises :class:`~apps.chart_vision.services.exceptions.ImageValidationError`
    for invalid/corrupted/oversized files (the caller maps it to a response).
    """
    data = read_upload_bytes(uploaded_file)
    validation = validate_image(
        data, declared_content_type=getattr(uploaded_file, "content_type", "") or ""
    )
    info = validation.info
    retention_days = int(getattr(settings, "VISION_SCREENSHOT_RETENTION_DAYS", 30))
    original_name = (getattr(uploaded_file, "name", "") or "upload.png")[:255]

    screenshot = ChartScreenshot(
        owner=owner,
        original_filename=original_name,
        content_type=content_type_for(info.image_format),
        image_format=info.image_format,
        size_bytes=info.size_bytes,
        width=info.width,
        height=info.height,
        sha256=info.sha256,
        status=UploadStatus.ACCEPTED,
        metadata={"validation_warnings": validation.warnings},
        expires_at=timezone.now() + timedelta(days=retention_days),
    )
    screenshot.image.save(original_name, ContentFile(data), save=False)
    screenshot.save()
    record_event(
        screenshot=screenshot,
        kind=EventKind.UPLOAD,
        message="Screenshot uploaded and validated.",
        detail={
            "width": info.width,
            "height": info.height,
            "format": info.image_format,
            "size_bytes": info.size_bytes,
        },
    )
    return screenshot


__all__ = ["create_screenshot_from_upload"]
