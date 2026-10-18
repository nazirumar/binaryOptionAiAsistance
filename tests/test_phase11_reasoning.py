# tests/test_phase11_reasoning.py
"""Phase 11 CP4 — real reasoning-provider integration (mocked HTTP).

Proves the OpenAI-compatible and Google Gemini adapters:

* extract structured content from real response shapes;
* enforce timeouts, bounded retries, 429 Retry-After and terminal 4xx;
* cap tokens, sanitize/redact context, never leak the API key into the URL;
* track prompt/model versions;
* enforce the direction guardrail (a provider can never flip NO TRADE);
* fall back safely with ``success=False`` on every failure path.

The optional live smoke test at the bottom runs ONLY when the operator sets
``REASONING_LLM_LIVE_TEST=1`` with a configured provider and key.
"""

from __future__ import annotations

import io
import json
import os
import urllib.error
from types import SimpleNamespace

import pytest
from django.test import override_settings

from apps.ai_assistant.services import reasoning_provider as rp
from apps.ai_assistant.services.reasoning_provider import (
    REASONING_PROMPT_VERSION,
    ReasoningProvider,
    ReasoningRequest,
)

pytestmark = pytest.mark.django_db

OPENAI_OK = {
    "choices": [{"message": {"role": "assistant", "content": "Support held on the last candle."}}],
    "usage": {"total_tokens": 42},
}
GOOGLE_OK = {
    "candidates": [{"content": {"parts": [{"text": "Buyers failed at resistance."}]}}],
    "usageMetadata": {"totalTokenCount": 37},
}


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _router(routes):
    """Return an urlopen replacement serving ``routes`` (list of callables/dicts)."""
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(
            {
                "url": request.full_url,
                "body": json.loads(request.data.decode()),
                "headers": dict(request.header_items()),
                "timeout": timeout,
            }
        )
        index = min(len(calls) - 1, len(routes) - 1)
        route = routes[index]
        if isinstance(route, Exception):
            raise route
        if isinstance(route, tuple):  # (status, payload) -> HTTPError
            status, payload = route
            raise urllib.error.HTTPError(
                request.full_url,
                status,
                "error",
                {"Retry-After": "1"},
                io.BytesIO(json.dumps(payload).encode()),
            )
        return route

    return fake_urlopen, calls


def _request(direction: str = "NO TRADE", **context) -> ReasoningRequest:
    ctx = {"direction": direction, "explanation": "Deterministic engine: no setup."}
    ctx.update(context)
    return ReasoningRequest(messages=({"role": "user", "content": "why no trade?"},), context=ctx)


def _provider(monkeypatch, routes, **overrides) -> tuple[ReasoningProvider, list]:
    base = {
        "REASONING_LLM_PROVIDER": "openai",
        "REASONING_LLM_API_KEY": "test-key-123",
        "REASONING_LLM_MODEL": "test-model",
        "REASONING_FALLBACK_ON_FAILURE": True,
    }
    base.update(overrides)
    fake_urlopen, calls = _router(routes)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(rp, "time", SimpleNamespace(sleep=lambda s: None))
    with override_settings(**base):
        return ReasoningProvider(), calls


