"""Structured logging helpers.

Provides a request-correlated context variable plus console (human readable)
and JSON (machine readable) formatters wired into Django's ``LOGGING`` config.
No secrets or market data payloads should ever be logged here.
"""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

#: Correlation id shared by every log record emitted while handling a request.
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

#: LogRecord attributes that are part of the logging protocol, never extras.
_RESERVED_RECORD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "request_id",
        "message",
        "asctime",
        "level",
        "logger",
        "timestamp",
    }
)


def set_request_id(value: str | None) -> None:
    """Set the current request id for the active context."""
    request_id_ctx.set(value)


def get_request_id() -> str | None:
    """Return the request id for the active context, if any."""
    return request_id_ctx.get()


class RequestIDFilter(logging.Filter):
    """Attach the active request id to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    """Collect structured extras attached to a record via ``logger.info(..., extra=...)``."""
    return {k: v for k, v in record.__dict__.items() if k not in _RESERVED_RECORD_ATTRS}


class RedactHeadersFilter(logging.Filter):
    """Mask sensitive HTTP header values in log messages and structured extras.

    Header names come from ``DJANGO_LOG_REDACT_HEADERS`` (comma-separated,
    default ``Authorization,Cookie,X-API-Key``) and are wired into the
    ``console`` handler in ``LOGGING``, so every formatter (verbose and JSON)
    emits already-redacted text.

    Two leak shapes are covered:

    * ``Header: value`` / ``Header=value`` occurrences in the rendered message,
      wherever they appear (``Authorization: Bearer ey...`` -> ``***``).
    * Structured extras: dict keys matching a header name are masked outright,
      nested dicts/lists are walked, and any remaining string is scanned with
      the same pattern.

    Scope: records only. Exception tracebacks are rendered *after* filters run,
    so secrets must still never be placed into exception messages.
    """

    MASK = "***"

    def __init__(self, headers: list[str] | str | None = None) -> None:
        super().__init__()
        if headers is None:
            # Imported lazily so the class is usable before settings configure.
            from django.conf import settings

            headers = list(getattr(settings, "DJANGO_LOG_REDACT_HEADERS", []))
        elif isinstance(headers, str):
            headers = [part.strip() for part in headers.split(",") if part.strip()]
        self.headers = [name for name in headers if name]
        self._pattern = self._build_pattern(self.headers)

    @staticmethod
    def _build_pattern(names: list[str]) -> re.Pattern[str] | None:
        if not names:
            return None
        alternatives = "|".join(re.escape(name) for name in names)
        # Fail-closed value capture:
        #   * optional prefix, so Django's META style ``HTTP_AUTHORIZATION``
        #     and ``Set-Cookie`` match too (``_``/``-`` are word chars, so a
        #     plain \b before the name would miss them);
        #   * optional closing quote, so ``'Authorization': 'Bearer ...`` from
        #     dict/list reprs matches;
        #   * the value runs to end-of-line, stopping only before the *next*
        #     ``header:``-shaped token, so ``Authorization: Bearer <jwt>`` is
        #     masked in full while neighbouring labelled fields survive.
        return re.compile(
            rf"(?i)([A-Za-z0-9_-]*(?:{alternatives}))['\"]?(\s*[:=]\s*)"
            rf"((?:(?!\s+['\"]?[A-Za-z0-9_-]+['\"]?\s*[:=])[^\r\n])+)"
        )

    def _redact_text(self, text: str) -> str:
        if not self._pattern:
            return text
        return self._pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{self.MASK}", text)

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact_text(value)
        if isinstance(value, dict):
            lowered = {name.lower() for name in self.headers}
            return {
                key: (
                    self.MASK
                    if isinstance(key, str) and key.lower() in lowered
                    else self._redact_value(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self._redact_value(item) for item in value]
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.headers:
            return True

        message = record.getMessage()
        redacted = self._redact_text(message)
        if redacted != message:
            record.msg = redacted
            record.args = None  # already rendered; avoid re-interpolation

        for key, value in list(record.__dict__.items()):
            if key in _RESERVED_RECORD_ATTRS or not isinstance(value, (str, dict, list, tuple)):
                continue
            new_value = self._redact_value(value)
            if new_value != value:
                record.__dict__[key] = new_value
        return True


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter that still appends structured extras."""

    default_time_format = "%Y-%m-%dT%H:%M:%S%z"

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"[{self.formatTime(record, self.default_time_format)}] "
            f"{record.levelname:<8} {record.name} rid={getattr(record, 'request_id', '-')} "
            f"{record.getMessage()}"
        )
        extras = _extra_fields(record)
        if extras:
            base += " " + json.dumps(extras, default=str)
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


class JsonFormatter(logging.Formatter):
    """One JSON object per line, suitable for log aggregation pipelines."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
