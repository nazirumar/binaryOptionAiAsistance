# ai_assistant/services/reasoning_provider.py
"""Configurable reasoning-model interface (Step 5, real integration in Phase 11 CP4).

The reasoning LLM *explains* results produced by the deterministic and
statistical engines; it never overrides them. This module implements real HTTP
adapters for two provider families:

* ``openai`` — any OpenAI-compatible ``/chat/completions`` endpoint
  (OpenAI itself, OpenRouter, LM Studio, vLLM, …) selected via
  ``REASONING_LLM_BASE_URL``;
* ``google`` — the Gemini ``generateContent`` API (the provider configured in
  this project's ``.env``).

Safety and cost contract
------------------------
* **Credentials** come from ``REASONING_LLM_*`` settings only; they are sent
  via request headers, never persisted, never logged, never returned.
* **Timeouts**: one bounded connect+read timeout per attempt
  (``REASONING_LLM_TIMEOUT_SECONDS``).
* **Bounded retries** (``REASONING_LLM_MAX_RETRIES``) with capped exponential
  backoff; HTTP 429 honours a bounded ``Retry-After``; other 4xx are terminal.
* **Cost bounds**: output tokens capped by ``REASONING_LLM_MAX_TOKENS``,
  sanitized context capped by ``MAX_CONTEXT_CHARS``.
* **Redaction**: only a sanitized copy of the context leaves the process —
  keys that look like credentials are dropped and ``Bearer``/``sk-``-style
  values are stripped from strings.
* **Prompt/model version tracking**: every response carries
  ``prompt_version`` (this module's ``REASONING_PROMPT_VERSION``) and
  ``model_version``.
* **Direction guardrail**: when the deterministic engine decided
  ``NO TRADE``, a provider answer that asserts a directional trade call is
  *discarded* (``error="direction_guardrail_violation"``) and the deterministic
  explanation is used instead. A provider can never flip a decision.
* **Safe fallback**: any failure returns ``success=False``; what the caller
  sees in ``content`` is governed by ``REASONING_FALLBACK_ON_FAILURE``.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

logger = logging.getLogger("apps.ai_assistant")

DEFAULT_TIMEOUT_SECONDS = 30
MAX_RETRIES = 2
DEFAULT_MAX_TOKENS = 512
DEFAULT_TEMPERATURE = 0.1

#: Bump whenever the system prompt below changes meaningfully. Traced onto
#: every response so an explanation can always be attributed to a prompt.
REASONING_PROMPT_VERSION = "phase11-v1"

SUPPORTED_PROVIDERS = ("mock", "openai", "google")

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

#: Hard cap on the serialized context shipped to a provider.
MAX_CONTEXT_CHARS = 6000

#: Per-string cap inside the sanitized context.
MAX_CONTEXT_VALUE_CHARS = 2000

#: Cap on ``Retry-After`` / backoff sleeps so a hostile or broken endpoint
#: cannot stall a worker.
MAX_RETRY_SLEEP_SECONDS = 10.0

#: Keys that must never leave the process.
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|apikey|token|secret|password|passwd|authorization|"
    r"credential|dsn|private[_-]?key|sessionid|cookie)"
)

#: Values that look like credentials embedded in free text.
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)\b(bearer\s+\S+|sk-[A-Za-z0-9_\-]{8,}|AIza[A-Za-z0-9_\-]{10,})"
)

#: Direction-claim patterns used by the guardrail. An *intent* verb followed
#: (within a short window) by a direction word inside the same sentence.
_DIRECTION_INTENT_RE = re.compile(
    r"(?i)\b(?:predict(?:s|ed|ing|ion)?|expect(?:s|ed|ing)?|recommend(?:s|ed|ing)?|"
    r"signal(?:s|ed|ing)?|suggest(?:s|ed|ing)?|"
    r"will\s+(?:go|rise|fall|move|close|turn)|"
    r"should\s+(?:go|buy|sell|rise|fall)|"
    r"look(?:ing)?\s+(?:for|to)\s+(?:buy|sell))\b"
    r"[^.!?\n]{0,48}"
    r"\b(up|down|buy|sell|long|short|rise|rising|fall|falling|rally|drop)\b",
    re.IGNORECASE,
)

_BULLISH_WORDS = frozenset({"up", "buy", "long", "rise", "rising", "rally"})
_BEARISH_WORDS = frozenset({"down", "sell", "short", "fall", "falling", "drop"})

REASONING_SYSTEM_PROMPT = (
    "You are an explanation assistant inside a trading-analysis system. "
    "Explain ONLY the verified evidence supplied in the context. "
    "Never invent market data, prices, probabilities or trading outcomes. "
    "The deterministic decision recorded in the context (the 'direction' field) "
    "is FINAL: you must not change it and must not issue a different direction. "
    "When the direction is NO TRADE, explain why no trade is warranted and "
    "never predict that price will go up or down. "
    "Keep the answer concise (max 120 words) and plain text."
)


@dataclass(frozen=True, slots=True)
class ReasoningRequest:
    """Structured input for the reasoning provider."""

    messages: tuple[dict[str, str], ...]
    context: dict[str, Any] = field(default_factory=dict)
    prompt_version: str = REASONING_PROMPT_VERSION
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
    tokens_used: int = 0


@dataclass(frozen=True, slots=True)
class _HttpResult:
    status: int
    body: bytes
    retry_after: float | None = None


class ReasoningProvider:
    """Provider abstraction supporting mock and real external providers.

    Credentials are read from REASONING_LLM_* environment variables only and
    are never hardcoded or persisted.
    """

    def __init__(self, provider: str | None = None, model: str | None = None) -> None:
        self.provider = provider or getattr(settings, "REASONING_LLM_PROVIDER", "mock")
        self.model = model or getattr(settings, "REASONING_LLM_MODEL", "")
        self.api_key = getattr(settings, "REASONING_LLM_API_KEY", "")
        self.base_url = (getattr(settings, "REASONING_LLM_BASE_URL", "") or "").rstrip("/")
        self.timeout = getattr(settings, "REASONING_LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        self.max_retries = getattr(settings, "REASONING_LLM_MAX_RETRIES", MAX_RETRIES)
        self.max_tokens = int(getattr(settings, "REASONING_LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS))
        self.temperature = float(
            getattr(settings, "REASONING_LLM_TEMPERATURE", DEFAULT_TEMPERATURE)
        )
        #: ``REASONING_FALLBACK_ON_FAILURE`` — see :meth:`_failure`.
        self.fallback_on_failure = bool(getattr(settings, "REASONING_FALLBACK_ON_FAILURE", True))

    @property
    def is_configured(self) -> bool:
        if self.provider == "mock":
            return True
        if not self.api_key:
            return False
        return self.provider in SUPPORTED_PROVIDERS

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
        if self.provider not in SUPPORTED_PROVIDERS:
            logger.error("reasoning provider %s unsupported", self.provider)
            return self._failure(request, error="provider_unsupported")
        if not self.model:
            return self._failure(request, error="provider_model_missing")
        return self._http_complete(request)

    # -- HTTP transport ----------------------------------------------------

    def _http_complete(self, request: ReasoningRequest) -> ReasoningResponse:
        # Size gate applies to the RAW context: an oversized context is a
        # caller bug and must be refused, not silently truncated into
        # plausibility.
        raw_context = request.context or {}
        if len(json.dumps(raw_context, default=str)) > MAX_CONTEXT_CHARS:
            logger.warning("reasoning context exceeds %d chars; refusing", MAX_CONTEXT_CHARS)
            return self._failure(request, error="context_too_large")
        sanitized_context = self.sanitize_context(raw_context)

        url, headers, payload = self._build_http_request(request, sanitized_context)
        body = json.dumps(payload).encode("utf-8")
        attempts = max(1, int(self.max_retries) + 1)
        last_error = "provider_error"

        for attempt in range(attempts):
            try:
                result = self._post(url, body, headers)
            except TimeoutError:
                last_error = "provider_timeout"
                logger.warning("reasoning provider timeout (attempt %d)", attempt + 1)
                self._sleep(attempt, None)
                continue
            except urllib.error.URLError as exc:
                last_error = "provider_connection_error"
                logger.warning(
                    "reasoning provider connection error (attempt %d): %s",
                    attempt + 1,
                    type(exc.reason).__name__,
                )
                self._sleep(attempt, None)
                continue

            if result.status == 200:
                return self._handle_success(request, result)
            if result.status == 429:
                last_error = "provider_rate_limited"
                logger.warning("reasoning provider rate limited (attempt %d)", attempt + 1)
                self._sleep(attempt, result.retry_after)
                continue
            if result.status >= 500:
                last_error = "provider_server_error"
                logger.warning(
                    "reasoning provider HTTP %d (attempt %d)", result.status, attempt + 1
                )
                self._sleep(attempt, result.retry_after)
                continue
            # Other 4xx are terminal: retrying cannot fix a bad request.
            logger.error("reasoning provider HTTP %d: terminal client error", result.status)
            return self._failure(request, error=f"provider_http_{result.status}")

        return self._failure(request, error=last_error)

    def _post(self, url: str, body: bytes, headers: dict[str, str]) -> _HttpResult:
        """POST JSON and return a normalized result (never raises HTTPError)."""
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return _HttpResult(status=response.status, body=response.read())
        except urllib.error.HTTPError as exc:
            retry_after = _parse_retry_after(
                exc.headers.get("Retry-After") if exc.headers else None
            )
            payload = b""
            try:
                payload = exc.read()
            except Exception:  # pragma: no cover - defensive
                pass
            return _HttpResult(status=exc.code, body=payload, retry_after=retry_after)

    def _handle_success(self, request: ReasoningRequest, result: _HttpResult) -> ReasoningResponse:
        try:
            parsed = json.loads(result.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._failure(request, error="provider_invalid_response")
        content = self._extract_content(parsed)
        if not content:
            return self._failure(request, error="provider_invalid_response")

        engine_direction = str((request.context or {}).get("direction", "") or "")
        if self._guardrail_violation(content, engine_direction):
            logger.error(
                "reasoning provider violated direction guardrail (%s vs engine %s)",
                engine_direction,
                engine_direction,
            )
            return self._failure(request, error="direction_guardrail_violation")

        return ReasoningResponse(
            content=content,
            provider=self.provider,
            model=self.model,
            prompt_version=request.prompt_version,
            model_version=str(self.model),
            success=True,
            tokens_used=_extract_tokens(parsed),
        )

    # -- provider payloads --------------------------------------------------

    def _build_http_request(
        self, request: ReasoningRequest, context: dict[str, Any]
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        if self.provider == "google":
            return self._build_google_request(request, context)
        return self._build_openai_request(request, context)

    def _build_openai_request(
        self, request: ReasoningRequest, context: dict[str, Any]
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        base = self.base_url or DEFAULT_OPENAI_BASE_URL
        url = f"{base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            # Some OpenAI-compatible hosts (e.g. Groq) sit behind Cloudflare,
            # which rejects urllib's default "Python-urllib/..." signature with
            # error 1010. A descriptive UA identifies the client honestly.
            "User-Agent": "nazbeen-academy/0.1",
        }
        messages = [{"role": "system", "content": REASONING_SYSTEM_PROMPT}]
        messages.append(
            {
                "role": "system",
                "content": "Verified engine context: " + json.dumps(context, default=str),
            }
        )
        for message in request.messages:
            role = message.get("role", "user")
            content = str(message.get("content", ""))[:MAX_CONTEXT_VALUE_CHARS]
            messages.append(
                {"role": role if role in ("user", "assistant") else "user", "content": content}
            )
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        return url, headers, payload

    def _build_google_request(
        self, request: ReasoningRequest, context: dict[str, Any]
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        base = self.base_url or DEFAULT_GOOGLE_BASE_URL
        url = f"{base}/models/{self.model}:generateContent"
        # The API key travels in a header, never in the URL (logs/referrers).
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        user_text = "\n".join(
            str(m.get("content", ""))[:MAX_CONTEXT_VALUE_CHARS] for m in request.messages
        )
        payload = {
            "systemInstruction": {"parts": [{"text": REASONING_SYSTEM_PROMPT}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Verified engine context: "
                                + json.dumps(context, default=str)
                                + "\n\nUser question:\n"
                                + user_text
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "maxOutputTokens": self.max_tokens,
                "temperature": self.temperature,
            },
        }
        return url, headers, payload

    # -- response parsing ---------------------------------------------------

    @staticmethod
    def _extract_content(parsed: Any) -> str:
        if not isinstance(parsed, dict):
            return ""
        try:
            if "choices" in parsed:  # OpenAI-compatible
                return str(parsed["choices"][0]["message"]["content"] or "").strip()
            candidates = parsed.get("candidates") or []  # Google Gemini
            if candidates:
                parts = (candidates[0].get("content") or {}).get("parts") or []
                return "".join(str(p.get("text", "")) for p in parts).strip()
        except (KeyError, IndexError, TypeError, AttributeError):
            return ""
        return ""

    # -- safety helpers -----------------------------------------------------

    @staticmethod
    def sanitize_context(context: dict[str, Any] | None) -> dict[str, Any]:
        """Return a credential-free, size-bounded copy of ``context``."""
        sanitized: dict[str, Any] = {}
        for key, value in (context or {}).items():
            name = str(key)
            if _SENSITIVE_KEY_RE.search(name):
                sanitized[name] = "[redacted]"
                continue
            if isinstance(value, str):
                cleaned = _SENSITIVE_VALUE_RE.sub("[redacted]", value)
                sanitized[name] = cleaned[:MAX_CONTEXT_VALUE_CHARS]
            elif value is None or isinstance(value, int | float | bool):
                sanitized[name] = value
            else:
                sanitized[name] = _SENSITIVE_VALUE_RE.sub("[redacted]", str(value))[
                    :MAX_CONTEXT_VALUE_CHARS
                ]
        return sanitized

    @staticmethod
    def _guardrail_violation(content: str, engine_direction: str) -> bool:
        """True when the text contradicts the deterministic decision.

        A ``NO TRADE`` decision may never be flipped into an actionable
        UP/DOWN call; a directional decision may never be contradicted by the
        opposite call.
        """
        match = _DIRECTION_INTENT_RE.search(content)
        if not match:
            return False
        word = match.group(1).lower()
        direction = (engine_direction or "").strip().upper()
        if direction in ("NO TRADE", "NO_TRADE", ""):
            return True
        if direction == "UP" and word in _BEARISH_WORDS:
            return True
        if direction == "DOWN" and word in _BULLISH_WORDS:
            return True
        return False

    def _sleep(self, attempt: int, retry_after: float | None) -> None:
        """Bounded backoff honouring ``Retry-After`` when supplied."""
        if attempt >= max(1, int(self.max_retries)):
            return  # last attempt: no point sleeping
        delay = retry_after if retry_after is not None else 0.5 * (2**attempt)
        time.sleep(min(max(delay, 0.0), MAX_RETRY_SLEEP_SECONDS))

    # -- failure / fallback -------------------------------------------------

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


def _parse_retry_after(raw: Any) -> float | None:
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return seconds


def _extract_tokens(parsed: Any) -> int:
    if not isinstance(parsed, dict):
        return 0
    usage = parsed.get("usage") or {}
    for key in ("total_tokens", "totalTokenCount"):
        value = usage.get(key, parsed.get(key))
        if isinstance(value, int | float) and value >= 0:
            return int(value)
    metadata = parsed.get("usageMetadata") or {}
    value = metadata.get("totalTokenCount")
    if isinstance(value, int | float) and value >= 0:
        return int(value)
    return 0


__all__ = [
    "MAX_CONTEXT_CHARS",
    "REASONING_PROMPT_VERSION",
    "REASONING_SYSTEM_PROMPT",
    "SUPPORTED_PROVIDERS",
    "ReasoningProvider",
    "ReasoningRequest",
    "ReasoningResponse",
]
