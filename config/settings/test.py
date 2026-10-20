"""Test settings.

Fast, hermetic and free of external services: in-memory SQLite, eager Celery,
locmem cache, in-memory channel layer and a cheap password hasher.
"""

from __future__ import annotations

from .base import *
from .base import BASE_DIR

DEBUG = False
ALLOWED_HOSTS = ["*", "testserver"]

# Fast, isolated database.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "ATOMIC_REQUESTS": False,
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# No external broker.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

DJANGO_LOG_FORMATTER = "verbose"
DJANGO_LOG_LEVEL = "WARNING"

# Static files are irrelevant to behaviour tests; drop WhiteNoise so it does not
# warn about a missing STATIC_ROOT.
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m.lower()]

# Temporary media root for upload tests.
MEDIA_ROOT = BASE_DIR / "media" / "test-tmp"

# Private screenshot storage for chart-vision tests (kept out of MEDIA_ROOT and
# the repository's real private storage).
VISION_SCREENSHOT_ROOT = BASE_DIR / "private_media" / "test-tmp"

# Tests are hermetic: never call a real vision provider.
VISION_LLM_PROVIDER = "mock"
VISION_LLM_API_KEY = ""

# Tests are hermetic: never call a real reasoning provider either. CP4 added
# a real HTTP path, so without this override a local .env configured with a
# live provider/key would leak real requests into the unit suite.
REASONING_LLM_PROVIDER = "mock"
REASONING_LLM_API_KEY = ""
REASONING_LLM_MODEL = "mock-reasoning-1"

# Tests are hermetic: no monitors are ever created from a developer's local
# .env. Tests that exercise monitors create them explicitly.
LIVE_SIGNAL_MONITORS = []

# Static files: skip the manifest (and collectstatic) during tests.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

API_DOCS_ENABLED = True
