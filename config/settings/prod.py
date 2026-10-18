"""Production settings.

Hardening is applied here. ``DJANGO_SECRET_KEY``, ``DJANGO_ALLOWED_HOSTS``,
``DJANGO_CSRF_TRUSTED_ORIGINS`` and a PostgreSQL ``DATABASE_URL`` must be
supplied through the environment; the application refuses to start with an
insecure configuration.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from apps.core.observability import init_sentry

from .base import *
from .base import REDIS_URL, env

DEBUG = False
DJANGO_LOG_FORMATTER = "json"
API_DOCS_ENABLED = env.bool("API_DOCS_ENABLED", default=False)

# --- Mandatory production configuration ----------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", default=None)
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production.")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
if not ALLOWED_HOSTS or ALLOWED_HOSTS == ["localhost", "127.0.0.1"]:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be set in production.")

DATABASE_URL = env("DATABASE_URL", default=None)
if not DATABASE_URL:
    raise ImproperlyConfigured("DATABASE_URL (PostgreSQL) must be set in production.")

# --- HTTPS / transport security ------------------------------------------
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Redis is required for Celery/Channels in production ------------------
if not REDIS_URL:
    raise ImproperlyConfigured("REDIS_URL must be set in production.")

# Static files served by WhiteNoise.
WHITENOISE_MAX_AGE = 60 * 60 * 24 * 30

# Switch logging to the machine-readable JSON formatter.
LOGGING["handlers"]["console"]["formatter"] = "json"  # type: ignore[name-defined]

# --- Optional error tracking ------------------------------------------------
# An empty SENTRY_DSN (the documented default) keeps Sentry off. A configured
# DSN requires sentry-sdk from requirements/prod.txt; otherwise the app refuses
# to boot rather than silently losing production error reports.
SENTRY_DSN = env("SENTRY_DSN", default="")
init_sentry(SENTRY_DSN, environment="production")
