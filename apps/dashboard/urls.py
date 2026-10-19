"""Dashboard URLs."""

from __future__ import annotations

from django.urls import path

from apps.dashboard import page_views, views

app_name = "dashboard"

urlpatterns = [
    path("", views.index, name="index"),
    path("mt5/", views.mt5, name="mt5"),
    path("vision/", views.vision, name="vision"),
    path("vision/upload/", views.vision_upload, name="vision-upload"),
    path("vision/<int:pk>/", views.vision_detail, name="vision-detail"),
    path("vision/<int:pk>/analyze/", views.vision_analyze, name="vision-analyze"),
    path("vision/<int:pk>/status/", views.vision_status, name="vision-status"),
    path("sync/", views.sync, name="sync"),
    path("sync/verify/", views.sync_verify, name="sync-verify"),
    path("sync/<int:pk>/", views.sync_detail, name="sync-detail"),
    path("partials/status/", views.status_fragment, name="status"),
    path("overview/", page_views.overview, name="overview"),
    path("analyses/", page_views.analyses, name="analyses"),
    path("analytics/", page_views.analytics, name="analytics"),
    path("assistant/", page_views.assistant, name="assistant"),
    path("assistant/<int:pk>/", page_views.assistant_detail, name="conversation-detail"),
    path(
        "assistant/<int:pk>/follow-up/",
        page_views.assistant_follow_up,
        name="conversation-follow-up",
    ),
    path("probability/", page_views.probability, name="probability"),
    path("market-health/", page_views.market_health, name="market-health"),
    path("backtests/", page_views.backtests, name="backtests"),
    path("backtests/run/", page_views.backtest_run, name="backtest-run"),
    path("knowledge/", page_views.knowledge, name="knowledge"),
    path("strategies/", page_views.strategy_library, name="strategy-library"),
    path(
        "strategies/<str:strategy_id>/",
        page_views.strategy_detail,
        name="strategy-detail",
    ),
    path(
        "book-strategies/",
        page_views.book_strategies,
        name="book-strategies",
    ),
    # Registered before <str:key>/ so "research" is not swallowed as a key.
    path(
        "book-strategies/research/",
        page_views.book_research,
        name="book-strategies-research",
    ),
    path(
        "book-strategies/<str:key>/",
        page_views.book_strategy_detail,
        name="book-strategy-detail",
    ),
    path(
        "book-strategies/<str:key>/toggle/",
        page_views.book_strategy_toggle,
        name="book-strategy-toggle",
    ),
    path("settings/", page_views.settings_page, name="settings"),
    path("settings/profile/", page_views.settings_profile, name="settings-profile"),
    path(
        "settings/password/",
        page_views.SettingsPasswordChangeView.as_view(),
        name="settings-password",
    ),
    path("settings/delete/", page_views.account_delete, name="settings-delete"),
    path("journal/", page_views.journal, name="journal"),
    path("journal/create/", page_views.journal_create, name="journal-create"),
    path("journal/create/post/", page_views.journal_create_post, name="journal-create-post"),
    path("journal/<int:pk>/edit/", page_views.journal_edit, name="journal-edit"),
    path("journal/<int:pk>/edit/post/", page_views.journal_edit_post, name="journal-edit-post"),
    path("journal/<int:pk>/delete/", page_views.journal_delete, name="journal-delete"),
    path("journal/performance/", page_views.journal_performance, name="journal-performance"),
    path("reports/", page_views.reports, name="reports"),
    path("exports/journal.csv", page_views.export_journal_csv, name="export-journal-csv"),
    path("exports/analyses.csv", page_views.export_analyses_csv, name="export-analyses-csv"),
    path(
        "exports/performance.pdf", page_views.export_performance_pdf, name="export-performance-pdf"
    ),
]
