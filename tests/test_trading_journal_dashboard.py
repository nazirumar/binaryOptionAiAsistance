# tests/test_trading_journal_dashboard.py
"""Tests for the trading journal and the Phase 9 dashboard (API + pages)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.trading_journal.models import JournalTrade
from apps.trading_journal.services.journal_performance import JournalPerformance
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _ts(hour: int) -> datetime:
    return datetime(2026, 1, 1, hour, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Journal model / performance calculations
# ---------------------------------------------------------------------------
def test_journal_trade_compute_profit_loss():
    trade = JournalTrade(
        instrument="EUR/USD",
        direction="call",
        entry_timestamp=_ts(12),
        stake=Decimal("100"),
        payout_percent=Decimal("80"),
        result="win",
    )
    assert trade.compute_profit_loss() == Decimal("80.00")

    trade.result = "loss"
    assert trade.compute_profit_loss() == Decimal("-100.00")

    trade.result = "tie"
    assert trade.compute_profit_loss() == Decimal("0.00")

    trade.result = "pending"
    assert trade.compute_profit_loss() == Decimal("0.00")


def test_journal_trade_save_derives_profit_loss():
    trade = JournalTrade.objects.create(
        owner=UserFactory(username="derive"),
        instrument="EUR/USD",
        direction="call",
        entry_timestamp=_ts(12),
        stake=Decimal("50"),
        payout_percent=Decimal("90"),
        result="win",
    )
    assert trade.profit_loss == Decimal("45.00")


def test_journal_performance_totals_win_rate_and_drawdown():
    user = UserFactory(username="perf")
    trades = [
        JournalTrade(
            owner=user,
            instrument="EUR/USD",
            direction="call",
            entry_timestamp=_ts(12),
            stake=Decimal("100"),
            payout_percent=Decimal("80"),
            result="win",
        ),
        JournalTrade(
            owner=user,
            instrument="EUR/USD",
            direction="put",
            entry_timestamp=_ts(13),
            stake=Decimal("100"),
            result="loss",
        ),
        JournalTrade(
            owner=user,
            instrument="EUR/USD",
            direction="put",
            entry_timestamp=_ts(14),
            stake=Decimal("100"),
            result="loss",
        ),
        JournalTrade(
            owner=user,
            instrument="EUR/USD",
            direction="call",
            entry_timestamp=_ts(15),
            stake=Decimal("100"),
            payout_percent=Decimal("80"),
            result="win",
        ),
        JournalTrade(
            owner=user,
            instrument="EUR/USD",
            direction="call",
            entry_timestamp=_ts(16),
            stake=Decimal("100"),
            result="tie",
        ),
        JournalTrade(
            owner=user,
            instrument="EUR/USD",
            direction="call",
            entry_timestamp=_ts(17),
            stake=Decimal("100"),
            result="pending",
        ),
    ]
    # NOTE: individual saves (not bulk_create) so JournalTrade.save() derives
    # profit_loss from stake/payout/result.
    for trade in trades:
        trade.save()

    summary = JournalPerformance(JournalTrade.objects.filter(owner=user)).summary()
    assert summary.total_recorded == 6
    assert summary.settled == 5
    assert summary.pending == 1
    assert summary.wins == 2
    assert summary.losses == 2
    assert summary.ties == 1
    assert summary.decided == 4
    assert summary.win_rate == 0.5
    # net = 80 - 100 - 100 + 80 + 0 = -40
    assert summary.net_profit_loss == Decimal("-40.00")
    # equity peaks at 80, trough at -120 -> drawdown 200
    assert summary.max_drawdown == Decimal("200.00")
    assert summary.max_losing_streak == 2
    assert summary.max_winning_streak == 1


def test_journal_performance_no_settled_data_is_insufficient():
    summary = JournalPerformance([]).summary()
    assert summary.has_settled_data is False
    assert summary.win_rate is None
    payload = summary.to_dict()
    assert payload["insufficient_data"] is True
    assert payload["win_rate_display"] == "Insufficient validated data."


def test_journal_performance_never_blends_trade_types():
    user = UserFactory(username="seg")
    JournalTrade.objects.create(
        owner=user,
        instrument="EUR/USD",
        direction="call",
        entry_timestamp=_ts(12),
        stake=Decimal("100"),
        payout_percent=Decimal("80"),
        result="win",
        trade_type="real",
    )
    JournalTrade.objects.create(
        owner=user,
        instrument="EUR/USD",
        direction="call",
        entry_timestamp=_ts(13),
        stake=Decimal("100"),
        result="loss",
        trade_type="backtest",
    )
    segments = JournalPerformance(JournalTrade.objects.filter(owner=user)).segmented_summary()
    assert set(segments) == {"real", "demo", "backtest", "hypothetical"}
    assert segments["real"].net_profit_loss == Decimal("80.00")
    assert segments["backtest"].net_profit_loss == Decimal("-100.00")
    assert segments["demo"].total_recorded == 0
    assert segments["hypothetical"].total_recorded == 0


# ---------------------------------------------------------------------------
# Journal API (authenticated, owner-scoped)
# ---------------------------------------------------------------------------
def test_journal_api_unauthenticated_returns_401():
    client = APIClient()
    resp = client.get(reverse("trading_journal:trade-list"))
    assert resp.status_code in (401, 403)


def test_journal_api_create_ownership_and_delete():
    owner = UserFactory(username="journal-owner")
    intruder = UserFactory(username="journal-intruder")

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("trading_journal:trade-list")
    resp = client.post(
        url,
        {
            "instrument": "EUR/USD",
            "direction": "call",
            "entry_timestamp": "2026-01-01T12:00:00Z",
            "stake": "100.00",
            "trade_type": "demo",
            "result": "pending",
        },
        format="json",
    )
    assert resp.status_code == 201
    trade_id = resp.data["id"]

    # The owner sees their own trade.
    assert client.get(reverse("trading_journal:trade-detail", args=[trade_id])).status_code == 200

    # Another user cannot read or delete it.
    intruder_client = APIClient()
    intruder_client.force_authenticate(user=intruder)
    assert (
        intruder_client.get(reverse("trading_journal:trade-detail", args=[trade_id])).status_code
        == 404
    )
    assert (
        intruder_client.delete(reverse("trading_journal:trade-detail", args=[trade_id])).status_code
        == 404
    )

    # The owner can delete it.
    assert (
        client.delete(reverse("trading_journal:trade-detail", args=[trade_id])).status_code == 204
    )


def test_journal_api_performance_is_segmented():
    user = UserFactory(username="perf-api")
    JournalTrade.objects.create(
        owner=user,
        instrument="EUR/USD",
        direction="call",
        entry_timestamp=_ts(12),
        stake=Decimal("100"),
        payout_percent=Decimal("80"),
        result="win",
        trade_type="real",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get(reverse("trading_journal:performance"))
    assert resp.status_code == 200
    segments = resp.data["segments"]
    assert segments["real"]["wins"] == 1
    assert segments["demo"]["total_recorded"] == 0
    # A single trade_type request returns only that summary.
    resp = client.get(reverse("trading_journal:performance"), {"trade_type": "real"})
    assert resp.data["trade_type"] == "real"
    assert resp.data["summary"]["wins"] == 1


def test_journal_api_rejects_expiry_before_entry():
    user = UserFactory(username="expiry")
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        reverse("trading_journal:trade-list"),
        {
            "instrument": "EUR/USD",
            "direction": "call",
            "entry_timestamp": "2026-01-01T12:00:00Z",
            "expiration_timestamp": "2026-01-01T11:00:00Z",
            "stake": "10.00",
            "trade_type": "demo",
            "result": "pending",
        },
        format="json",
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Dashboard API (authenticated, owner-scoped)
# ---------------------------------------------------------------------------
def test_dashboard_api_overview_requires_auth():
    client = APIClient()
    resp = client.get(reverse("dashboard_api:overview"))
    assert resp.status_code in (401, 403)


def test_dashboard_api_overview_returns_real_counts():
    user = UserFactory(username="overview-user")
    JournalTrade.objects.create(
        owner=user,
        instrument="EUR/USD",
        direction="call",
        entry_timestamp=_ts(12),
        stake=Decimal("100"),
        payout_percent=Decimal("80"),
        result="win",
        trade_type="real",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get(reverse("dashboard_api:overview"))
    assert resp.status_code == 200
    assert resp.data["counts"]["journal_trades"] == 1
    assert resp.data["decisions"] == {"up": 0, "down": 0, "no_trade": 0}
    # No validated outcomes yet beyond the one settled real trade, which exists.
    assert resp.data["performance"]["has_valid_outcomes"] is True


def test_dashboard_api_overview_insufficient_data_message():
    user = UserFactory(username="no-outcomes")
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get(reverse("dashboard_api:overview"))
    assert resp.status_code == 200
    assert resp.data["performance"]["has_valid_outcomes"] is False
    assert resp.data["performance"]["message"] == "Insufficient validated data."


def test_dashboard_api_analytics_requires_auth():
    client = APIClient()
    assert client.get(reverse("dashboard_api:analytics")).status_code in (401, 403)


def test_dashboard_api_market_health_requires_auth():
    client = APIClient()
    assert client.get(reverse("dashboard_api:market-health")).status_code in (401, 403)


def test_dashboard_api_reports_export_scoped_to_owner():
    user = UserFactory(username="exporter")
    JournalTrade.objects.create(
        owner=user,
        instrument="EUR/USD",
        direction="call",
        entry_timestamp=_ts(12),
        stake=Decimal("100"),
        payout_percent=Decimal("80"),
        result="win",
        trade_type="real",
        notes="mine",
    )
    other = UserFactory(username="export-other")
    JournalTrade.objects.create(
        owner=other,
        instrument="GBP/USD",
        direction="put",
        entry_timestamp=_ts(12),
        stake=Decimal("100"),
        result="loss",
        trade_type="real",
        notes="secret",
    )

    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get(reverse("dashboard_api:reports"), {"kind": "journal_csv"})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "EUR/USD" in body
    assert "mine" in body
    # Another user's data must never leak into this export.
    assert "GBP/USD" not in body
    assert "secret" not in body


def test_dashboard_api_reports_pdf_is_valid():
    user = UserFactory(username="pdf-user")
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get(reverse("dashboard_api:reports"), {"kind": "performance_pdf"})
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-1.4")
    assert resp.content.rstrip().endswith(b"%%EOF")


def test_dashboard_api_reports_requires_auth():
    client = APIClient()
    assert client.get(reverse("dashboard_api:reports")).status_code in (401, 403)


# ---------------------------------------------------------------------------
# Dashboard pages (session auth -> redirect anonymous users to login)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url_name",
    [
        "dashboard:overview",
        "dashboard:analyses",
        "dashboard:analytics",
        "dashboard:probability",
        "dashboard:market-health",
        "dashboard:backtests",
        "dashboard:knowledge",
        "dashboard:settings",
        "dashboard:journal",
        "dashboard:journal-create",
        "dashboard:journal-performance",
        "dashboard:reports",
        "dashboard:export-journal-csv",
        "dashboard:export-analyses-csv",
        "dashboard:export-performance-pdf",
    ],
)
def test_dashboard_pages_redirect_anonymous_users(client, url_name):
    resp = client.get(reverse(url_name))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


def test_dashboard_page_renders_when_logged_in(client):
    user = UserFactory(username="page-user")
    client.force_login(user)
    for url_name in ("dashboard:overview", "dashboard:journal", "dashboard:analytics"):
        resp = client.get(reverse(url_name))
        assert resp.status_code == 200


def test_dashboard_export_downloads_for_owner(client):
    user = UserFactory(username="csv-owner")
    JournalTrade.objects.create(
        owner=user,
        instrument="EUR/USD",
        direction="call",
        entry_timestamp=_ts(12),
        stake=Decimal("100"),
        result="pending",
        trade_type="demo",
    )
    client.force_login(user)
    resp = client.get(reverse("dashboard:export-journal-csv"))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv"
    assert "EUR/USD" in resp.content.decode()


def test_dashboard_ownership_isolation(client):
    user = UserFactory(username="iso-owner")
    other = UserFactory(username="iso-other")
    trade = JournalTrade.objects.create(
        owner=user,
        instrument="EUR/USD",
        direction="call",
        entry_timestamp=_ts(12),
        stake=Decimal("100"),
        result="pending",
        trade_type="demo",
    )
    client.force_login(other)
    resp = client.get(reverse("dashboard:journal-edit", args=[trade.pk]))
    assert resp.status_code == 404
