"""Development settings.

Optimised for local iteration: verbose logging, permissive hosts and the
Django debug toolbar-friendly defaults. Never use these settings in production.
"""

from __future__ import annotations

from .base import *
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Local development should not require HTTPS.
SECURE_SSL_REDIRECT = False

DJANGO_LOG_FORMATTER = "verbose"

# Enable the browsable API and schema docs during development.
API_DOCS_ENABLED = True

# In development, run tasks synchronously unless a broker is configured.
CELERY_TASK_ALWAYS_EAGER = env.bool(
    "CELERY_TASK_ALWAYS_EAGER", default=not bool(env("REDIS_URL", default=""))
)

# Email to console.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

INTERNAL_IPS = ["127.0.0.1"]

# Development serves static files without a collectstatic manifest.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