class TestOpenAIAdapter:
    def test_success_returns_content_and_versions(self, monkeypatch):
        provider, calls = _provider(monkeypatch, [FakeResponse(OPENAI_OK)])
        response = provider.complete(_request())
        assert response.success is True
        assert response.content == "Support held on the last candle."
        assert response.prompt_version == REASONING_PROMPT_VERSION
        assert response.model_version == "test-model"
        assert response.tokens_used == 42
        assert calls[0]["url"].endswith("/chat/completions")
        assert calls[0]["body"]["max_tokens"] == 512

    def test_base_url_override_is_honoured(self, monkeypatch):
        provider, calls = _provider(
            monkeypatch,
            [FakeResponse(OPENAI_OK)],
            REASONING_LLM_BASE_URL="https://router.example/v1",
        )
        provider.complete(_request())
        assert calls[0]["url"] == "https://router.example/v1/chat/completions"

    def test_api_key_header_not_in_url(self, monkeypatch):
        provider, calls = _provider(monkeypatch, [FakeResponse(OPENAI_OK)])
        provider.complete(_request())
        assert "test-key-123" not in calls[0]["url"]
        assert any("test-key-123" in str(v) for v in calls[0]["headers"].values())

    def test_rate_limit_retries_and_succeeds(self, monkeypatch):
        provider, calls = _provider(
            monkeypatch, [(429, {"error": "slow down"}), FakeResponse(OPENAI_OK)]
        )
        response = provider.complete(_request())
        assert response.success is True
        assert len(calls) == 2

    def test_server_errors_exhaust_retries_then_fall_back(self, monkeypatch):
        provider, calls = _provider(monkeypatch, [(500, {}), (500, {}), (503, {})])
        response = provider.complete(_request())
        assert response.success is False
        assert response.error == "provider_server_error"
        assert response.content == "Deterministic engine: no setup."
        assert len(calls) == 3  # bounded: max_retries(2) + 1

    def test_client_error_is_terminal(self, monkeypatch):
        provider, calls = _provider(monkeypatch, [(400, {"error": "bad request"})])
        response = provider.complete(_request())
        assert response.success is False
        assert response.error == "provider_http_400"
        assert len(calls) == 1

    def test_timeout_is_reported(self, monkeypatch):
        provider, _calls = _provider(monkeypatch, [TimeoutError("timed out")])
        response = provider.complete(_request())
        assert response.success is False
        assert response.error == "provider_timeout"
        assert response.content == "Deterministic engine: no setup."

    def test_connection_error_is_reported(self, monkeypatch):
        provider, _calls = _provider(monkeypatch, [urllib.error.URLError(ConnectionRefusedError())])
        response = provider.complete(_request())
        assert response.success is False
        assert response.error == "provider_connection_error"

    def test_invalid_json_body_fails_closed(self, monkeypatch):
        provider, _calls = _provider(
            monkeypatch, [FakeResponse({}), FakeResponse({}), FakeResponse({})]
        )
        response = provider.complete(_request())
        assert response.success is False
        assert response.error == "provider_invalid_response"

    def test_timeout_setting_is_passed_to_urlopen(self, monkeypatch):
        provider, calls = _provider(
            monkeypatch, [FakeResponse(OPENAI_OK)], REASONING_LLM_TIMEOUT_SECONDS=7
        )
        provider.complete(_request())
        assert calls[0]["timeout"] == 7


class TestGoogleAdapter:
    def test_success_uses_gemini_shape(self, monkeypatch):
        provider, calls = _provider(
            monkeypatch,
            [FakeResponse(GOOGLE_OK)],
            REASONING_LLM_PROVIDER="google",
            REASONING_LLM_MODEL="gemini-1.5-pro",
        )
        response = provider.complete(_request())
        assert response.success is True
        assert response.content == "Buyers failed at resistance."
        assert response.tokens_used == 37
        assert ":generateContent" in calls[0]["url"]

    def test_api_key_in_header_not_query_string(self, monkeypatch):
        provider, calls = _provider(
            monkeypatch,
            [FakeResponse(GOOGLE_OK)],
            REASONING_LLM_PROVIDER="google",
            REASONING_LLM_MODEL="gemini-1.5-pro",
        )
        provider.complete(_request())
        assert "key=" not in calls[0]["url"]
        # urllib normalises header capitalisation ("X-goog-api-key").
        headers = {k.lower(): v for k, v in calls[0]["headers"].items()}
        assert headers.get("x-goog-api-key") == "test-key-123"

    def test_generation_config_is_capped(self, monkeypatch):
        provider, calls = _provider(
            monkeypatch,
            [FakeResponse(GOOGLE_OK)],
            REASONING_LLM_PROVIDER="google",
            REASONING_LLM_MODEL="gemini-1.5-pro",
            REASONING_LLM_MAX_TOKENS=128,
        )
        provider.complete(_request())
        assert calls[0]["body"]["generationConfig"]["maxOutputTokens"] == 128


class TestConfigurationGuards:
    def test_missing_key_falls_back(self):
        with override_settings(
            REASONING_LLM_PROVIDER="google",
            REASONING_LLM_API_KEY="",
            REASONING_FALLBACK_ON_FAILURE=True,
        ):
            response = ReasoningProvider().complete(_request())
        assert response.success is False
        assert response.error == "provider_not_configured"
        assert response.content == "Deterministic engine: no setup."

    def test_unsupported_provider_with_key(self, monkeypatch):
        provider, _calls = _provider(
            monkeypatch, [FakeResponse(OPENAI_OK)], REASONING_LLM_PROVIDER="other"
        )
        provider.api_key = "k"
        response = provider.complete(_request())
        assert response.error == "provider_unsupported"

    def test_missing_model_is_reported(self, monkeypatch):
        provider, _calls = _provider(monkeypatch, [FakeResponse(OPENAI_OK)], REASONING_LLM_MODEL="")
        response = provider.complete(_request())
        assert response.error == "provider_model_missing"

    def test_oversized_context_refused(self, monkeypatch):
        provider, _calls = _provider(monkeypatch, [FakeResponse(OPENAI_OK)])
        request = _request(note="x" * (rp.MAX_CONTEXT_CHARS + 10))
        response = provider.complete(request)
        assert response.error == "context_too_large"
        assert response.content == "Deterministic engine: no setup."


