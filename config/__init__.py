"""Django project configuration package.

Exposes the Celery application so that it is loaded when Django starts,
enabling ``@shared_task`` usage across the codebase.
"""

from __future__ import annotations

from .celery import app as celery_app

__all__ = ("celery_app",)
