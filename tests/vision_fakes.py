"""Fakes, fixtures and factories for chart-vision tests.

All tests are hermetic: images are generated in-memory with Pillow and the vision
provider is always a fake, so no network or credentials are required.
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.chart_vision.constants import SCHEMA_VERSION
from apps.chart_vision.models import ChartScreenshot
from apps.chart_vision.services.dto import ProviderResult, ProviderUsage
from apps.chart_vision.services.vision_provider import ProviderConfig, VisionProvider

SHARED_CONFIG = ProviderConfig(
    provider="mock",
    model="static-vision-1",
    api_key="",
    base_url="",
    timeout_seconds=1,
    max_retries=0,
    backoff_seconds=0.0,
    max_tokens=64,
    temperature=0.0,
)


# ---------------------------------------------------------------------------
# Image builders
# ---------------------------------------------------------------------------
def _draw(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height), (255, 255, 255))
    # A few coloured bars so the image is not uniform (decodes meaningfully).
    for index in range(6):
        x = 20 + index * 30
        color = (0, 160, 0) if index % 2 == 0 else (200, 0, 0)
        for y in range(20, min(height, 60)):
            image.putpixel((min(x, width - 1), y), color)
    return image


def image_bytes(fmt: str = "PNG", *, width: int = 800, height: int = 400) -> bytes:
    buffer = BytesIO()
    _draw(width, height).save(buffer, format=fmt)
    return buffer.getvalue()


def png_bytes(**kwargs: int) -> bytes:
    return image_bytes("PNG", **kwargs)


def jpeg_bytes(**kwargs: int) -> bytes:
    return image_bytes("JPEG", **kwargs)


def webp_bytes(**kwargs: int) -> bytes:
    return image_bytes("WEBP", **kwargs)


def uploaded_file(
    data: bytes | None = None, name: str = "chart.png", content_type: str = "image/png"
):
    return SimpleUploadedFile(
        name, data if data is not None else png_bytes(), content_type=content_type
    )


# ---------------------------------------------------------------------------
# Screenshot helpers
# ---------------------------------------------------------------------------
def make_screenshot(
    owner, *, data: bytes | None = None, name: str = "chart.png"
) -> ChartScreenshot:
    screenshot = ChartScreenshot.objects.create(
        owner=owner,
        original_filename=name,
        content_type="image/png",
        image_format="png",
        size_bytes=len(data or png_bytes()),
        width=800,
        height=400,
        sha256="0" * 64,
        status="accepted",
    )
    screenshot.image.save(name, ContentFile(data if data is not None else png_bytes()), save=True)
    return screenshot


# ---------------------------------------------------------------------------
# Provider fakes
# ---------------------------------------------------------------------------
class StaticVisionProvider(VisionProvider):
    """Returns a fixed payload (or raises a fixed error)."""

    name = "static"

    def __init__(
        self,
        *,
        payload: dict[str, Any] | None = None,
        raw_text: str | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__(SHARED_CONFIG)
        if raw_text is not None:
            self._raw = raw_text
        else:
            self._raw = json.dumps(payload if payload is not None else full_payload())
        self._error = error

    def analyze(self, *, image_bytes: bytes, mime_type: str, prompt: str) -> ProviderResult:
        if self._error is not None:
            raise self._error
        return ProviderResult(
            raw_text=self._raw,
            provider=self.name,
            model="static-vision-1",
            usage=ProviderUsage(prompt_tokens=11, completion_tokens=7, total_tokens=18),
            latency_ms=5,
        )


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------
def full_payload(**overrides: Any) -> dict[str, Any]:
    """A fully-populated, schema-valid payload (status: completed)."""
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "analysis_status": "completed",
        "screenshot_quality": {"rating": "high", "issues": [], "notes": ""},
        "chart_metadata": {
            "platform": "IQ Option",
            "instrument": "EURUSD",
            "otc_status": "regular",
            "timeframe": "M1",
            "screenshot_timestamp": "2026-01-05T12:00:00Z",
            "visible_price_labels": ["1.1000", "1.1050", "1.1100"],
            "candle_colors": {"bullish": "green", "bearish": "red"},
            "orientation": "standard",
            "volume_indicator_present": False,
            "technical_indicators": ["moving average"],
            "confidence": 0.8,
        },
        "candles": [
            {
                "index": 0,
                "position": "left",
                "classification": "bullish",
                "body_size": "medium",
                "upper_wick": "small",
                "lower_wick": "small",
                "high_px": 120,
                "low_px": 200,
                "body_top_px": 140,
                "body_bottom_px": 190,
                "appears_complete": True,
                "confidence": 0.7,
                "ambiguity": None,
            },
            {
                "index": 1,
                "position": "middle",
                "classification": "bearish",
                "body_size": "small",
                "upper_wick": "medium",
                "lower_wick": "small",
                "high_px": 130,
                "low_px": 210,
                "body_top_px": 160,
                "body_bottom_px": 205,
                "appears_complete": True,
                "confidence": 0.6,
                "ambiguity": None,
            },
            {
                "index": 2,
                "position": "right",
                "classification": "bullish",
                "body_size": "large",
                "upper_wick": "small",
                "lower_wick": "none",
                "high_px": 110,
                "low_px": 205,
                "body_top_px": 115,
                "body_bottom_px": 195,
                "appears_complete": True,
                "confidence": 0.5,
                "ambiguity": None,
            },
        ],
        "market_structure": {
            "trend": "uptrend",
            "higher_highs": True,
            "higher_lows": True,
            "lower_highs": False,
            "lower_lows": False,
            "swing_highs": [{"candle": 2, "confidence": 0.6, "confirmed": True}],
            "swing_lows": [{"candle": 1, "confidence": 0.4, "confirmed": False}],
            "breakouts": [],
            "failed_breakouts": [],
            "consolidation": False,
            "notes": "Higher highs and higher lows visible.",
            "confidence": 0.6,
        },
        "support_resistance": [
            {
                "zone_type": "resistance",
                "approx_location": "upper-third",
                "price_hint": "1.1100",
                "supporting_candles": [0, 2],
                "repeated_rejection": True,
                "broken": False,
                "flip": None,
                "confidence": 0.55,
                "description": "Two rejections near the upper band.",
            }
        ],
        "patterns": [
            {
                "name": "bullish engulfing",
                "category": "candlestick",
                "direction": "bullish",
                "candles": [1, 2],
                "confidence": 0.5,
                "confirmed": True,
                "description": "Second candle engulfs the first.",
            }
        ],
        "sequence_observations": [
            {
                "kind": "reference_sequence",
                "candles": [0, 1, 2],
                "confidence": 0.4,
                "notes": "Three-candle reference sequence.",
            }
        ],
        "market_cycle": {
            "observed": True,
            "phase": "motive",
            "description": "Impulsive move to the upside.",
            "confidence": 0.4,
        },
        "liquidity": [
            {
                "kind": "fair_value_gap",
                "candles": [0, 1],
                "confidence": 0.35,
                "notes": "Potential gap between candles 0 and 1.",
            }
        ],
        "volume": {
            "patterns": ["rising"],
            "indicator_present": False,
            "notes": "",
            "confidence": 0.3,
        },
        "missing_information": [],
        "warnings": [],
        "observation_confidence": {"overall": 0.62, "notes": "Reasonable visibility."},
    }
    payload.update(overrides)
    return payload


def unknown_metadata_payload() -> dict[str, Any]:
    """A payload whose instrument/timeframe/OTC cannot be read."""
    return full_payload(
        analysis_status="partial",
        chart_metadata={
            "platform": "UNKNOWN",
            "instrument": "UNKNOWN",
            "otc_status": "unknown",
            "timeframe": "UNKNOWN",
            "screenshot_timestamp": None,
            "visible_price_labels": [],
            "candle_colors": {"bullish": "UNKNOWN", "bearish": "UNKNOWN"},
            "orientation": "unknown",
            "volume_indicator_present": None,
            "technical_indicators": [],
            "confidence": 0.0,
        },
    )


def utcnow():
    return timezone.now()
