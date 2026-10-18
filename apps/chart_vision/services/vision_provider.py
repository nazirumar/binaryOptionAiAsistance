"""Configurable vision-LLM provider abstraction.

Three providers are supported, selected by ``VISION_LLM_PROVIDER``:

``mock``
    Deterministic, offline development stub. It returns a clearly-labelled
    illustrative payload so the pipeline can be exercised without credentials.
``openai`` / ``custom``
    OpenAI-compatible ``/chat/completions`` endpoints that accept image input as
    a base64 data URI. ``custom`` is the same protocol with an explicit base URL.

Credentials are read from settings/environment only and are never stored or
logged. A provider failure raises a typed exception; it never returns a
fabricated analysis.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from apps.chart_vision.constants import PROMPT_VERSION, SCHEMA_VERSION, ProviderName
from apps.chart_vision.services.dto import ProviderResult, ProviderUsage
from apps.chart_vision.services.exceptions import (
    VisionProviderUnavailableError,
    VisionRateLimitError,
    VisionResponseError,
    VisionTimeoutError,
)


@dataclass(slots=True, frozen=True)
class ProviderConfig:
    """Resolved provider configuration (never persisted)."""

    provider: str
    model: str
    api_key: str
    base_url: str
    timeout_seconds: int
    max_retries: int
    backoff_seconds: float
    max_tokens: int
    temperature: float

    @classmethod
    def from_settings(cls) -> ProviderConfig:
        return cls(
            provider=str(getattr(settings, "VISION_LLM_PROVIDER", "mock") or "mock"),
            model=str(getattr(settings, "VISION_LLM_MODEL", "") or ""),
            api_key=str(getattr(settings, "VISION_LLM_API_KEY", "") or ""),
            base_url=str(getattr(settings, "VISION_LLM_BASE_URL", "") or ""),
            timeout_seconds=int(getattr(settings, "VISION_LLM_TIMEOUT_SECONDS", 60)),
            max_retries=int(getattr(settings, "VISION_LLM_MAX_RETRIES", 2)),
            backoff_seconds=float(getattr(settings, "VISION_LLM_BACKOFF_SECONDS", 1.5)),
            max_tokens=int(getattr(settings, "VISION_LLM_MAX_TOKENS", 2048)),
            temperature=float(getattr(settings, "VISION_LLM_TEMPERATURE", 0.0)),
        )


class VisionProvider(ABC):
    """Interface every vision provider implements.

    ``analyze`` performs a **single** attempt; bounded retries are handled by the
    analyser, which understands rate-limit/backoff policy.
    """

    name: str = "base"

    def __init__(self, config: ProviderConfig | None = None) -> None:
        self.config = config or ProviderConfig.from_settings()

    @property
    def model(self) -> str:
        return self.config.model

    @abstractmethod
    def analyze(self, *, image_bytes: bytes, mime_type: str, prompt: str) -> ProviderResult:
        """Send the image + prompt to the model and return the raw response."""


class MockVisionProvider(VisionProvider):
    """Offline, deterministic provider for development and tests."""

    name = ProviderName.MOCK

    def __init__(self, config: ProviderConfig | None = None, *, payload: dict | None = None):
        super().__init__(config)
        self._payload = payload

    def analyze(self, *, image_bytes: bytes, mime_type: str, prompt: str) -> ProviderResult:
        started = time.monotonic()
        payload = self._payload if self._payload is not None else build_mock_payload()
        raw_text = json.dumps(payload)
        latency_ms = int((time.monotonic() - started) * 1000)
        return ProviderResult(
            raw_text=raw_text,
            provider=self.name,
            model=self.model or "mock-vision-1",
            usage=ProviderUsage(),
            latency_ms=latency_ms,
        )


class OpenAICompatibleVisionProvider(VisionProvider):
    """OpenAI-compatible chat-completions provider with image input."""

    name = ProviderName.OPENAI

    def analyze(self, *, image_bytes: bytes, mime_type: str, prompt: str) -> ProviderResult:
        base_url = (self.config.base_url or "https://api.openai.com/v1").rstrip("/")
        if not self.config.api_key:
            raise VisionProviderUnavailableError(
                "VISION_LLM_API_KEY is not configured.", retryable=False
            )
        if not self.config.model:
            raise VisionProviderUnavailableError(
                "VISION_LLM_MODEL is not configured.", retryable=False
            )

        data_uri = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        body = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyse the attached chart screenshot."},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                },
            ],
        }
        started = time.monotonic()
        response = self._post_json(
            url=f"{base_url}/chat/completions",
            payload=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
        )
        latency_ms = int((time.monotonic() - started) * 1000)

        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise VisionResponseError("Provider response is missing message content.") from exc
        if not isinstance(content, str) or not content.strip():
            raise VisionResponseError("Provider returned empty message content.")

        usage_raw = response.get("usage") or {}
        usage = ProviderUsage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
            total_tokens=int(usage_raw.get("total_tokens", 0) or 0),
        )
        model = str(response.get("model") or self.config.model)
        return ProviderResult(
            raw_text=content,
            provider=self.name,
            model=model,
            usage=usage,
            latency_ms=latency_ms,
        )

    def _post_json(self, *, url: str, payload: dict, headers: dict) -> dict:
        """POST JSON and decode the response. Overridable for testing."""
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = _safe_error_body(exc)
            retry_after = _parse_retry_after(exc.headers.get("Retry-After"))
            if exc.code == 429:
                raise VisionRateLimitError(
                    f"Provider rate limit reached (429): {detail}", retry_after=retry_after
                ) from exc
            if exc.code in (401, 403):
                raise VisionProviderUnavailableError(
                    f"Provider rejected the credentials ({exc.code}).", retryable=False
                ) from exc
            if exc.code >= 500:
                raise VisionProviderUnavailableError(
                    f"Provider server error ({exc.code}): {detail}"
                ) from exc
            raise VisionResponseError(f"Provider returned HTTP {exc.code}: {detail}") from exc
        except TimeoutError as exc:
            raise VisionTimeoutError(
                f"Provider did not respond within {self.config.timeout_seconds}s."
            ) from exc
        except urllib.error.URLError as exc:
            raise VisionProviderUnavailableError(f"Provider unreachable: {exc.reason}") from exc

        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise VisionResponseError("Provider returned a non-JSON HTTP body.") from exc
        if not isinstance(decoded, dict):
            raise VisionResponseError("Provider returned an unexpected JSON shape.")
        return decoded


#: ``custom`` shares the OpenAI-compatible wire protocol.
CustomVisionProvider = OpenAICompatibleVisionProvider


def get_vision_provider(
    provider_name: str | None = None, *, config: ProviderConfig | None = None
) -> VisionProvider:
    """Return the configured provider instance."""
    resolved = (
        provider_name or str(getattr(settings, "VISION_LLM_PROVIDER", "mock") or "mock")
    ).lower()
    resolved_config = config or ProviderConfig.from_settings()
    if resolved == ProviderName.MOCK:
        return MockVisionProvider(resolved_config)
    if resolved in {ProviderName.OPENAI, ProviderName.CUSTOM}:
        return OpenAICompatibleVisionProvider(resolved_config)
    raise VisionProviderUnavailableError(f"Unknown vision provider {resolved!r}.", retryable=False)


def _parse_retry_after(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _safe_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - defensive
        return ""
    return body[:500]


def build_mock_payload() -> dict:
    """A schema-valid, clearly-illustrative payload for the mock provider."""
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_status": "partial",
        "screenshot_quality": {
            "rating": "medium",
            "issues": [],
            "notes": f"Mock provider ({PROMPT_VERSION}) — illustrative output only.",
        },
        "chart_metadata": {
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
        "candles": [
            {
                "index": 0,
                "position": "mid-left",
                "classification": "bullish",
                "body_size": "medium",
                "upper_wick": "small",
                "lower_wick": "small",
                "high_px": 100,
                "low_px": 160,
                "body_top_px": 110,
                "body_bottom_px": 150,
                "appears_complete": True,
                "confidence": 0.3,
                "ambiguity": None,
            },
            {
                "index": 1,
                "position": "right",
                "classification": "bearish",
                "body_size": "small",
                "upper_wick": "medium",
                "lower_wick": "small",
                "high_px": 105,
                "low_px": 165,
                "body_top_px": 130,
                "body_bottom_px": 160,
                "appears_complete": False,
                "confidence": 0.2,
                "ambiguity": "Rightmost candle may still be forming.",
            },
        ],
        "market_structure": {
            "trend": "unclear",
            "higher_highs": None,
            "higher_lows": None,
            "lower_highs": None,
            "lower_lows": None,
            "swing_highs": [],
            "swing_lows": [],
            "breakouts": [],
            "failed_breakouts": [],
            "consolidation": None,
            "notes": "Mock provider output.",
            "confidence": 0.0,
        },
        "support_resistance": [],
        "patterns": [],
        "sequence_observations": [],
        "market_cycle": {
            "observed": False,
            "phase": "insufficient",
            "description": "Mock provider output.",
            "confidence": 0.0,
        },
        "liquidity": [],
        "volume": {
            "patterns": [],
            "indicator_present": None,
            "notes": "",
            "confidence": 0.0,
        },
        "missing_information": ["mock provider provides no real observations"],
        "warnings": [
            "MOCK PROVIDER: illustrative output for development only; not a real analysis."
        ],
        "observation_confidence": {"overall": 0.0, "notes": "Mock provider output."},
    }


__all__ = [
    "CustomVisionProvider",
    "MockVisionProvider",
    "OpenAICompatibleVisionProvider",
    "ProviderConfig",
    "VisionProvider",
    "build_mock_payload",
    "get_vision_provider",
]
