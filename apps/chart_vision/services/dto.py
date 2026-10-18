"""Immutable data-transfer objects for the chart-vision service layer.

The services depend on these DTOs rather than on Pillow or the ORM, which keeps
validation, preprocessing and provider logic unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class ImageInfo:
    """Decoded image properties gathered during validation."""

    width: int
    height: int
    image_format: str
    mode: str
    size_bytes: int
    sha256: str


@dataclass(slots=True)
class ValidationResult:
    """Outcome of image validation.

    ``valid`` is the hard gate used for upload acceptance; ``errors`` list the
    rejection reasons and ``warnings`` list non-fatal observations (e.g. low
    pixel dimensions).
    """

    valid: bool
    info: ImageInfo | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def error_code(self) -> str:
        return self.errors[0] if self.errors else ""


@dataclass(slots=True, frozen=True)
class PreprocessedImage:
    """Bytes handed to the vision provider plus their properties."""

    data: bytes
    width: int
    height: int
    mime_type: str
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class ProviderUsage:
    """Token accounting reported by the provider (zeros when unavailable)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(slots=True, frozen=True)
class ProviderResult:
    """Raw provider response before schema validation."""

    raw_text: str
    provider: str
    model: str
    usage: ProviderUsage
    latency_ms: int


@dataclass(slots=True, frozen=True)
class NormalizedAnalysis:
    """Normalised, schema-validated structured output.

    ``payload`` is the complete result stored once on the analysis. The derived
    collections are compact projections persisted as related rows.
    """

    payload: dict[str, Any]
    chart_metadata: dict[str, Any]
    candles: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    patterns: list[dict[str, Any]]
    price_zones: list[dict[str, Any]]
    warnings: list[str]
    missing_information: list[str]
    observation_confidence: float | None
    status: str


__all__ = [
    "ImageInfo",
    "NormalizedAnalysis",
    "PreprocessedImage",
    "ProviderResult",
    "ProviderUsage",
    "ValidationResult",
]
