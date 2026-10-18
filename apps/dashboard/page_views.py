# apps/dashboard/page_views.py
"""Server-rendered dashboard pages (Phase 9).

These views are session-authenticated (Django's ``login_required``) and
owner-scoped. Anonymous requests are redirected to the login page. API clients
should use the DRF endpoints under ``/api/dashboard/`` and ``/api/journal/``,
which return ``401`` for unauthenticated requests.

Both surfaces reuse the same Phase 9 service layer, so the HTML pages and the
JSON API always report identical, real data.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET, require_POST

from apps.dashboard.services.analytics_service import (
    StrategyAnalytics,
    daily_decision_series,
)
from apps.dashboard.services.history_service import AnalysisHistoryService
from apps.dashboard.services.market_health_service import MarketHealthService
from apps.dashboard.services.overview_service import OverviewService
from apps.dashboard.services.performance_service import ProbabilityAnalytics
from apps.dashboard.services.reporting_service import ReportingService

#: Page size for server-rendered tables.
PAGE_SIZE = 25


# ---------------------------------------------------------------------------
# Overview (Step 4)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def overview(request: HttpRequest) -> HttpResponse:
    context = {"overview": OverviewService(request.user).build()}
    return render(request, "dashboard/overview.html", context)


# ---------------------------------------------------------------------------
# Analysis history (Step 5)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def analyses(request: HttpRequest) -> HttpResponse:
    service = AnalysisHistoryService(request.user)
    params = request.GET
    queryset = service.filter(
        instrument=params.get("instrument"),
        timeframe=params.get("timeframe"),
        market_type=params.get("market_type"),
        strategy_family=params.get("strategy_family"),
        direction=params.get("direction"),
        reason=params.get("reason"),
        data_compatibility=params.get("data_compatibility"),
        probability_status=params.get("probability_status"),
        date_from=params.get("date_from"),
        date_to=params.get("date_to"),
        search=params.get("search"),
    )
    paginator = Paginator(queryset, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    context = {
        "page_obj": page,
        "paginator": paginator,
        "evaluations": page,
        "choices": service.filter_choices(),
        "filters": params,
    }
    return render(request, "dashboard/analyses.html", context)


# ---------------------------------------------------------------------------
# Strategy analytics (Step 6)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def analytics(request: HttpRequest) -> HttpResponse:
    context = {
        "analytics": StrategyAnalytics(request.user).build(),
        "series": daily_decision_series(request.user),
    }
    return render(request, "dashboard/analytics.html", context)


# ---------------------------------------------------------------------------
# Probability analytics (Step 7)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def probability(request: HttpRequest) -> HttpResponse:
    context = {"probability": ProbabilityAnalytics(request.user).build()}
    return render(request, "dashboard/probability.html", context)


# ---------------------------------------------------------------------------
# Market health (Step 10)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def market_health(request: HttpRequest) -> HttpResponse:
    from apps.market_data.permissions import accessible_profiles

    profile = accessible_profiles(request.user).order_by("-is_default", "name").first()
    context = {"health": MarketHealthService(request.user).build(profile)}
    return render(request, "dashboard/market_health.html", context)


# ---------------------------------------------------------------------------
# Backtest dashboard (Step 11)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def backtests(request: HttpRequest) -> HttpResponse:
    from apps.research.models import BacktestRun, HistoricalDataset

    # ``owner__in=[user, None]`` would silently drop shared (NULL-owner)
    # datasets, because SQL ``IN`` never matches NULL — use explicit OR.
    datasets = HistoricalDataset.objects.filter(
        Q(owner=request.user) | Q(owner__isnull=True)
    ).order_by("-created_at")[:50]
    runs = BacktestRun.objects.filter(owner=request.user).order_by("-created_at")[:50]
    context = {"datasets": datasets, "runs": runs}
    return render(request, "dashboard/backtests.html", context)


@login_required
@require_POST
def backtest_run(request: HttpRequest) -> HttpResponse:
    """Queue a backtest job; the expensive work runs in the background worker."""
    from apps.research.models import BacktestRun, HistoricalDataset
    from apps.research.tasks import run_backtest_task

    dataset_id = request.POST.get("dataset_id")
    if not dataset_id or not str(dataset_id).isdigit():
        messages.error(request, "Please choose a dataset.")
        return redirect("dashboard:backtests")
    # Owner-scoped: a user may only launch a run against their own or the
    # shared (ownerless) dataset — never another user's (IDOR guard).
    # NOTE: ``owner__in=[user, None]`` does NOT match NULL rows (SQL ``IN``
    # never matches NULL), so an explicit OR-isnull is required.
    dataset = HistoricalDataset.objects.filter(
        Q(owner=request.user) | Q(owner__isnull=True),
        pk=int(dataset_id),
    ).first()
    if dataset is None:
        messages.error(request, "That dataset could not be found.")
        return redirect("dashboard:backtests")
    run = BacktestRun.objects.create(
        owner=request.user,
        dataset=dataset,
        name=request.POST.get("name") or f"Backtest {dataset.name}",
        status="pending",
        strategy_config={
            "strategy": request.POST.get("strategy", ""),
            "instrument": request.POST.get("instrument", dataset.instrument),
            "timeframe": request.POST.get("timeframe", dataset.timeframe),
        },
    )
    run_backtest_task.delay(run.pk)
    messages.success(request, "Backtest queued. Results will appear when the worker finishes.")
    return redirect("dashboard:backtests")


# ---------------------------------------------------------------------------
# Knowledge library (Step 12)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def knowledge(request: HttpRequest) -> HttpResponse:
    from apps.price_action.knowledge import catalogue

    return render(request, "dashboard/knowledge.html", {"catalogue": catalogue()})


# ---------------------------------------------------------------------------
# Strategy library (Phase 12, CP12)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def strategy_library(request: HttpRequest) -> HttpResponse:
    """Versioned strategy definitions with explicit validation status.

    Experimental/draft definitions are listed (never hidden) but visually
    labelled, so an unvalidated strategy can never pass as approved knowledge.
    """
    from apps.strategy_knowledge.models import StrategyDefinition
    from apps.strategy_knowledge.services.metrics import DISCLAIMER as METRICS_DISCLAIMER

    search = (request.GET.get("q") or "").strip()
    category_slug = (request.GET.get("category") or "").strip()
    qs = StrategyDefinition.objects.select_related("category", "version")
    if search:
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(strategy_id__icontains=search)
            | Q(description__icontains=search)
        )
    if category_slug:
        qs = qs.filter(category__slug=category_slug)

    grouped: dict[str, list[StrategyDefinition]] = {}
    for definition in qs:
        grouped.setdefault(
            definition.category.name if definition.category_id else "Uncategorised", []
        ).append(definition)

    from apps.strategy_knowledge.models import StrategyCategory

    context = {
        "grouped": grouped,
        "categories": StrategyCategory.objects.all(),
        "search": search,
        "active_category": category_slug,
        "total": qs.count(),
        "metrics_disclaimer": METRICS_DISCLAIMER,
    }
    return render(request, "dashboard/strategy_library.html", context)


@login_required
@require_GET
def strategy_detail(request: HttpRequest, strategy_id: str) -> HttpResponse:
    """One definition: structured conditions, examples, recent detections."""
    from apps.strategy_knowledge.models import StrategyDefinition

    definition = (
        StrategyDefinition.objects.filter(strategy_id=strategy_id)
        .select_related("category", "version")
        .first()
    )
    if definition is None:
        raise Http404("strategy not found")

    conditions = list(definition.conditions.all())
    detections = list(definition.detections.select_related("analysis").order_by("-created_at")[:20])
    examples = list(definition.examples.all())
    status_counts: dict[str, int] = {}
    for detection in definition.detections.all():
        status_counts[detection.status] = status_counts.get(detection.status, 0) + 1

    context = {
        "definition": definition,
        "required": [c for c in conditions if c.kind == "required"],
        "optional": [c for c in conditions if c.kind == "optional"],
        "contradictory": [c for c in conditions if c.kind == "contradictory"],
        "invalidation": [c for c in conditions if c.kind == "invalidation"],
        "detections": detections,
        "examples": examples,
        "status_counts": status_counts,
    }
    return render(request, "dashboard/strategy_detail.html", context)


# ---------------------------------------------------------------------------
# Book strategies (Phase 13, Step 8)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def book_strategies(request: HttpRequest) -> HttpResponse:
    """Binary Options Trading Bible catalog with explicit review states.

    Every entry is visible for education (including contradictory or
    unimplemented ones) and clearly labelled. The enable/disable control only
    flips ``recognition_enabled`` (staff only, POST); no page or toggle here
    can approve a strategy for live decisions.
    """
    from apps.book_strategies.models import BookStrategy

    search = (request.GET.get("q") or "").strip()
    qs = BookStrategy.objects.select_related("version")
    if search:
        qs = qs.filter(name__icontains=search) | qs.filter(key__icontains=search)

    grouped: dict[str, list[BookStrategy]] = {}
    for row in qs:
        grouped.setdefault(f"Chapter {row.chapter}", []).append(row)

    context = {
        "grouped": grouped,
        "search": search,
        "total": qs.count(),
        "implemented_total": sum(1 for r in qs if r.detector_key),
        "approved_total": sum(1 for r in qs if r.decision_use_approved),
        "is_staff_user": request.user.is_staff,
    }
    return render(request, "dashboard/book_strategies.html", context)


@login_required
@require_GET
def book_strategy_detail(request: HttpRequest, key: str) -> HttpResponse:
    from apps.book_strategies.models import BookStrategy

    strategy = BookStrategy.objects.select_related("version").filter(key=key).first()
    if strategy is None:
        raise Http404("book strategy not found")

    detections = list(strategy.detections.order_by("-created_at")[:20])
    state_counts: dict[str, int] = {}
    for detection in strategy.detections.all():
        state_counts[detection.state] = state_counts.get(detection.state, 0) + 1

    context = {
        "strategy": strategy,
        "detections": detections,
        "state_counts": state_counts,
        "is_staff_user": request.user.is_staff,
    }
    return render(request, "dashboard/book_strategy_detail.html", context)


@login_required
@require_POST
def book_strategy_toggle(request: HttpRequest, key: str) -> HttpResponse:
    """Staff-only recognition switch. NEVER touches ``decision_use_approved``."""
    from apps.book_strategies.models import BookStrategy

    if not request.user.is_staff:
        messages.error(request, "Only administrators can toggle book strategies.")
        return redirect("dashboard:book-strategies")
    strategy = BookStrategy.objects.filter(key=key).first()
    if strategy is None:
        raise Http404("book strategy not found")
    strategy.recognition_enabled = not strategy.recognition_enabled
    strategy.save(update_fields=["recognition_enabled", "updated_at"])
    state = "enabled" if strategy.recognition_enabled else "disabled"
    messages.success(
        request,
        f"{strategy.key} recognition {state}. This does not approve the "
        "strategy for live decisions.",
    )
    return redirect(request.META.get("HTTP_REFERER") or "dashboard:book-strategies")


# ---------------------------------------------------------------------------
# Settings (Step 13)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def settings_page(request: HttpRequest) -> HttpResponse:
    from apps.accounts.forms import PreferenceForm, ProfileForm
    from apps.accounts.models import UserPreference

    preference, _ = UserPreference.objects.get_or_create(user=request.user)
    context = {
        "profile_form": ProfileForm(instance=request.user),
        "preference_form": PreferenceForm(instance=preference),
    }
    return render(request, "dashboard/settings.html", context)


@login_required
@require_POST
def settings_profile(request: HttpRequest) -> HttpResponse:
    from apps.accounts.forms import PreferenceForm, ProfileForm
    from apps.accounts.models import UserPreference

    preference, _ = UserPreference.objects.get_or_create(user=request.user)
    profile_form = ProfileForm(request.POST, instance=request.user)
    preference_form = PreferenceForm(request.POST, instance=preference)
    if profile_form.is_valid() and preference_form.is_valid():
        profile_form.save()
        preference_form.save()
        messages.success(request, "Settings saved.")
        return redirect("dashboard:settings")
    messages.error(request, "Please correct the errors below.")
    return render(
        request,
        "dashboard/settings.html",
        {"profile_form": profile_form, "preference_form": preference_form},
    )


class SettingsPasswordChangeView(PasswordChangeView):
    template_name = "dashboard/password_change.html"
    success_url = reverse_lazy("dashboard:settings")

    def form_valid(self, form):  # type: ignore[no-untyped-def]
        messages.success(self.request, "Password updated.")
        return super().form_valid(form)


@login_required
@require_POST
def account_delete(request: HttpRequest) -> HttpResponse:
    """Delete the current account after password confirmation."""
    password = request.POST.get("password", "")
    if not request.user.check_password(password):
        messages.error(request, "Password confirmation failed. Account not deleted.")
        return redirect("dashboard:settings")
    user = request.user
    logout(request)
    user.delete()
    messages.success(request, "Your account and data have been deleted.")
    return redirect("home")


# ---------------------------------------------------------------------------
# Trading journal (Steps 8 & 9)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def journal(request: HttpRequest) -> HttpResponse:
    from apps.trading_journal.models import JournalTrade
    from apps.trading_journal.services.journal_performance import JournalPerformance

    queryset = JournalTrade.objects.filter(owner=request.user).order_by("-entry_timestamp")
    paginator = Paginator(queryset, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    performance = JournalPerformance(queryset)
    context = {
        "page_obj": page,
        "paginator": paginator,
        "trades": page,
        "performance": performance.segmented_summary(),
    }
    return render(request, "dashboard/journal.html", context)


@login_required
@require_GET
def journal_create(request: HttpRequest) -> HttpResponse:
    from apps.trading_journal.forms import JournalTradeForm

    form = JournalTradeForm()
    return render(request, "dashboard/journal_form.html", {"form": form, "mode": "create"})


@login_required
@require_POST
def journal_create_post(request: HttpRequest) -> HttpResponse:
    from apps.trading_journal.forms import JournalTradeForm

    form = JournalTradeForm(request.POST)
    if form.is_valid():
        trade = form.save(commit=False)
        trade.owner = request.user
        trade.save()
        messages.success(request, "Journal trade created.")
        return redirect("dashboard:journal")
    return render(
        request,
        "dashboard/journal_form.html",
        {"form": form, "mode": "create", "errors": form.errors},
    )


@login_required
@require_GET
def journal_edit(request: HttpRequest, pk: int) -> HttpResponse:
    from apps.trading_journal.forms import JournalTradeForm
    from apps.trading_journal.models import JournalTrade

    trade = JournalTrade.objects.filter(owner=request.user, pk=pk).first()
    if trade is None:
        raise Http404("Trade not found.")
    form = JournalTradeForm(instance=trade)
    return render(
        request,
        "dashboard/journal_form.html",
        {"form": form, "mode": "edit", "trade": trade},
    )


@login_required
@require_POST
def journal_edit_post(request: HttpRequest, pk: int) -> HttpResponse:
    from apps.trading_journal.forms import JournalTradeForm
    from apps.trading_journal.models import JournalTrade

    trade = JournalTrade.objects.filter(owner=request.user, pk=pk).first()
    if trade is None:
        raise Http404("Trade not found.")
    form = JournalTradeForm(request.POST, instance=trade)
    if form.is_valid():
        form.save()
        messages.success(request, "Journal trade updated.")
        return redirect("dashboard:journal")
    return render(
        request,
        "dashboard/journal_form.html",
        {"form": form, "mode": "edit", "trade": trade, "errors": form.errors},
    )


@login_required
@require_POST
def journal_delete(request: HttpRequest, pk: int) -> HttpResponse:
    from apps.trading_journal.models import JournalTrade

    trade = JournalTrade.objects.filter(owner=request.user, pk=pk).first()
    if trade is None:
        raise Http404("Trade not found.")
    trade.delete()
    messages.success(request, "Journal trade deleted.")
    return redirect("dashboard:journal")


@login_required
@require_GET
def journal_performance(request: HttpRequest) -> HttpResponse:
    from apps.trading_journal.models import JournalTrade
    from apps.trading_journal.services.journal_performance import JournalPerformance

    queryset = JournalTrade.objects.filter(owner=request.user).order_by("-entry_timestamp")
    performance = JournalPerformance(queryset).segmented_summary()
    return render(request, "dashboard/journal_performance.html", {"performance": performance})


# ---------------------------------------------------------------------------
# AI assistant conversations (Phase 11 CP12)
# ---------------------------------------------------------------------------
def _latest_result_summary(conversation) -> dict:
    """Most recent persisted assessment for a conversation's UI.

    Prefers the completed job's ``result_summary`` (the pipeline's own
    summarised verdict); falls back to the analysis session's full
    ``response_schema``. Never fabricates a summary: an empty dict means "no
    assessment yet" and the templates render that state explicitly.
    """
    from apps.ai_assistant.models import AIAnalysisJob, AIAnalysisSession

    job = (
        AIAnalysisJob.objects.filter(
            conversation=conversation, status=AIAnalysisJob.Status.COMPLETED
        )
        .order_by("-finished_at", "-pk")
        .first()
    )
    if job and isinstance(job.result_summary, dict) and job.result_summary.get("direction"):
        return job.result_summary
    session = (
        AIAnalysisSession.objects.filter(conversation=conversation).order_by("-created_at").first()
    )
    if session and isinstance(session.response_schema, dict):
        return session.response_schema
    return {}


@login_required
@require_GET
def assistant(request: HttpRequest) -> HttpResponse:
    """List the signed-in user's assistant conversations with latest verdict."""
    from apps.ai_assistant.models import AIConversation

    conversations = AIConversation.objects.filter(owner=request.user).select_related(
        "screenshot_analysis", "sync_session"
    )
    rows = [{"conversation": c, "summary": _latest_result_summary(c)} for c in conversations]
    return render(request, "dashboard/assistant.html", {"rows": rows})


