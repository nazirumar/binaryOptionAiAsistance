# Frontend Page Inventory

**Project:** Nazbeen Academy Binary Ai Asisstance
**Scope:** Every rendered page, template and partial (Phase A deliverable)
**Date:** 2026-10-20

Legend — **Shell:** `base` = public shell, `dash` = dashboard shell
(`dashboard/layout.html`), **+shell** = currently bypasses the dashboard shell
and must be folded in during the redesign.

---

## 1. Public pages

| # | URL | URL name | Template | Shell | Notes |
|---|---|---|---|---|---|
| 1 | `/` | `home` | `core/home.html` | base | Landing page. Redirects authenticated users to `/dashboard/`. |
| 2 | `/accounts/login/` | `accounts:login` | `accounts/login.html` | base | Credential form; field errors. |
| 3 | `/accounts/signup/` | `accounts:signup` | `accounts/signup.html` | base | Registration form. |
| 4 | `/accounts/logout/` | `accounts:logout` | — (POST → redirect) | — | Django `LogoutView`. |
| 5 | `/healthz/` | `healthz` | JSON (no template) | — | Liveness probe. |
| 6 | `/healthz/detail/` | `healthz-detail` | JSON (no template) | — | Staff diagnostics. |
| 7 | `/api/docs/` | `api-docs` | drf-spectacular | — | API docs (dev/test only). |
| 8 | `/admin/` | — | Django admin | — | Django admin (not redesigned; framework-provided). |

---

## 2. Dashboard — Workspace

| # | URL | URL name | Template | Shell | Key content / contracts |
|---|---|---|---|---|---|
| 9 | `/dashboard/` | `dashboard:index` | `dashboard/index.html` | dash | Welcome + HTMX status card (`#status-card`, `dashboard:status`), "Your activity" metrics, quick links, roadmap. **Must keep** display name, "Critical integration remediation", no `Planned`. |
| 10 | `/dashboard/overview/` | `dashboard:overview` | `dashboard/overview.html` | dash | Real metrics, validated performance, latest backtest, recent analyses. |
| 11 | `/dashboard/analyses/` | `dashboard:analyses` | `dashboard/analyses.html` | dash | GET filter form, results table, CSV export, pagination (`partials/pagination.html`). |
| 12 | `/dashboard/assistant/` | `dashboard:assistant` | `dashboard/assistant.html` | dash | Conversation list. **Must keep** `No conversations yet`. |
| 13 | `/dashboard/assistant/<pk>/` | `dashboard:conversation-detail` | `dashboard/conversation_detail.html` | dash | Assessment, decision reasons, evidence, calibration, probability notice, follow-up form. **Must keep** `Assessment`, `MT5 verification`, `Calibration`, `Probability unavailable`, `model not calibrated`, `Evidence`, `Sync status`, `NO TRADE`, `Decision reasons`, `Assistant`. |
| 14 | `/dashboard/assistant/<pk>/follow-up/` | `dashboard:conversation-follow-up` | — (POST → redirect) | — | Persists a follow-up message. |

---

## 3. Dashboard — Screenshot analysis & synchronization (fold into shell)

| # | URL | URL name | Template | Shell | Key content / contracts |
|---|---|---|---|---|---|
| 15 | `/dashboard/vision/` | `dashboard:vision` | `dashboard/vision.html` | base **+shell** | Upload form (multipart, field `image`), history table. |
| 16 | `/dashboard/vision/upload/` | `dashboard:vision-upload` | — (POST → redirect) | — | Validates + stores screenshot, enqueues analysis. |
| 17 | `/dashboard/vision/<pk>/` | `dashboard:vision-detail` | `dashboard/vision_detail.html` | base **+shell** | Screenshot preview + HTMX `#vision-status`. **Must keep** `Screenshot #`. |
| 18 | `/dashboard/vision/<pk>/analyze/` | `dashboard:vision-analyze` | — (POST → redirect) | — | (Re)queue analysis. |
| 19 | `/dashboard/vision/<pk>/status/` | `dashboard:vision-status` | `dashboard/partials/vision_status.html` | partial | HTMX fragment: status, metadata, structure, patterns, zones, observations, warnings. **Must keep** `Analysis`. |
| 20 | `/dashboard/sync/` | `dashboard:sync` | `dashboard/sync.html` | base **+shell** | Verify-an-analysis form + sync history. |
| 21 | `/dashboard/sync/verify/` | `dashboard:sync-verify` | — (POST → redirect) | — | Creates a sync session. |
| 22 | `/dashboard/sync/<pk>/` | `dashboard:sync-detail` | `dashboard/sync_detail.html` | base **+shell** | Verified/not-verified banner, candle comparison, mismatch reasons. |
| 23 | `/dashboard/mt5/` | `dashboard:mt5` | `dashboard/mt5.html` | base **+shell** | Connection, latest quote, last candle, workers. **Must keep** `MT5 market data`, masked login `*******21`. |
| 24 | `/dashboard/market-health/` | `dashboard:market-health` | `dashboard/market_health.html` | dash | Status cards, OTC warnings, symbols, recent events. |
| 25 | `/dashboard/partials/status/` | `dashboard:status` | `dashboard/partials/status.html` | partial | HTMX status card. **Must keep** `System status`, `Offline mock`, `no live model configured`, `not configured (missing API key, model)`. |

