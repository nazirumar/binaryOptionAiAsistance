"""Page and theme tests."""

from __future__ import annotations

import pytest

from tests.factories import UserFactory


@pytest.mark.django_db
def test_home_page_renders_for_anonymous(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Nazbeen Academy" in response.content


@pytest.mark.django_db
def test_home_redirects_authenticated_user_to_dashboard(client):
    client.force_login(UserFactory())
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == "/dashboard/"


@pytest.mark.django_db
def test_dashboard_requires_login(client):
    response = client.get("/dashboard/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_dashboard_renders_for_user(client):
    client.force_login(UserFactory(display_name="Dashboard Tester"))
    response = client.get("/dashboard/")
    assert response.status_code == 200
    assert b"Dashboard Tester" in response.content


@pytest.mark.django_db
def test_status_fragment_renders(client):
    client.force_login(UserFactory())
    response = client.get("/dashboard/partials/status/")
    assert response.status_code == 200
    assert b"System status" in response.content


@pytest.mark.django_db
def test_status_fragment_reports_the_real_vision_state(client):
    """Test settings use the offline mock — the card must say so, honestly."""
    client.force_login(UserFactory())
    response = client.get("/dashboard/partials/status/")
    assert b"Offline mock" in response.content
    assert b"no live model configured" in response.content
    assert b"Not configured (Phase 3)" not in response.content


@pytest.mark.django_db
def test_status_fragment_shows_a_configured_provider_without_leaking_the_key(client):
    from django.test import override_settings

    client.force_login(UserFactory())
    with override_settings(
        VISION_LLM_PROVIDER="openai",
        VISION_LLM_API_KEY="sk-super-secret-key",
        VISION_LLM_MODEL="gpt-4o-mini",
    ):
        response = client.get("/dashboard/partials/status/")
    assert b"openai" in response.content and b"gpt-4o-mini" in response.content
    assert b"sk-super-secret-key" not in response.content  # never rendered


@pytest.mark.django_db
def test_status_fragment_flags_a_provider_with_missing_credentials(client):
    from django.test import override_settings

    client.force_login(UserFactory())
    with override_settings(
        VISION_LLM_PROVIDER="openai",
        VISION_LLM_API_KEY="",
        VISION_LLM_MODEL="",
    ):
        response = client.get("/dashboard/partials/status/")
    assert b"not configured (missing API key, model)" in response.content


@pytest.mark.django_db
def test_dashboard_roadmap_is_up_to_date(client):
    client.force_login(UserFactory())
    response = client.get("/dashboard/")
    content = response.content
    assert response.status_code == 200
    # Phase 10 shipped; Phase 11 (integration remediation) shipped too.
    assert b"Critical integration remediation" in content
    assert b"Planned" not in content


@pytest.mark.django_db
def test_mt5_dashboard_requires_login(client):
    response = client.get("/dashboard/mt5/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_mt5_dashboard_renders_with_market_data(client):
    from django.utils import timezone

    from apps.market_data.models import MT5ConnectionProfile
    from apps.market_data.services.tick_service import persist_ticks
    from tests.marketdata_fakes import make_symbol, make_tick

    user = UserFactory()
    client.force_login(user)
    MT5ConnectionProfile.objects.create(
        name="acme", owner=user, login=987654321, server="Acme-Demo", broker="Acme"
    )
    symbol = make_symbol(canonical="EURUSD", broker_symbol="EURUSD")
    persist_ticks(symbol, [make_tick(timezone.now())])

    response = client.get("/dashboard/mt5/")
    assert response.status_code == 200
    content = response.content
    assert b"MT5 market data" in content
    assert b"EURUSD" in content
    assert b"*******21" in content
    assert b"987654321" not in content


@pytest.mark.django_db
def test_settings_page_renders_for_user(client):
    client.force_login(UserFactory())
    response = client.get("/dashboard/settings/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_settings_profile_get_redirects_to_settings_page(client):
    """The profile endpoint is a form target, not a page: a browser GET is
    redirected instead of answered with a raw 405."""
    client.force_login(UserFactory())
    response = client.get("/dashboard/settings/profile/")
    assert response.status_code == 302
    assert response.url == "/dashboard/settings/"


@pytest.mark.django_db
def test_settings_profile_post_saves_and_redirects(client):
    from apps.accounts.models import UserPreference

    user = UserFactory(display_name="Old Name")
    client.force_login(user)
    UserPreference.objects.get_or_create(user=user)

    response = client.post(
        "/dashboard/settings/profile/",
        {
            "display_name": "New Name",
            "email": user.email,
            "timezone": "UTC",
            "preferred_theme": "dark",
            "data_retention_days": 0,
        },
    )
    assert response.status_code == 302
    assert response.url == "/dashboard/settings/"
    user.refresh_from_db()
    assert user.display_name == "New Name"


@pytest.mark.django_db
def test_theme_cookie_controls_initial_theme(client):
    default = client.get("/")
    assert b'class="dark"' in default.content  # default theme is dark

    client.cookies["theme"] = "light"
    light = client.get("/")
    assert b'class="dark"' not in light.content
