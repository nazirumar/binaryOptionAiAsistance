# tests/test_phase10_env_wiring.py
"""Phase 10 follow-up — .env connectivity: every declared knob is actually wired.

``scripts/check_env_coverage.py`` cross-references three directions:

* code reads key X  -> X has a supplier (``.env`` / compose / entrypoint / CI)
* code reads key X  -> X is documented in ``.env.example``
* ``.env`` carries X -> something reads X (no dead knobs)

Before this follow-up four keys were dangling: ``DJANGO_LOG_REDACT_HEADERS``
and ``SENTRY_DSN`` were documented security features with no code behind them,
``REASONING_FALLBACK_ON_FAILURE`` was ignored by the provider, and
``VISION_DAILY_REQUEST_BUDGET`` described a guard that was never implemented
(it was removed rather than pretended). These tests pin each connection so the
wiring cannot silently disappear again, and run the coverage scanner itself as
the final gate.
"""

from __future__ import annotations

import importlib.util
import io
import logging
import subprocess
import sys
import types
import unittest.mock
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from apps.ai_assistant.services.reasoning_provider import (
    ReasoningProvider,
    ReasoningRequest,
)
from apps.core.logging import JsonFormatter, RedactHeadersFilter
from apps.core.observability import init_sentry

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HEADERS = ["Authorization", "Cookie", "X-API-Key"]


def _filter() -> RedactHeadersFilter:
    return RedactHeadersFilter(headers=DEFAULT_HEADERS)


