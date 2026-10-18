"""Configuration and deployment-safety tests."""

from __future__ import annotations

from django.conf import settings

from apps.core.checks import check_production_database


def test_settings_are_importable_and_consistent():
    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert settings.LANGUAGE_CODE == "en-us"
    assert settings.USE_TZ is True
    assert "rest_framework" in settings.INSTALLED_APPS
    assert "channels" in settings.INSTALLED_APPS


def test_rest_framework_defaults_require_authentication():
    assert (
        "rest_framework.permissions.IsAuthenticated"
        in settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]
    )


def test_production_check_flags_sqlite(settings):
    settings.DEBUG = False
    settings.DATABASES["default"]["ENGINE"] = "django.db.backends.sqlite3"
    errors = check_production_database(None)
    assert any(error.id == "core.E001" for error in errors)
