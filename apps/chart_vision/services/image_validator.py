"""Secure validation of uploaded chart screenshots.

Validation is defence-in-depth: size bounds, magic-byte signature checks, a
bounded safe decode with Pillow and a full pixel-limit guard. Anything that is
not a decodable PNG/JPEG/WebP is rejected; nothing is guessed from the filename
or the client-declared content type.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from io import BytesIO

from django.conf import settings
from PIL import Image, UnidentifiedImageError

from apps.chart_vision.constants import ImageFormat
from apps.chart_vision.services.dto import ImageInfo, ValidationResult
from apps.chart_vision.services.exceptions import (
    CorruptedImageError,
    ImageTooLargeError,
    UnsupportedImageFormatError,
)

#: Magic-byte signatures for the supported formats.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"

#: Mapping of a Pillow ``Image.format`` to our :class:`ImageFormat`.
_PIL_FORMAT_MAP = {
    "PNG": ImageFormat.PNG,
    "JPEG": ImageFormat.JPEG,
    "MPO": ImageFormat.JPEG,  # multi-picture JPEG; first frame decodes as JPEG
    "WEBP": ImageFormat.WEBP,
}

_CONTENT_TYPE_MAP = {
    ImageFormat.PNG: "image/png",
    ImageFormat.JPEG: "image/jpeg",
    ImageFormat.WEBP: "image/webp",
}


def detect_format(data: bytes) -> str | None:
    """Return the :class:`ImageFormat` implied by the file signature, or ``None``."""
    if data.startswith(_PNG_SIGNATURE):
        return ImageFormat.PNG
    if data.startswith(_JPEG_SIGNATURE):
        return ImageFormat.JPEG
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ImageFormat.WEBP
    return None


def content_type_for(image_format: str) -> str:
    return _CONTENT_TYPE_MAP.get(image_format, "application/octet-stream")


def read_upload_bytes(file_obj, *, limit: int | None = None) -> bytes:
    """Read an uploaded file into memory, refusing anything past ``limit``.

    Reading with an explicit ceiling prevents a malicious client from exhausting
    memory before the size check runs.
    """
    ceiling = limit if limit is not None else int(settings.VISION_MAX_UPLOAD_BYTES)
    if hasattr(file_obj, "chunks"):
        buffer = bytearray()
        for chunk in file_obj.chunks():
            buffer.extend(chunk)
            if len(buffer) > ceiling:
                raise ImageTooLargeError(f"Uploaded file exceeds the {ceiling} byte limit.")
        return bytes(buffer)
    data = file_obj.read() if hasattr(file_obj, "read") else bytes(file_obj)
    if len(data) > ceiling:
        raise ImageTooLargeError(f"Uploaded file exceeds the {ceiling} byte limit.")
    return data


@contextmanager
def _decompression_guard(max_pixels: int):
    """Temporarily tighten Pillow's decompression-bomb threshold."""
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        yield
    finally:
        Image.MAX_IMAGE_PIXELS = previous


def validate_image(data: bytes, *, declared_content_type: str = "") -> ValidationResult:
    """Validate raw image bytes and return a :class:`ValidationResult`.

    Raises a specific :class:`~apps.chart_vision.services.exceptions.ImageValidationError`
    for hard failures so callers can record a precise ``error_code``.
    """
    errors: list[str] = []
    warnings: list[str] = []

    size_bytes = len(data)
    if size_bytes == 0:
        raise CorruptedImageError("The uploaded file is empty.")

    max_bytes = int(settings.VISION_MAX_UPLOAD_BYTES)
    if size_bytes > max_bytes:
        raise ImageTooLargeError(f"File is {size_bytes} bytes; the limit is {max_bytes} bytes.")

    signature_format = detect_format(data)
    if signature_format is None:
        raise UnsupportedImageFormatError(
            "Only PNG, JPEG and WebP images are accepted (signature mismatch)."
        )

    max_pixels = int(settings.VISION_MAX_PIXELS)
    try:
        with _decompression_guard(max_pixels):
            with Image.open(BytesIO(data)) as probe:
                width, height = probe.size
                mode = probe.mode
                pil_format = probe.format
                probe.verify()  # cheap structural check (may raise)
            # ``verify()`` leaves the file unusable; reopen and fully decode.
            with Image.open(BytesIO(data)) as decoded:
                decoded.load()
    except Image.DecompressionBombError as exc:  # pragma: no cover - Pillow guard
        raise ImageTooLargeError(
            f"Image exceeds the {max_pixels} pixel decompression limit."
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise CorruptedImageError(f"Image could not be decoded: {exc}") from exc

    if width <= 0 or height <= 0:
        raise CorruptedImageError("Image reports zero dimensions.")

    if width * height > max_pixels:
        raise ImageTooLargeError(f"Image has {width * height} pixels; limit {max_pixels}.")

    max_width = int(settings.VISION_MAX_WIDTH)
    max_height = int(settings.VISION_MAX_HEIGHT)
    if width > max_width or height > max_height:
        raise ImageTooLargeError(
            f"Image is {width}x{height}; the maximum is {max_width}x{max_height}."
        )

    min_width = int(settings.VISION_MIN_WIDTH)
    min_height = int(settings.VISION_MIN_HEIGHT)
    if width < min_width or height < min_height:
        warnings.append(f"Low resolution ({width}x{height}); analysis confidence may be reduced.")

    resolved_format = _PIL_FORMAT_MAP.get(pil_format or "")
    if resolved_format is None:
        raise UnsupportedImageFormatError(f"Decoded image format {pil_format!r} is not supported.")
    if resolved_format != signature_format:
        warnings.append(
            f"Declared signature ({signature_format}) differs from decoded format "
            f"({resolved_format}); using the decoded format."
        )

    expected_content_type = content_type_for(resolved_format)
    if declared_content_type and declared_content_type != expected_content_type:
        warnings.append(
            f"Client content type {declared_content_type!r} does not match the "
            f"detected type {expected_content_type!r}."
        )

    sha256 = hashlib.sha256(data).hexdigest()
    info = ImageInfo(
        width=width,
        height=height,
        image_format=resolved_format,
        mode=mode,
        size_bytes=size_bytes,
        sha256=sha256,
    )
    return ValidationResult(valid=not errors, info=info, errors=errors, warnings=warnings)


__all__ = [
    "content_type_for",
    "detect_format",
    "read_upload_bytes",
    "validate_image",
]
