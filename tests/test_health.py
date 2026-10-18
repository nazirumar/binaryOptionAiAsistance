"""Health endpoint tests (plain Django and DRF)."""

from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_django_health_endpoint_ok(client):
    response = client.get(reverse("healthz"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["version"]


@pytest.mark.django_db
def test_django_health_requires_no_auth(client):
    # Anonymous access must succeed (probes are unauthenticated).
    assert client.get(reverse("healthz")).status_code == 200


@pytest.mark.django_db
def test_api_health_endpoint_ok(client):
    response = client.get("/api/health/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["application"] == "nazbeen-academy-binary-ai"


def test_health_response_has_request_id(client):
    response = client.get(reverse("healthz"))
    assert response.headers.get("X-Request-ID")
