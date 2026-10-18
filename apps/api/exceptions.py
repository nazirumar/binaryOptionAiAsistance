"""Consistent API error envelope with request correlation."""

from __future__ import annotations

from typing import Any

from rest_framework.response import Response
from rest_framework.views import exception_handler


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Wrap DRF's default handler to add a request id to error responses."""
    response = exception_handler(exc, context)
    if response is None:
        return None

    request = context.get("request")
    request_id = getattr(request, "request_id", None) if request is not None else None

    if isinstance(response.data, dict):
        data = dict(response.data)
        data.setdefault("detail", "Request failed.")
        data["request_id"] = request_id
        response.data = data
    else:
        response.data = {
            "detail": response.data,
            "request_id": request_id,
        }
    return response
