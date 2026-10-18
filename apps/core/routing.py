"""WebSocket routing for Django Channels.

Consumers are added in later phases (analysis progress streaming). The empty
list keeps the ASGI router valid and testable today.
"""

from __future__ import annotations

from typing import Any

websocket_urlpatterns: list[Any] = []
