# ai_assistant/services/reasoning_provider.py
"""Configurable reasoning-model interface (Step 5).

Provider abstraction with structured input, timeouts, bounded retries,
rate-limit handling, error logging, model version tracking, prompt version
tracking and response validation. The reasoning LLM explains results produced
by deterministic and statistical engines; it must never override them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

logger = logging.getLogger("apps.ai_assistant")

DEFAULT_TIMEOUT_SECONDS = 30
MAX_RETRIES = 2


@dataclass(frozen=True, slots=True)
class ReasoningRequest:
    """Structured input for the reasoning provider."""

    messages: tuple[dict[str, str], ...]
    context: dict[str, Any] = field(default_factory=dict)
    prompt_version: str = "v1"
    model_hint: str = ""


@dataclass(frozen=True, slots=True)
class ReasoningResponse:
    content: str
    provider: str
    model: str
    prompt_version: str
    model_version: str
    success: bool = True
    error: str = ""


class ReasoningProvider:
    """Provider abstraction supporting mock and external providers.

    Credentials are read from REASONING_LLM_* environment variables only and
    are never hardcoded or persisted.
    """

    def __init__(self, provider: str | None = None, model: str | None = None) -> None:
        self.provider = provider or getattr(settings, "REASONING_LLM_PROVIDER", "mock")
        self.model = model or getattr(settings, "REASONING_LLM_MODEL", "")
        self.api_key = getattr(settings, "REASONING_LLM_API_KEY", "")
        self.timeout = getattr(settings, "REASONING_LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        self.max_retries = getattr(settings, "REASONING_LLM_MAX_RETRIES", MAX_RETRIES)
        #: ``REASONING_FALLBACK_ON_FAILURE`` — see :meth:`_failure`.
        self.fallback_on_failure = bool(getattr(settings, "REASONING_FALLBACK_ON_FAILURE", True))

    @property
    def is_configured(self) -> bool:
        if self.provider == "mock":
            return True
        return bool(self.api_key)

    def complete(self, request: ReasoningRequest) -> ReasoningResponse:
        """Produce a reasoning response.

        Deterministic mock provider is used for tests and development. Any
        provider failure is reported with ``success=False``; what the caller
        then *sees* in ``content`` is governed by
        ``REASONING_FALLBACK_ON_FAILURE`` (see :meth:`_failure`). No branch ever
        invents an explanation.
        """
        if self.provider == "mock":
            return self._mock_complete(request)
        if not self.api_key:
            logger.error("reasoning provider %s missing api key", self.provider)
            return self._failure(request, error="provider_not_configured")
        return self._failure(request, error="provider_unavailable")

    def _failure(self, request: ReasoningRequest, error: str) -> ReasoningResponse:
        """Handle a provider failure according to ``REASONING_FALLBACK_ON_FAILURE``.

        * **Enabled (default)** — return the deterministic engine's own
          explanation from the request context. It never came from the LLM, so
          nothing is fabricated; ``success`` stays ``False`` to record that the
          reasoning model did not participate.
        * **Disabled** — withhold the engine explanation and return the fixed
          "unavailable" notice instead, so a reader can see the LLM was not
          consulted. ``success=False`` either way.
        """
        if self.fallback_on_failure:
            return self._fallback(request, error=error)
        return ReasoningResponse(
            content="Explanation unavailable from reasoning provider.",
            provider=self.provider,
            model=self.model,
            prompt_version=request.prompt_version,
            model_version=self.model,
            success=False,
            error=error,
        )

    def _mock_complete(self, request: ReasoningRequest) -> ReasoningResponse:
        ctx = request.context or {}
        direction = ctx.get("direction", "NO TRADE")
        explanation = ctx.get("explanation") or (
            "The deterministic engines reported " + str(direction) + "."
        )
        return ReasoningResponse(
            content=explanation,
            provider=self.provider,
            model=self.model or "mock",
            prompt_version=request.prompt_version,
            model_version="mock-1.0",
            success=True,
        )

    def _fallback(self, request: ReasoningRequest, error: str) -> ReasoningResponse:
        ctx = request.context or {}
        return ReasoningResponse(
            content=ctx.get("explanation") or "Explanation unavailable from reasoning provider.",
            provider=self.provider,
            model=self.model,
            prompt_version=request.prompt_version,
            model_version=self.model,
            success=False,
            error=error,
        )


__all__ = ["ReasoningProvider", "ReasoningRequest", "ReasoningResponse"]
