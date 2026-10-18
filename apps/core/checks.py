"""Custom system checks for deployment safety."""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error


def check_production_database(app_configs, **kwargs):  # type: ignore[no-untyped-def]
    """Fail ``manage.py check --deploy`` if SQLite is used outside DEBUG."""
    errors = []
    if not settings.DEBUG:
        engine = settings.DATABASES["default"]["ENGINE"]
        if "sqlite" in engine:
            errors.append(
                Error(
                    "SQLite is not permitted for non-debug deployments.",
                    hint="Configure a PostgreSQL DATABASE_URL.",
                    id="core.E001",
                )
            )
    return errors