def _load_scanner():
    spec = importlib.util.spec_from_file_location(
        "check_env_coverage", ROOT / "scripts" / "check_env_coverage.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# DJANGO_LOG_REDACT_HEADERS — RedactHeadersFilter
# ---------------------------------------------------------------------------
class TestLogRedaction:
    def test_masks_full_bearer_token_not_just_the_scheme(self) -> None:
        out = _filter()._redact_text(
            "call failed: Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload ok"
        )
        assert "eyJhbGciOiJIUzI1NiJ9" not in out
        assert "Authorization: ***" in out
        assert "call failed:" in out  # surrounding context survives

    def test_masks_meta_style_and_dict_reprs(self) -> None:
        meta = _filter()._redact_text("META HTTP_AUTHORIZATION = Bearer tok123")
        assert "tok123" not in meta

        as_dict = _filter()._redact_text(
            "headers {'Authorization': 'Bearer tok456', 'X-API-Key': 'k-9'}"
        )
        assert "tok456" not in as_dict
        assert "k-9" not in as_dict

    def test_masks_cookie_and_set_cookie(self) -> None:
        assert "session=abc" not in _filter()._redact_text("Cookie: session=abc; Path=/")
        assert "auth=z9" not in _filter()._redact_text("Set-Cookie: auth=z9; HttpOnly")

    def test_leaves_lines_without_headers_untouched(self) -> None:
        line = "sync completed for EURUSD M1 in 126 ms"
        assert _filter()._redact_text(line) == line

    def test_neighbouring_labelled_fields_survive(self) -> None:
        out = _filter()._redact_text("Authorization: Bearer abc, Cookie: def=1")
        assert "abc" not in out and "def=1" not in out
        assert "Cookie: ***" in out

    def test_filter_renders_message_and_scrubs_structured_extras(self) -> None:
        record = logging.LogRecord(
            "apps.test",
            logging.INFO,
            __file__,
            1,
            "upstream rejected Authorization: Bearer leak123",
            None,
            None,
        )
        record.headers = {
            "Cookie": "session=abc",
            "X-Api-Key": "k1",
            "accept": "application/json",
        }

        assert _filter().filter(record) is True

        assert "leak123" not in record.getMessage()
        assert record.args is None  # rendered once, no re-interpolation
        assert record.headers["Cookie"] == "***"
        assert record.headers["X-Api-Key"] == "***"
        assert record.headers["accept"] == "application/json"  # not a secret

    def test_json_formatter_output_is_secret_free(self) -> None:
        record = logging.LogRecord(
            "apps.test",
            logging.WARNING,
            __file__,
            1,
            "X-API-Key: topsecret999",
            None,
            None,
        )
        _filter().filter(record)
        rendered = JsonFormatter().format(record)
        assert "topsecret999" not in rendered
        assert "***" in rendered

    def test_empty_header_list_disables_filter(self) -> None:
        noop = RedactHeadersFilter(headers=[])
        line = "Authorization: Bearer x"
        assert noop._redact_text(line) == line
        assert noop.filter(logging.LogRecord("t", logging.INFO, __file__, 1, line, None, None))

    def test_settings_wire_the_filter_into_the_console_handler(self) -> None:
        from django.conf import settings

        assert "redact" in settings.LOGGING["filters"]
        assert "redact" in settings.LOGGING["handlers"]["console"]["filters"]
        assert settings.DJANGO_LOG_REDACT_HEADERS == DEFAULT_HEADERS

    def test_configured_logger_redacts_end_to_end(self) -> None:
        """The live Django-configured handler must mask what is written to it."""
        handler = logging.getLogger("apps").handlers[0]
        stream = io.StringIO()
        original = handler.stream
        handler.stream = stream
        try:
            logging.getLogger("apps.envwiring").warning(
                "retry Authorization: Bearer supersecrettoken exhausted"
            )
        finally:
            handler.stream = original

        text = stream.getvalue()
        assert "supersecrettoken" not in text
        assert "***" in text


# ---------------------------------------------------------------------------
# REASONING_FALLBACK_ON_FAILURE — ReasoningProvider
# ---------------------------------------------------------------------------
def _request() -> ReasoningRequest:
    return ReasoningRequest(
        messages=({"role": "user", "content": "why no trade?"},),
        context={"direction": "NO TRADE", "explanation": "Deterministic engine: no setup."},
    )


class TestReasoningFallbackFlag:
    """``ReasoningProvider`` reads settings at construction, so each test wraps
    its own ``override_settings`` context (plain classes cannot be decorated
    with it). The base state: a configured-but-networkless provider with no key.
    """

    @staticmethod
    def _provider(**overrides):
        base = {
            "REASONING_LLM_PROVIDER": "google",
            "REASONING_LLM_API_KEY": "",
            "REASONING_LLM_MODEL": "test-model",
        }
        base.update(overrides)
        return override_settings(**base)

    def test_enabled_shows_deterministic_explanation_and_flags_failure(self) -> None:
        with self._provider(REASONING_FALLBACK_ON_FAILURE=True):
            response = ReasoningProvider().complete(_request())
        assert response.success is False
        assert response.error == "provider_not_configured"
        assert response.content == "Deterministic engine: no setup."

    def test_disabled_withholds_explanation_and_shows_notice(self) -> None:
        with self._provider(REASONING_FALLBACK_ON_FAILURE=False):
            response = ReasoningProvider().complete(_request())
        assert response.success is False
        assert response.error == "provider_not_configured"
        assert response.content == "Explanation unavailable from reasoning provider."
        assert "Deterministic engine" not in response.content

    def test_disabled_on_unreachable_provider_never_invents_text(self) -> None:
        # Phase 11 CP4: the provider now performs real network I/O, so the
        # "unreachable" case is a connection failure. The failure path must
        # still be the honest notice — never invented text.
        import urllib.error

        def _unreachable(request, timeout=None):
            raise urllib.error.URLError(ConnectionRefusedError())

        with (
            self._provider(REASONING_FALLBACK_ON_FAILURE=False, REASONING_LLM_API_KEY="k"),
            unittest.mock.patch("urllib.request.urlopen", _unreachable),
        ):
            response = ReasoningProvider().complete(_request())
        assert response.success is False
        assert response.error == "provider_connection_error"
        assert response.content == "Explanation unavailable from reasoning provider."

    def test_flag_does_not_affect_the_mock_provider(self) -> None:
        with self._provider(REASONING_FALLBACK_ON_FAILURE=False, REASONING_LLM_PROVIDER="mock"):
            response = ReasoningProvider().complete(_request())
        assert response.success is True
        assert response.content == "Deterministic engine: no setup."


# ---------------------------------------------------------------------------
# SENTRY_DSN — apps.core.observability.init_sentry
# ---------------------------------------------------------------------------
class TestSentryWiring:
    def test_disabled_when_dsn_empty(self) -> None:
        assert init_sentry("") is False

    def test_missing_sdk_with_dsn_set_fails_loudly(self, monkeypatch) -> None:
        # ``None`` in sys.modules makes ``import sentry_sdk`` raise ImportError.
        monkeypatch.setitem(sys.modules, "sentry_sdk", None)
        with pytest.raises(ImproperlyConfigured, match="sentry-sdk"):
            init_sentry("https://key@o1.ingest.sentry.io/1")

    def test_initializes_sdk_with_privacy_safe_defaults(self, monkeypatch) -> None:
        calls: dict = {}
        sentry_module = types.ModuleType("sentry_sdk")
        sentry_module.init = lambda **kwargs: calls.update(kwargs)
        integrations_module = types.ModuleType("sentry_sdk.integrations")
        django_module = types.ModuleType("sentry_sdk.integrations.django")

        class DjangoIntegration:  # mirrors the SDK's class name
            pass

        django_module.DjangoIntegration = DjangoIntegration
        integrations_module.django = django_module
        sentry_module.integrations = integrations_module

        monkeypatch.setitem(sys.modules, "sentry_sdk", sentry_module)
        monkeypatch.setitem(sys.modules, "sentry_sdk.integrations", integrations_module)
        monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.django", django_module)

        initialized = init_sentry("https://key@o1.ingest.sentry.io/2", environment="production")

        assert initialized is True
        assert calls["dsn"] == "https://key@o1.ingest.sentry.io/2"
        assert calls["environment"] == "production"
        assert calls["send_default_pii"] is False  # no bodies/cookies leave the host
        assert calls["traces_sample_rate"] == 0.0  # errors only

    def test_prod_settings_initialize_sentry(self) -> None:
        source = (ROOT / "config" / "settings" / "prod.py").read_text(encoding="utf-8")
        assert "init_sentry(SENTRY_DSN" in source
        assert 'environment="production"' in source


# ---------------------------------------------------------------------------
# The scanner itself — full .env <-> code <-> .env.example connectivity
# ---------------------------------------------------------------------------
def test_env_coverage_report_is_clean() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_env_coverage.py"),
            "--root",
            str(ROOT),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        # CPU-bound AST scan over the whole repo. Generous timeout so a busy
        # machine running the full suite cannot turn this into a false failure.
        timeout=300,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[MISSING-REQUIRED] 0" in output, output
    assert "[UNDOCUMENTED] 0" in output, output
    assert "[CONFIG-UNDOCUMENTED] 0" in output, output
    assert "[UNQUOTED-DOLLAR] 0" in output, output


def test_dollar_guard_flags_unquoted_and_accepts_single_quoted(tmp_path) -> None:
    """`$...` values must be single-quoted or compose corrupts them.

    django-environ keeps all three forms literal, but compose interpolates the
    unquoted and double-quoted ones — which silently gave containers a
    different DJANGO_SECRET_KEY than the host until this was found.
    """
    scanner = _load_scanner()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GOOD='has_$literal'\nDOUBLE=\"has_$literal\"\nBARE=has_$literal\nPLAIN=no_dollar_here\n",
        encoding="utf-8",
    )
    assert scanner.unquoted_dollar_keys(env_file) == ["BARE", "DOUBLE"]


def test_env_and_template_carry_no_dead_knobs() -> None:
    scanner = _load_scanner()
    code_keys, _ = scanner.scan_python(ROOT)
    config_keys = scanner.scan_config_files(ROOT)

    for name in (".env", ".env.example"):
        keys = scanner.read_env_keys(ROOT / name)
        dead = sorted(keys - code_keys - config_keys)
        assert dead == [], f"{name} carries keys nothing reads: {dead}"


def test_removed_vision_budget_stays_removed() -> None:
    """The unimplemented cost guard must not creep back into the files."""
    scanner = _load_scanner()
    assert "VISION_DAILY_REQUEST_BUDGET" not in scanner.read_env_keys(ROOT / ".env")
    assert "VISION_DAILY_REQUEST_BUDGET" not in scanner.read_env_keys(ROOT / ".env.example")
