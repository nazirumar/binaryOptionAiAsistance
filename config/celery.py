"""Celery application for Nazbeen Academy Binary Ai Asisstance.

The broker/result backend is derived from ``REDIS_URL``. When no Redis URL is
configured an in-memory broker is used so that development and tests do not
require a running Redis instance.
"""

from __future__ import annotations

import os

from celery import Celery
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("nazbeen_academy")

# Read Celery-related settings from Django's configuration using the
# ``CELERY_`` namespace.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Discover ``tasks.py`` modules inside installed apps.
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> str:  # pragma: no cover - operational helper
    """Trivial task used to verify the broker/worker wiring."""
    return f"debug task executed by {self.request.hostname}"