---

## 4. Dashboard — Strategies & knowledge

| # | URL | URL name | Template | Shell | Key content / contracts |
|---|---|---|---|---|---|
| 26 | `/dashboard/strategies/` | `dashboard:strategy-library` | `dashboard/strategy_library.html` | dash | Grouped by category, status badges, search/filter. |
| 27 | `/dashboard/strategies/<strategy_id>/` | `dashboard:strategy-detail` | `dashboard/strategy_detail.html` | dash | Description, conditions, recognition history, examples. |
| 28 | `/dashboard/book-strategies/` | `dashboard:book-strategies` | `dashboard/book_strategies.html` | dash | Book catalog by chapter. **Must keep** `Book strategies`, `Rising Three Method`, `Not approved for decisions`. |
| 29 | `/dashboard/book-strategies/research/` | `dashboard:book-strategies-research` | `dashboard/book_research.html` | dash | Recognition + paper metrics, ranking, dataset provenance (241 lines). |
| 30 | `/dashboard/book-strategies/<key>/` | `dashboard:book-strategy-detail` | `dashboard/book_strategy_detail.html` | dash | Single book strategy detail; staff toggle. |
| 31 | `/dashboard/book-strategies/<key>/toggle/` | `dashboard:book-strategy-toggle` | — (POST → redirect) | — | Staff recognition toggle. |
| 32 | `/dashboard/knowledge/` | `dashboard:knowledge` | `dashboard/knowledge.html` | dash | Versioned concept cards. **Must keep** `Bullish engulfing setup`, `Experimental`, `not validated`, `Prior bearish candle`. |

---

## 5. Dashboard — Research & forward testing

| # | URL | URL name | Template | Shell | Key content / contracts |
|---|---|---|---|---|---|
| 33 | `/dashboard/analytics/` | `dashboard:analytics` | `dashboard/analytics.html` | dash | Totals, by-family, verified accuracy. |
| 34 | `/dashboard/probability/` | `dashboard:probability` | `dashboard/probability.html` | dash | Calibration status. **Must keep** `Calibration status`. |
| 35 | `/dashboard/backtests/` | `dashboard:backtests` | `dashboard/backtests.html` | dash | Start-backtest form + runs table. |
| 36 | `/dashboard/backtests/run/` | `dashboard:backtest-run` | — (POST → redirect) | — | Enqueues a backtest. |
| 37 | `/dashboard/forward-testing/` | `dashboard:forward-testing` | `dashboard/forward_testing.html` | dash | Recognition vs prediction metrics (separate scopes), segments (143 lines). |
| 38 | `/dashboard/screenshot-cases/` | `dashboard:screenshot-cases` | `dashboard/screenshot_cases.html` | dash | Case list + human-labelled counts. |
| 39 | `/dashboard/screenshot-cases/<pk>/` | `dashboard:screenshot-case-detail` | `dashboard/screenshot_case_detail.html` | dash | Recognition results, annotations, paper predictions. |
| 40 | `/dashboard/review-queue/` | `dashboard:review-queue` | `dashboard/review_queue.html` | dash | Filters, items, resolve/dismiss, scan. |
| 41 | `/dashboard/review-queue/scan/` | `dashboard:review-queue-scan` | — (POST → redirect) | — | Idempotent scan. |
| 42 | `/dashboard/review-queue/<pk>/resolve/` | `dashboard:review-resolve` | — (POST → redirect) | — | Resolve/dismiss one item. |

