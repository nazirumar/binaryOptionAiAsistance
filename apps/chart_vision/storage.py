"""Private storage for uploaded chart screenshots.

Screenshots may contain account details, so they are **never** served from
``MEDIA_URL``. A dedicated :class:`~django.core.files.storage.FileSystemStorage`
rooted at ``VISION_SCREENSHOT_ROOT`` keeps the bytes outside the publicly served
media tree, and :meth:`url` refuses to produce a public URL. Files are streamed
back to authorised owners through :func:`apps.chart_vision.views.screenshot_image`.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils import timezone


class PrivateScreenshotStorage(FileSystemStorage):
    """Filesystem storage that hides files from public (``MEDIA_URL``) access."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("location", str(settings.VISION_SCREENSHOT_ROOT))
        kwargs.setdefault("base_url", None)
        super().__init__(*args, **kwargs)

    def url(self, name: str) -> str:  # pragma: no cover - defensive guard
        raise ValueError(
            "Screenshots are private; serve them through the authenticated "
            "chart-vision image endpoint, never a public URL."
        )


#: Single shared storage instance used by :attr:`ChartScreenshot.image`.
private_screenshot_storage = PrivateScreenshotStorage()


def screenshot_upload_path(instance, filename: str) -> str:
    """Build a collision-free, non-guessable storage path.

    Layout: ``<owner_id|shared>/<YYYY>/<MM>/<uuid4>.<ext>``. The original
    filename is never used (only its validated extension), preventing path
    traversal and information disclosure.
    """
    owner = getattr(instance, "owner_id", None) or "shared"
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    extension = suffix if suffix.isalnum() and len(suffix) <= 5 else "png"
    now = timezone.now()
    return f"{owner}/{now:%Y/%m}/{uuid.uuid4().hex}.{extension}"


__all__ = ["PrivateScreenshotStorage", "private_screenshot_storage", "screenshot_upload_path"]
