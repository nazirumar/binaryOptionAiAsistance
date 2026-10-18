"""API authentication and permission tests."""

from __future__ import annotations

import json

import pytest

from tests.factories import UserFactory


@pytest.mark.django_db
def test_me_requires_authentication(client):
    response = client.get("/api/me/")
    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_me_returns_authenticated_user(client):
    user = UserFactory(username="apiuser")
    client.force_login(user)
    response = client.get("/api/me/")
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "apiuser"
    assert "password" not in json.dumps(body).lower()


@pytest.mark.django_db
def test_error_response_includes_request_id(client):
    response = client.get("/api/me/")
    body = response.json()
    assert body["request_id"]
