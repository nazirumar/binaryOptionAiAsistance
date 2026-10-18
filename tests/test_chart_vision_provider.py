"""Tests for the configurable vision provider and bounded retry behaviour."""

from __future__ import annotations

import email.message
import json
import urllib.error
from unittest import mock

import pytest

from apps.chart_vision.services.dto import ProviderResult, ProviderUsage
from apps.chart_vision.services.exceptions import (
    VisionProviderUnavailableError,
    VisionRateLimitError,
    VisionResponseError,
    VisionTimeoutError,
)
from apps.chart_vision.services.vision_provider import (
    MockVisionProvider,
    OpenAICompatibleVisionProvider,
    ProviderConfig,
    VisionProvider,
    build_mock_payload,
    get_vision_provider,
)
from tests.vision_fakes import full_payload

pytestmark = pytest.mark.django_db

URL = "https://example.test/v1/chat/completions"


def _config(**overrides) -> ProviderConfig:
    base = {
        "provider": "openai",
        "model": "vision-test",
        "api_key": "secret-key",
        "base_url": "https://example.test/v1",
        "timeout_seconds": 5,
        "max_retries": 2,
        "backoff_seconds": 0.01,
        "max_tokens": 128,
        "temperature": 0.0,
    }
    base.update(overrides)
    return ProviderConfig(**base)


def _fake_response(payload: dict) -> mock.MagicMock:
    response = mock.MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__ = mock.MagicMock(return_value=response)
    response.__exit__ = mock.MagicMock(return_value=False)
    return response


