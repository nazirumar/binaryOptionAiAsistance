"""Navigation structure for the application shell.

The sidebar, the focused-page breadcrumbs and the top-bar search all read from
this single module, so navigation can never drift between surfaces.

Nothing here changes routing or permissions: every entry is a `{% url %}` name
that already exists in :mod:`apps.dashboard.urls` or :mod:`apps.accounts.urls`.
The ``current`` matching is best-effort on the resolved URL name and only drives
the ``aria-current`` / active styling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.http import HttpRequest


@dataclass(frozen=True)
class NavEntry:
    """A single navigable destination."""

    label: str
    url_name: str
    icon: str
    #: URL names that should also mark this entry active (detail pages etc.).
    match: tuple[str, ...] = ()


@dataclass(frozen=True)
class NavGroup:
    """A labelled group of destinations in the sidebar."""

    label: str
    icon: str
    entries: tuple[NavEntry, ...] = field(default_factory=tuple)
    #: When true the group renders as a collapsible <details> disclosure.
    collapsible: bool = False


#: The application information architecture. Order here is the display order.
NAV_GROUPS: tuple[NavGroup, ...] = (
    NavGroup(
        label="Workspace",
        icon="icon-dashboard",
        entries=(
            NavEntry("Dashboard", "dashboard:index", "icon-dashboard"),
            NavEntry(
                "Screenshot Analysis",
                "dashboard:vision",
                "icon-scan",
                match=("dashboard:vision", "dashboard:vision-detail"),
            ),
            NavEntry(
                "AI Assistant",
                "dashboard:assistant",
                "icon-sparkles",
                match=("dashboard:assistant", "dashboard:conversation-detail"),
            ),
            NavEntry("Analysis History", "dashboard:analyses", "icon-history"),
        ),
    ),
    NavGroup(
        label="Strategies",
        icon="icon-library",
        entries=(
            NavEntry(
                "Strategy Library",
                "dashboard:strategy-library",
                "icon-library",
                match=("dashboard:strategy-detail",),
            ),
            NavEntry(
                "Book Strategies",
                "dashboard:book-strategies",
                "icon-book",
                match=("dashboard:book-strategy-detail",),
            ),
            NavEntry("Knowledge Library", "dashboard:knowledge", "icon-brain"),
        ),
    ),
    NavGroup(
        label="Research",
        icon="icon-flask",
        collapsible=True,
        entries=(
            NavEntry(
                "Backtesting",
                "dashboard:backtests",
                "icon-flask",
                match=("dashboard:backtest-run",),
            ),
            NavEntry("Strategy Analytics", "dashboard:analytics", "icon-chart"),
            NavEntry("Forward Testing", "dashboard:forward-testing", "icon-target"),
            NavEntry(
                "Screenshot Cases",
                "dashboard:screenshot-cases",
                "icon-image",
                match=("dashboard:screenshot-case-detail",),
            ),
            NavEntry(
                "Review Queue",
                "dashboard:review-queue",
                "icon-inbox",
                match=("dashboard:review-resolve",),
            ),
            NavEntry("Probability & Calibration", "dashboard:probability", "icon-gauge"),
            NavEntry(
                "Market Data & Synchronization",
                "dashboard:sync",
                "icon-database",
                match=("dashboard:sync", "dashboard:sync-detail"),
            ),
            NavEntry(
                "Trading Journal",
                "dashboard:journal",
                "icon-journal",
                match=(
                    "dashboard:journal",
                    "dashboard:journal-create",
                    "dashboard:journal-edit",
                    "dashboard:journal-performance",
                ),
            ),
            NavEntry("Reports", "dashboard:reports", "icon-report"),
        ),
    ),
)

#: Account menu entries (top-bar profile dropdown, not the sidebar body).
ACCOUNT_ENTRIES: tuple[NavEntry, ...] = (
    NavEntry("Settings", "dashboard:settings", "icon-settings"),
    NavEntry("Profile", "dashboard:settings-profile", "icon-user"),
    NavEntry("Security", "dashboard:settings-password", "icon-shield"),
)

#: Human labels + parent group for detail pages, used to build breadcrumbs.
#: Maps a resolved URL name to ``(group_label, page_label, parent_url_name)``.
_BREADCRUMB_PARENTS: dict[str, tuple[str, str, str | None]] = {
    "dashboard:vision": ("Workspace", "Screenshot Analysis", None),
    "dashboard:vision-detail": ("Workspace", "Screenshot Analysis", "dashboard:vision"),
    "dashboard:assistant": ("Workspace", "AI Assistant", None),
    "dashboard:conversation-detail": (
        "Workspace",
        "AI Assistant",
        "dashboard:assistant",
    ),
    "dashboard:analyses": ("Workspace", "Analysis History", None),
    "dashboard:strategy-library": ("Strategies", "Strategy Library", None),
    "dashboard:strategy-detail": (
        "Strategies",
        "Strategy Library",
        "dashboard:strategy-library",
    ),
    "dashboard:book-strategies": ("Strategies", "Book Strategies", None),
    "dashboard:book-strategy-detail": (
        "Strategies",
        "Book Strategies",
        "dashboard:book-strategies",
    ),
    "dashboard:book-strategies-research": (
        "Strategies",
        "Book Strategies",
        "dashboard:book-strategies",
    ),
    "dashboard:knowledge": ("Strategies", "Knowledge Library", None),
    "dashboard:backtests": ("Research", "Backtesting", None),
    "dashboard:analytics": ("Research", "Strategy Analytics", None),
    "dashboard:forward-testing": ("Research", "Forward Testing", None),
    "dashboard:screenshot-cases": ("Research", "Screenshot Cases", None),
    "dashboard:screenshot-case-detail": (
        "Research",
        "Screenshot Cases",
        "dashboard:screenshot-cases",
    ),
    "dashboard:review-queue": ("Research", "Review Queue", None),
    "dashboard:probability": ("Research", "Probability & Calibration", None),
    "dashboard:sync": ("Research", "Market Data & Synchronization", None),
    "dashboard:sync-detail": (
        "Research",
        "Market Data & Synchronization",
        "dashboard:sync",
    ),
    "dashboard:mt5": ("Research", "Market Data & Synchronization", "dashboard:sync"),
    "dashboard:market-health": ("Research", "Market Data & Synchronization", "dashboard:sync"),
    "dashboard:journal": ("Research", "Trading Journal", None),
    "dashboard:journal-create": ("Research", "Trading Journal", "dashboard:journal"),
    "dashboard:journal-edit": ("Research", "Trading Journal", "dashboard:journal"),
    "dashboard:journal-performance": (
        "Research",
        "Journal Performance",
        "dashboard:journal",
    ),
    "dashboard:reports": ("Research", "Reports", None),
    "dashboard:settings": ("Account", "Settings", None),
    "dashboard:settings-profile": ("Account", "Profile", "dashboard:settings"),
    "dashboard:settings-password": ("Account", "Security", "dashboard:settings"),
    "dashboard:overview": ("Workspace", "Overview", "dashboard:index"),
}


def _resolved_name(request: HttpRequest) -> str:
    match = getattr(request, "resolver_match", None)
    if match is None:
        return ""
    if match.namespace and match.url_name:
        return f"{match.namespace}:{match.url_name}"
    return match.url_name or ""


def shell_context(request: HttpRequest) -> dict[str, Any]:
    """Expose navigation + breadcrumb data to every template."""
    current = _resolved_name(request)

    # Parse the current breadcrumb triple, tolerating unknown pages.
    crumb: tuple[str, str, str | None] = _BREADCRUMB_PARENTS.get(
        current, ("", "", None)
    )
    group_label, page_label, parent_name = crumb

    breadcrumbs: list[dict[str, str]] = []
    if page_label:
        if parent_name:
            parent = _BREADCRUMB_PARENTS.get(parent_name)
            if parent:
                # parent = (group, label, grandparent)
                breadcrumbs.append({"label": parent[1], "url_name": parent_name})
        breadcrumbs.append({"label": page_label, "url_name": ""})

    return {
        "nav_groups": NAV_GROUPS,
        "account_entries": ACCOUNT_ENTRIES,
        "current_url_name": current,
        "breadcrumbs": breadcrumbs,
        "page_group": group_label,
        "page_label": page_label,
    }