class TestRedaction:
    def test_sensitive_keys_are_redacted_in_payload(self, monkeypatch):
        provider, calls = _provider(monkeypatch, [FakeResponse(OPENAI_OK)])
        provider.complete(_request(api_key="super-secret", user_token="tok-1", password="hunter2"))
        body = json.dumps(calls[0]["body"])
        assert "super-secret" not in body
        assert "tok-1" not in body
        assert "hunter2" not in body
        assert body.count("[redacted]") >= 3

    def test_credential_shaped_values_in_free_text_are_stripped(self, monkeypatch):
        provider, calls = _provider(monkeypatch, [FakeResponse(OPENAI_OK)])
        provider.complete(_request(note="header was Bearer abc.def and key sk-abcdefghijklmnop"))
        body = json.dumps(calls[0]["body"])
        assert "abc.def" not in body
        assert "sk-abcdefghijklmnop" not in body


class TestDirectionGuardrail:
    def test_no_trade_is_never_flipped(self, monkeypatch):
        provider, _calls = _provider(
            monkeypatch,
            [
                FakeResponse(
                    {"choices": [{"message": {"content": "The price will go up next candle."}}]}
                )
            ],
        )
        response = provider.complete(_request(direction="NO TRADE"))
        assert response.success is False
        assert response.error == "direction_guardrail_violation"
        # The deterministic explanation is used instead — nothing invented.
        assert response.content == "Deterministic engine: no setup."

    def test_no_trade_rejects_sell_recommendation(self, monkeypatch):
        provider, _calls = _provider(
            monkeypatch,
            [FakeResponse({"choices": [{"message": {"content": "I recommend you sell here."}}]})],
        )
        response = provider.complete(_request(direction="NO TRADE"))
        assert response.error == "direction_guardrail_violation"

    def test_up_decision_cannot_be_contradicted(self, monkeypatch):
        provider, _calls = _provider(
            monkeypatch,
            [FakeResponse({"choices": [{"message": {"content": "I expect it to fall instead."}}]})],
        )
        response = provider.complete(_request(direction="UP"))
        assert response.error == "direction_guardrail_violation"

    def test_agreeing_answer_passes(self, monkeypatch):
        provider, _calls = _provider(
            monkeypatch,
            [
                FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": "Buyers defended support; the engine reports UP."
                                }
                            }
                        ]
                    }
                )
            ],
        )
        response = provider.complete(_request(direction="UP"))
        assert response.success is True

    def test_neutral_explanation_of_no_trade_passes(self, monkeypatch):
        provider, _calls = _provider(
            monkeypatch,
            [
                FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": "No setup formed: price sat between support and resistance."
                                }
                            }
                        ]
                    }
                )
            ],
        )
        response = provider.complete(_request(direction="NO TRADE"))
        assert response.success is True


# ---------------------------------------------------------------------------
# Optional LIVE smoke test — never runs unless explicitly enabled.
# ---------------------------------------------------------------------------
@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("REASONING_LLM_LIVE_TEST") != "1"
    or os.environ.get("REASONING_LLM_PROVIDER", "mock") == "mock"
    or not os.environ.get("REASONING_LLM_API_KEY"),
    reason="Live reasoning smoke test requires REASONING_LLM_LIVE_TEST=1 and a configured provider/key",
)
def test_live_reasoning_smoke():
    """One real request against the configured provider. Report honestly.

    The provider is assembled explicitly from ``os.environ`` — NOT from
    Django settings — so test settings (which force the mock provider for
    hermeticity) cannot silently turn this into a fake pass.
    """
    provider = ReasoningProvider(
        provider=os.environ["REASONING_LLM_PROVIDER"],
        model=os.environ.get("REASONING_LLM_MODEL", ""),
    )
    provider.api_key = os.environ["REASONING_LLM_API_KEY"]
    response = provider.complete(
        ReasoningRequest(
            messages=(
                {"role": "user", "content": "Summarise the supplied context in one sentence."},
            ),
            context={"direction": "NO TRADE", "explanation": "Deterministic engine: no setup."},
        )
    )
    assert response.success is True, f"live provider failed: {response.error}"
    assert response.content
    assert response.provider == os.environ["REASONING_LLM_PROVIDER"]
