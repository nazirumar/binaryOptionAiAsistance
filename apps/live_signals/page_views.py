# live_signals/page_views.py
"""Server-rendered Live Signals pages (Phase 15).

Session-authenticated and owner-scoped, matching the rest of the dashboard.
Every view reads real persisted rows through the read-model services; nothing
here fabricates a price, signal or statistic.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.live_signals.constants import (
    MONITOR_DISCLAIMER,
    MONITORABLE_TIMEFRAMES,
    SIGNALS_DISCLAIMER,
    OutcomeStatus,
    SignalCategory,
    SignalStatus,
)
from apps.live_signals.models import (
    UserMonitor,
    UserMonitorSettings,
)
from apps.live_signals.services.alerts import (
    mark_alert_read,
    unread_alerts_for,
)
from apps.live_signals.services.dashboard import (
    SignalFilters,
    build_dashboard,
    build_outcomes,
    signal_detail,
)


#: Poll interval for the live fragment (HTMX fallback to Channels).
def _poll_seconds() -> int:
    from django.conf import settings

    return int(getattr(settings, "LIVE_SIGNAL_POLL_SECONDS", 15))


def _filters_from_request(request: HttpRequest) -> SignalFilters:
    params = request.GET
    return SignalFilters(
        strategy=params.get("strategy", ""),
        instrument=params.get("instrument", ""),
        timeframe=params.get("timeframe", ""),
        category=params.get("category", ""),
        status=params.get("status", ""),
        direction=params.get("direction", ""),
        outcome=params.get("outcome", ""),
    )


def _signal_querystring(request: HttpRequest) -> str:
    """Preserve filters across HTMX polling swaps."""
    return request.GET.urlencode()


@login_required
@require_GET
def live_signals(request: HttpRequest) -> HttpResponse:
    """The Live Signals dashboard."""
    context = {
        "dashboard": build_dashboard(request.user, _filters_from_request(request)),
        "poll_seconds": _poll_seconds(),
        "disclaimer": SIGNALS_DISCLAIMER,
        "monitor_disclaimer": MONITOR_DISCLAIMER,
        "categories": SignalCategory.CHOICES,
        "statuses": SignalStatus.CHOICES,
        "outcomes": OutcomeStatus.CHOICES,
        "querystring": _signal_querystring(request),
    }
    return render(request, "dashboard/live_signals.html", context)


@login_required
@require_GET
def live_signals_feed(request: HttpRequest) -> HttpResponse:
    """HTMX fragment: the signal feed + counters, polled without a full reload."""
    context = {
        "dashboard": build_dashboard(request.user, _filters_from_request(request)),
        "poll_seconds": _poll_seconds(),
        "querystring": _signal_querystring(request),
    }
    return render(request, "dashboard/partials/live_signals_feed.html", context)


@login_required
@require_GET
def live_signal_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """HTMX fragment: one signal's full evidence panel (owner-scoped)."""
    signal = signal_detail(request.user, pk)
    if signal is None:
        raise Http404("No such signal")
    return render(
        request,
        "dashboard/partials/live_signal_detail.html",
        {"signal": signal},
    )


@login_required
@require_GET
def live_signals_outcomes(request: HttpRequest) -> HttpResponse:
    """Paper-outcome metrics page (recognition vs directional kept separate)."""
    context = {
        "outcomes": build_outcomes(request.user),
        "disclaimer": SIGNALS_DISCLAIMER,
    }
    return render(request, "dashboard/live_signals_outcomes.html", context)


