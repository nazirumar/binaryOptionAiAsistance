"""ASGI entrypoint for Nazbeen Academy Binary Ai Asisstance.

Routes HTTP traffic to Django and WebSocket traffic through Django Channels.
WebSocket consumers are registered in ``apps.core.routing`` and are populated
in later phases (e.g. analysis progress streaming).
"""

from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

# The Django ASGI application must be created before importing modules that
# touch the ORM (the apps registry must be ready).
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from apps.core.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