def _http_error(code: int, *, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(URL, code, "error", headers, None)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def test_factory_returns_mock_provider(settings):
    settings.VISION_LLM_PROVIDER = "mock"
    assert isinstance(get_vision_provider(), MockVisionProvider)


@pytest.mark.parametrize("name", ["openai", "custom"])
def test_factory_returns_openai_compatible(name):
    assert isinstance(
        get_vision_provider(name, config=_config(provider=name)), OpenAICompatibleVisionProvider
    )


def test_factory_rejects_unknown_provider():
    with pytest.raises(VisionProviderUnavailableError):
        get_vision_provider("does-not-exist", config=_config())


def test_mock_provider_output_is_schema_shaped():
    provider = MockVisionProvider(_config(provider="mock", model=""))
    result = provider.analyze(image_bytes=b"x", mime_type="image/png", prompt="p")
    payload = json.loads(result.raw_text)
    assert payload["schema_version"] == "1.0"
    assert payload["candles"], "mock payload should include example candles"
    assert build_mock_payload()["warnings"]


# ---------------------------------------------------------------------------
# HTTP behaviour
# ---------------------------------------------------------------------------
def _success_payload() -> dict:
    return {
        "model": "vision-test-2",
        "choices": [{"message": {"content": json.dumps(full_payload())}}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 20, "total_tokens": 50},
    }


def test_http_success_parses_content_and_usage():
    provider = OpenAICompatibleVisionProvider(_config())
    with mock.patch("urllib.request.urlopen", return_value=_fake_response(_success_payload())):
        result = provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")
    assert result.model == "vision-test-2"
    assert result.usage.total_tokens == 50
    assert json.loads(result.raw_text)["chart_metadata"]["instrument"] == "EURUSD"


def test_missing_api_key_raises_non_retryable():
    provider = OpenAICompatibleVisionProvider(_config(api_key=""))
    with pytest.raises(VisionProviderUnavailableError) as excinfo:
        provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")
    assert excinfo.value.retryable is False


def test_missing_model_raises_non_retryable():
    provider = OpenAICompatibleVisionProvider(_config(model=""))
    with pytest.raises(VisionProviderUnavailableError) as excinfo:
        provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")
    assert excinfo.value.retryable is False


def test_rate_limit_maps_with_retry_after():
    provider = OpenAICompatibleVisionProvider(_config())
    with mock.patch("urllib.request.urlopen", side_effect=_http_error(429, retry_after="3")):
        with pytest.raises(VisionRateLimitError) as excinfo:
            provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")
    assert excinfo.value.retry_after == 3.0


def test_auth_error_is_non_retryable():
    provider = OpenAICompatibleVisionProvider(_config())
    with mock.patch("urllib.request.urlopen", side_effect=_http_error(401)):
        with pytest.raises(VisionProviderUnavailableError) as excinfo:
            provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")
    assert excinfo.value.retryable is False


def test_server_error_is_retryable():
    provider = OpenAICompatibleVisionProvider(_config())
    with mock.patch("urllib.request.urlopen", side_effect=_http_error(503)):
        with pytest.raises(VisionProviderUnavailableError) as excinfo:
            provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")
    assert excinfo.value.retryable is True


def test_timeout_maps_to_timeout_error():
    provider = OpenAICompatibleVisionProvider(_config())
    with mock.patch("urllib.request.urlopen", side_effect=TimeoutError):
        with pytest.raises(VisionTimeoutError):
            provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")


def test_unreachable_maps_to_unavailable():
    provider = OpenAICompatibleVisionProvider(_config())
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route")):
        with pytest.raises(VisionProviderUnavailableError):
            provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")


def test_non_json_body_raises_response_error():
    response = mock.MagicMock()
    response.read.return_value = b"<html>not json</html>"
    response.__enter__ = mock.MagicMock(return_value=response)
    response.__exit__ = mock.MagicMock(return_value=False)
    provider = OpenAICompatibleVisionProvider(_config())
    with mock.patch("urllib.request.urlopen", return_value=response):
        with pytest.raises(VisionResponseError):
            provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")


def test_missing_message_content_raises_response_error():
    provider = OpenAICompatibleVisionProvider(_config())
    with mock.patch("urllib.request.urlopen", return_value=_fake_response({"choices": []})):
        with pytest.raises(VisionResponseError):
            provider.analyze(image_bytes=b"img", mime_type="image/png", prompt="p")


# ---------------------------------------------------------------------------
# Analyzer retry loop
# ---------------------------------------------------------------------------
class _ScriptedProvider(VisionProvider):
    name = "scripted"

    def __init__(self, outcomes):
        super().__init__(_config(provider="scripted", max_retries=2, backoff_seconds=0.01))
        self._outcomes = list(outcomes)
        self.calls = 0

    def analyze(self, *, image_bytes, mime_type, prompt):
        outcome = self._outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return ProviderResult(
            raw_text=json.dumps(full_payload()),
            provider=self.name,
            model="scripted-1",
            usage=ProviderUsage(),
            latency_ms=1,
        )


def test_analyzer_retries_rate_limit_then_succeeds():
    from apps.chart_vision.services.screenshot_analyzer import ScreenshotAnalyzer
    from tests.factories import UserFactory
    from tests.vision_fakes import make_screenshot

    user = UserFactory(username="retry-analyst")
    screenshot = make_screenshot(user)
    sleep_calls = []
    provider = _ScriptedProvider([VisionRateLimitError("slow down", retry_after=2.0), "ok"])
    from apps.chart_vision.services.screenshot_analyzer import get_or_create_analysis

    analysis, _ = get_or_create_analysis(screenshot)
    ScreenshotAnalyzer(provider=provider, sleep=sleep_calls.append).analyze(screenshot, analysis)
    analysis.refresh_from_db()
    assert provider.calls == 2
    assert sleep_calls == [2.0]
    assert analysis.status == "completed"


def test_analyzer_gives_up_after_max_retries():
    from apps.chart_vision.services.screenshot_analyzer import (
        ScreenshotAnalyzer,
        get_or_create_analysis,
    )
    from tests.factories import UserFactory
    from tests.vision_fakes import make_screenshot

    user = UserFactory(username="retry-analyst-2")
    screenshot = make_screenshot(user)
    provider = _ScriptedProvider(
        [
            VisionTimeoutError("t1"),
            VisionTimeoutError("t2"),
            VisionTimeoutError("t3"),
        ]
    )
    analysis, _ = get_or_create_analysis(screenshot)
    with pytest.raises(VisionTimeoutError):
        ScreenshotAnalyzer(provider=provider, sleep=lambda _s: None).analyze(screenshot, analysis)
    # 1 initial attempt + 2 retries.
    assert provider.calls == 3
    analysis.refresh_from_db()
    assert analysis.status == "failed"
    assert analysis.error_code == "provider_timeout"
