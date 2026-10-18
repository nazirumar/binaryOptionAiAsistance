"""Smoke tests for infrastructure wiring: ASGI, WSGI, Celery and Channels."""

from __future__ import annotations

from django.conf import settings


def test_asgi_application_builds():
    from config.asgi import application

    assert application is not None


def test_wsgi_application_builds():
    from config.wsgi import application

    assert application is not None


def test_celery_app_is_configured():
    from config.celery import app

    assert app.main == "nazbeen_academy"


def test_channel_layer_configured():
    assert "default" in settings.CHANNEL_LAYERS
    assert settings.CHANNEL_LAYERS["default"]["BACKEND"]


def test_asgi_websocket_router_present():
    from apps.core.routing import websocket_urlpatterns

    assert isinstance(websocket_urlpatterns, list)
