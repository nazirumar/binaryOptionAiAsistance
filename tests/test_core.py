"""Structured logging, middleware and Celery wiring tests."""

from __future__ import annotations

import json
import logging

import pytest

from apps.core.logging import JsonFormatter, RequestIDFilter, set_request_id
from apps.core.tasks import health_probe


def _make_record(message: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(
        name="apps.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_json_formatter_emits_valid_json_with_request_id():
    set_request_id("req-123")
    try:
        record = _make_record("analysis.start")
        record.request_id = "req-123"  # normally set by the filter
        payload = json.loads(JsonFormatter().format(record))
    finally:
        set_request_id(None)

    assert payload["message"] == "analysis.start"
    assert payload["level"] == "INFO"
    assert payload["request_id"] == "req-123"
    assert "timestamp" in payload


def test_request_id_filter_defaults_to_dash():
    record = _make_record()
    RequestIDFilter().filter(record)
    assert record.request_id == "-"


@pytest.mark.django_db
def test_request_id_middleware_generates_header(client):
    response = client.get("/healthz/")
    assert response.headers["X-Request-ID"]


@pytest.mark.django_db
def test_request_id_middleware_echoes_inbound_header(client):
    response = client.get("/healthz/", headers={"X-Request-ID": "abc-999"})
    assert response.headers["X-Request-ID"] == "abc-999"


def test_celery_task_runs_eagerly(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    result = health_probe.delay().get()
    assert result == {"status": "ok", "task": "core.health_probe"}
