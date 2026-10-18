"""Tests for secure image validation and preprocessing."""

from __future__ import annotations

from io import BytesIO

import pytest
from django.test import override_settings
from PIL import Image

from apps.chart_vision.services.exceptions import (
    CorruptedImageError,
    ImageTooLargeError,
    UnsupportedImageFormatError,
)
from apps.chart_vision.services.image_preprocessor import preprocess_image
from apps.chart_vision.services.image_validator import detect_format, validate_image
from tests.vision_fakes import jpeg_bytes, png_bytes, webp_bytes

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("data", "expected_format"),
    [
        (png_bytes(), "png"),
        (jpeg_bytes(), "jpeg"),
        (webp_bytes(), "webp"),
    ],
)
def test_accepts_supported_formats(data, expected_format):
    result = validate_image(data)
    assert result.valid is True
    assert result.info is not None
    assert result.info.image_format == expected_format
    assert result.info.width == 800
    assert result.info.height == 400
    assert len(result.info.sha256) == 64


def test_rejects_unsupported_format():
    with pytest.raises(UnsupportedImageFormatError):
        validate_image(b"GIF89a" + b"\x00" * 32)


def test_rejects_text_payload():
    with pytest.raises(UnsupportedImageFormatError):
        validate_image(b"this is not an image")


def test_rejects_empty_payload():
    with pytest.raises(CorruptedImageError):
        validate_image(b"")


def test_rejects_corrupted_png():
    data = png_bytes()[:32]  # signature kept, body truncated
    with pytest.raises(CorruptedImageError):
        validate_image(data)


@override_settings(VISION_MAX_UPLOAD_BYTES=64)
def test_rejects_oversized_file():
    with pytest.raises(ImageTooLargeError):
        validate_image(png_bytes())


@override_settings(VISION_MAX_WIDTH=100)
def test_rejects_excessive_width():
    with pytest.raises(ImageTooLargeError):
        validate_image(png_bytes())


@override_settings(VISION_MAX_PIXELS=1000)
def test_rejects_excessive_pixels():
    with pytest.raises(ImageTooLargeError):
        validate_image(png_bytes())


@override_settings(VISION_MIN_WIDTH=4000, VISION_MIN_HEIGHT=4000)
def test_low_resolution_is_a_warning_not_an_error():
    result = validate_image(png_bytes())
    assert result.valid is True
    assert any("Low resolution" in warning for warning in result.warnings)


def test_content_type_mismatch_is_a_warning():
    result = validate_image(png_bytes(), declared_content_type="image/jpeg")
    assert any("does not match" in warning for warning in result.warnings)


def test_detect_format_signatures():
    assert detect_format(png_bytes()) == "png"
    assert detect_format(jpeg_bytes()) == "jpeg"
    assert detect_format(webp_bytes()) == "webp"
    assert detect_format(b"nope") is None


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------
def test_preprocess_produces_bounded_png():
    result = preprocess_image(png_bytes(width=800, height=400))
    assert result.mime_type == "image/png"
    with Image.open(BytesIO(result.data)) as image:
        assert image.format == "PNG"
    assert result.width <= 2000 and result.height <= 2000


@override_settings(VISION_PREPROCESS_MAX_DIMENSION=200)
def test_preprocess_downscales_oversized_images():
    result = preprocess_image(png_bytes(width=800, height=400))
    assert max(result.width, result.height) == 200
    assert any("Downscaled" in note for note in result.notes)


def test_preprocess_flattens_transparency():
    from PIL import Image as PILImage

    buffer = BytesIO()
    PILImage.new("RGBA", (300, 200), (0, 0, 0, 0)).save(buffer, format="PNG")
    result = preprocess_image(buffer.getvalue())
    assert any("transparency" in note.lower() for note in result.notes)


def test_preprocess_rejects_garbage():
    with pytest.raises(CorruptedImageError):
        preprocess_image(b"not an image at all")