---

## 6. Dashboard — Journal, reports, settings

| # | URL | URL name | Template | Shell | Key content / contracts |
|---|---|---|---|---|---|
| 43 | `/dashboard/journal/` | `dashboard:journal` | `dashboard/journal.html` | dash | Provenance summary, trades table, CSV export, new/delete. |
| 44 | `/dashboard/journal/create/` | `dashboard:journal-create` | `dashboard/journal_form.html` | dash | New entry (`{{ form.as_p }}`). |
| 45 | `/dashboard/journal/create/post/` | `dashboard:journal-create-post` | — (POST → redirect) | — | Creates entry. |
| 46 | `/dashboard/journal/<pk>/edit/` | `dashboard:journal-edit` | `dashboard/journal_form.html` | dash | Edit entry. |
| 47 | `/dashboard/journal/<pk>/edit/post/` | `dashboard:journal-edit-post` | — (POST → redirect) | — | Saves entry. |
| 48 | `/dashboard/journal/<pk>/delete/` | `dashboard:journal-delete` | — (POST → redirect) | — | Deletes entry. |
| 49 | `/dashboard/journal/performance/` | `dashboard:journal-performance` | `dashboard/journal_performance.html` | dash | Per-provenance stats. |
| 50 | `/dashboard/reports/` | `dashboard:reports` | `dashboard/reports.html` | dash | Export cards + report contents. |
| 51 | `/dashboard/exports/journal.csv` | `dashboard:export-journal-csv` | CSV download | — | File download. |
| 52 | `/dashboard/exports/analyses.csv` | `dashboard:export-analyses-csv` | CSV download | — | File download. |
| 53 | `/dashboard/exports/performance.pdf` | `dashboard:export-performance-pdf` | PDF download | — | File download. |
| 54 | `/dashboard/settings/` | `dashboard:settings` | `dashboard/settings.html` | dash | Profile/preferences, password link, delete account. |
| 55 | `/dashboard/settings/profile/` | `dashboard:settings-profile` | — (POST → redirect) | — | Saves profile. |
| 56 | `/dashboard/settings/password/` | `dashboard:settings-password` | `dashboard/password_change.html` | dash | Password change form. |
| 57 | `/dashboard/settings/delete/` | `dashboard:settings-delete` | — (POST → redirect) | — | Deletes account. |

---

## 7. Partials & shared components

| Template | Role |
|---|---|
| `templates/base.html` | Root public shell: `<head>`, top nav, flash messages, footer, theme toggle include, HTMX + CSRF wiring. |
| `templates/dashboard/layout.html` | Dashboard shell: sidebar nav + `{% block page_content %}`. |
| `templates/partials/theme_toggle.html` | Theme toggle button (only shared component today). |
| `templates/dashboard/partials/status.html` | HTMX system-status card. |
| `templates/dashboard/partials/vision_status.html` | HTMX analysis status + results (179 lines). |
| `templates/dashboard/partials/pagination.html` | Prev/next pager. |

---

## 8. Target navigation grouping (redesign)

The current sidebar has 4 groups (Analytics / Trading / Data / Reports). The
redesign regroups to the requested information architecture:

| Group | Items |
|---|---|
| **Workspace** | Dashboard, Screenshot Analysis, AI Assistant, Analysis History |
| **Strategies** | Strategy Library, Book Strategies, Knowledge Library |
| **Research** | Backtesting, Strategy Analytics, Forward Testing, Screenshot Cases, Review Queue, Probability & Calibration, Market Data & Synchronization, Trading Journal, Reports |
| **Account** | Settings, Profile, Security, Sign Out |

Progressive disclosure: within **Research**, group into collapsible sub-sections
(Testing, Evaluation, Data) so advanced items do not crowd the primary tasks.

---

## 9. Summary

- **39 templates** (1 root shell, 2 auth, 1 landing, 1 dashboard shell,
  30 dashboard pages, 4 partials).
- **5 pages bypass the dashboard shell** and must be folded in.
- **17 pages contain forms** (only one upload form, in `vision.html`).
- **4 templates use HTMX** (`base`, `index`, `vision_detail`, `vision_status`).
- **3 dashboard templates have inline `<script>`** (`index`, `vision_status`,
  and the terminal-state reset in `vision_status.html`).
- Every page listed above is a redesign target. None may be left on the old
  visual system, and none may lose a feature it currently exposes.