@login_required
@require_GET
def assistant_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """One conversation: persisted assessment, evidence and message thread."""
    from apps.ai_assistant.models import AIAnalysisSession, AIConversation

    conversation = (
        AIConversation.objects.filter(owner=request.user, pk=pk)
        .select_related("screenshot_analysis", "sync_session")
        .first()
    )
    if conversation is None:
        raise Http404("Conversation not found.")
    session = (
        AIAnalysisSession.objects.filter(conversation=conversation)
        .select_related("strategy_evaluation", "sync_session")
        .order_by("-created_at")
        .first()
    )
    context = {
        "conversation": conversation,
        "session": session,
        "summary": _latest_result_summary(conversation),
        "messages": conversation.messages.order_by("created_at"),
    }
    return render(request, "dashboard/conversation_detail.html", context)


@login_required
@require_POST
def assistant_follow_up(request: HttpRequest, pk: int) -> HttpResponse:
    """Answer a follow-up question from stored evidence (POST, then redirect)."""
    from apps.ai_assistant.models import AIConversation
    from apps.ai_assistant.services.assistant_service import AssistantService

    conversation = AIConversation.objects.filter(owner=request.user, pk=pk).first()
    if conversation is None:
        raise Http404("Conversation not found.")
    text = (request.POST.get("message") or "").strip()
    if not text:
        messages.error(request, "Please enter a question.")
        return redirect("dashboard:conversation-detail", pk=conversation.pk)
    outcome = AssistantService().handle_follow_up(request.user, conversation.pk, text)
    if "error" in outcome:
        messages.error(request, "That follow-up could not be answered from stored evidence.")
    else:
        messages.success(request, "Follow-up answered from stored evidence.")
    return redirect("dashboard:conversation-detail", pk=conversation.pk)


# ---------------------------------------------------------------------------
# Reports / Exports (Step 14) - session-authenticated, owner-scoped
# ---------------------------------------------------------------------------
@login_required
@require_GET
def reports(request: HttpRequest) -> HttpResponse:
    return render(request, "dashboard/reports.html")


@login_required
@require_GET
def export_journal_csv(request: HttpRequest) -> HttpResponse:
    return ReportingService(request.user).journal_csv(
        trade_type=request.GET.get("trade_type") or None
    )


@login_required
@require_GET
def export_analyses_csv(request: HttpRequest) -> HttpResponse:
    return ReportingService(request.user).analyses_csv()


@login_required
@require_GET
def export_performance_pdf(request: HttpRequest) -> HttpResponse:
    return ReportingService(request.user).performance_pdf()
