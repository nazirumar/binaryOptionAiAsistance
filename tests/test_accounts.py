"""Custom user model and authentication flow tests."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from tests.factories import UserFactory

User = get_user_model()


@pytest.mark.django_db
def test_user_str_prefers_display_name():
    user = UserFactory(display_name="Naz Analyst")
    assert str(user) == "Naz Analyst"
    assert user.name == "Naz Analyst"


@pytest.mark.django_db
def test_user_defaults():
    user = UserFactory()
    assert user.timezone == "UTC"
    assert user.preferred_theme == "dark"
    assert user.is_active is True


@pytest.mark.django_db
def test_signup_creates_and_logs_in_user(client):
    response = client.post(
        "/accounts/signup/",
        {
            "username": "newanalyst",
            "email": "new@example.com",
            "password1": "a-very-strong-pass-9876",
            "password2": "a-very-strong-pass-9876",
        },
    )
    assert response.status_code == 302
    assert User.objects.filter(username="newanalyst").exists()
    # Session should now be authenticated.
    assert client.session["_auth_user_id"] == str(User.objects.get(username="newanalyst").pk)


@pytest.mark.django_db
def test_login_with_valid_credentials(client):
    UserFactory(username="trader1")
    ok = client.login(username="trader1", password="test-pass-1234")
    assert ok is True


@pytest.mark.django_db
def test_login_page_renders(client):
    response = client.get("/accounts/login/")
    assert response.status_code == 200
    assert b"Sign in" in response.content