@login_required
def live_signals_settings(request: HttpRequest) -> HttpResponse:
    """Owner-scoped monitoring + alert preferences."""
    settings_obj, _ = UserMonitorSettings.objects.get_or_create(user=request.user)

    if request.method == "POST":
        action = request.POST.get("action", "save")

        if action == "add_monitor":
            _add_user_monitor(request)
            return redirect("dashboard:live-signals-settings")

        if action == "remove_monitor":
            monitor_id = request.POST.get("monitor_id") or ""
            if monitor_id.isdigit():
                UserMonitor.objects.filter(
                    user=request.user, pk=int(monitor_id)
                ).delete()
                messages.success(request, "Monitored instrument removed.")
            return redirect("dashboard:live-signals-settings")

        instruments: list[str] = []
        for raw in request.POST.getlist("instruments"):
            instruments.extend(v.strip() for v in raw.split(",") if v.strip())
        timeframes = [
            v
            for v in request.POST.getlist("timeframes")
            if v in MONITORABLE_TIMEFRAMES
        ]
        enabled_strategies = [
            v.strip() for v in request.POST.getlist("enabled_strategies") if v.strip()
        ]
        settings_obj.instruments = instruments
        settings_obj.timeframes = timeframes
        settings_obj.enabled_strategies = enabled_strategies
        settings_obj.alerts_enabled = "alerts_enabled" in request.POST
        settings_obj.browser_notifications = "browser_notifications" in request.POST
        settings_obj.show_experimental = "show_experimental" in request.POST
        settings_obj.only_approved = "only_approved" in request.POST
        settings_obj.save()
        messages.success(request, "Live-signal preferences saved.")
        return redirect("dashboard:live-signals-settings")

    from apps.book_strategies.models import BookStrategy

    strategies = list(
        BookStrategy.objects.filter(recognition_enabled=True).order_by("key")
    )
    user_monitors = list(
        UserMonitor.objects.filter(user=request.user).order_by(
            "canonical_instrument", "timeframe"
        )
    )
    context = {
        "settings_obj": settings_obj,
        "timeframes": MONITORABLE_TIMEFRAMES,
        "user_monitors": user_monitors,
        "strategies": strategies,
        "disclaimer": MONITOR_DISCLAIMER,
    }
    return render(request, "dashboard/live_signals_settings.html", context)


def _add_user_monitor(request: HttpRequest) -> None:
    """Validate and persist one user-added instrument/timeframe watch."""
    instrument = (request.POST.get("monitor_instrument") or "").strip().upper()
    timeframe = (request.POST.get("monitor_timeframe") or "").strip().upper()
    market_type = (request.POST.get("monitor_market_type") or "regular").strip().lower()

    if not instrument:
        messages.error(request, "Enter an instrument code (e.g. EURUSD).")
        return
    if timeframe not in MONITORABLE_TIMEFRAMES:
        messages.error(
            request,
            "Choose a supported timeframe: " + ", ".join(MONITORABLE_TIMEFRAMES) + ".",
        )
        return
    if market_type not in ("regular", "otc"):
        messages.error(request, "Market type must be regular or otc.")
        return

    _, created = UserMonitor.objects.get_or_create(
        user=request.user,
        canonical_instrument=instrument,
        timeframe=timeframe,
        market_type=market_type,
    )
    if created:
        messages.success(request, f"Now monitoring {instrument} {timeframe} ({market_type}).")
    else:
        messages.info(request, f"{instrument} {timeframe} ({market_type}) is already monitored.")


@login_required
@require_POST
def live_signal_alert_read(request: HttpRequest, pk: int) -> HttpResponse:
    """Mark one of the user's own alerts read (owner-scoped)."""
    ok = mark_alert_read(request.user, pk)
    if request.headers.get("HX-Request"):
        alerts = unread_alerts_for(request.user)
        return render(
            request,
            "dashboard/partials/alert_list.html",
            {"alerts": alerts},
        )
    return JsonResponse({"ok": ok})


@login_required
@require_GET
def live_signals_status_fragment(request: HttpRequest) -> HttpResponse:
    """Small polled fragment: monitor/feed status summary."""
    dashboard = build_dashboard(request.user, SignalFilters())
    return render(
        request,
        "dashboard/partials/live_signals_status.html",
        {"dashboard": dashboard, "poll_seconds": _poll_seconds()},
    )


__all__ = [
    "live_signal_alert_read",
    "live_signal_detail",
    "live_signals",
    "live_signals_feed",
    "live_signals_outcomes",
    "live_signals_settings",
    "live_signals_status_fragment",
]
