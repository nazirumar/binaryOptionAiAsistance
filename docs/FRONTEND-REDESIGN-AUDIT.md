# Frontend Redesign — Audit

**Project:** Nazbeen Academy Binary Ai Asisstance
**Scope:** Complete frontend / UX audit (Phase A of the frontend redesign)
**Date:** 2026-10-20
**Backend:** unchanged (this document is read-only reconnaissance)

---

## 1. Method

Every frontend artefact was inspected:

- all `templates/**/*.html` (39 files) — see `docs/FRONTEND-PAGE-INVENTORY.md`
- `static/css/app.css`, `static/js/theme.js`
- the template context processor (`apps/core/context_processors.py`)
- `config/settings/base.py` (static/template/storage configuration)
- `config/urls.py` and `apps/dashboard/urls.py`, `apps/accounts/urls.py`
- every test that asserts on rendered HTML, so a redesign cannot silently
  break behaviour: `tests/test_pages.py`, `tests/test_phase11_frontend.py`,
  `tests/test_book_strategies.py`, `tests/test_phase12_knowledge.py`,
  `tests/test_phase10_integration_e2e.py`, `tests/test_phase11_e2e.py`,
  `tests/test_phase10_uat.py`.

Baseline test run before any change: **1239 passed, 3 skipped**.

---

## 2. Current technical stack (verified)

| Concern | Current state | File / evidence |
|---|---|---|
| CSS framework | **Tailwind via CDN** (`https://cdn.tailwindcss.com`) | `templates/base.html:11-14` |
| Tailwind config | inline `tailwind.config` object (darkMode only) | `templates/base.html:11-13` |
| Project CSS | 39-line override file | `static/css/app.css` |
| JS | one file, theme toggle only | `static/js/theme.js` |
| HTMX | CDN `htmx.org@1.9.12` | `templates/base.html:18` |
| Icons | inline hand-written SVG (one icon only) | `templates/partials/theme_toggle.html` |
| Static storage | `CompressedManifestStaticFilesStorage` | `config/settings/base.py:310-315` |
| Static dirs | `static/` | `config/settings/base.py:302-304` |
| Template dirs | central `templates/` | `config/settings/base.py:237` |
| Node build | **none** (no `package.json`; `node`/`npm` available on the host) | repo root |
| Theme | class-based `dark` on `<html>`, server-rendered from cookie, `DEFAULT_THEME="dark"` | `context_processors.py`, `theme.js` |

### Critical blockers found

1. **Tailwind CDN in production.** `cdn.tailwindcss.com` compiles CSS in the
   browser, is explicitly "for development purposes only", blocks
   `Content-Security-Policy` hardening, and adds a large external runtime
   dependency. Must be replaced with a compiled, versioned, committed build.
2. **HTMX from a public CDN** with no integrity pin — should be vendored.
3. **No design tokens.** Every colour (`slate-*`, `indigo-*`, `emerald-*`,
   `amber-*`, `red-*`) is hard-coded inline across 39 templates. There is no
   single source of truth for brand colour, spacing, radius, or elevation.
4. **Two parallel navigation systems.** `base.html` renders a top nav
   (Dashboard/Screenshots/Sync/Journal/Reports/Settings) *and*
   `dashboard/layout.html` renders a sidebar with a different, larger set of
   links. They disagree, and the top bar is duplicated on every dashboard page.
5. **Five dashboard-area pages bypass the dashboard shell** and extend
   `base.html` directly (`vision`, `vision_detail`, `sync`, `sync_detail`,
   `mt5`) — so they have no sidebar, no breadcrumb, and the top nav instead.
6. **Brand accent is `indigo-600`** with no defined premium palette; there is
   no violet/cyan accent system, no semantic status token set.

---

## 3. Findings against the twelve audit questions

### 3.1 Outdated designs
- Generic "bootstrap-like" card grid (`rounded-xl border bg-white/900 p-4/5`)
  repeated verbatim across all 30 dashboard pages.
- Single `text-2xl font-bold` page title, no eyebrow/context, no actions row.
- The dashboard index still shows a **"Project roadmap"** grid of phases —
  internal build metadata presented as a user feature.
- Only two icons exist in the whole app (sun/moon); everything else is text.

### 3.2 Duplicate navigation
- `base.html` top nav repeats six destinations that also appear in the
  sidebar, on every authenticated dashboard page (confirmed both are rendered).
- `dashboard/index.html` links "MT5 market data" and "Screenshot vision" as
  large cards while the sidebar already lists the same destinations.

### 3.3 Crowded layouts
- `book_research.html` (241 lines) and `forward_testing.html` (143 lines)
  pack many unrelated metric tables onto one page with no tabs or sections.
- `dashboard/index.html` stacks status card → metrics → quick links → roadmap
  with no grouping or progressive disclosure.

### 3.4 Poor visual hierarchy
- Page title, section headings (`font-semibold`) and metric labels all use
  similar weights/sizes; there is no type scale.
- Metric values, labels and captions differ card-to-card with no consistent
  metric-card component.

### 3.5 Inconsistent colours and spacing
- Card padding alternates between `p-4` and `p-5`; gaps alternate between
  `gap-3` and `gap-4`; margins between `mt-1/mt-2/mt-3/mt-4`.
- Status colours are ad-hoc per template (emerald/amber/red/slate/indigo) with
  no shared mapping of *status → colour*.

### 3.6 Unclear buttons and actions
- Primary action button styling (`bg-indigo-600 … hover:bg-indigo-500`) is
  copy-pasted and differs in padding/radius from page to page.
- Destructive actions (`Delete account`, journal `Delete`) are rendered as
  ordinary links/buttons with no danger styling or confirmation dialog.
- `journal_form.html` renders the raw `{{ form.as_p }}` — unstyled browser
  controls inconsistent with the rest of the app.

### 3.7 Missing loading states
- No skeletons except one `animate-pulse` line in `dashboard/index.html`.
- The vision detail page relies on HTMX polling with no visible progress stage
  or stage indicator; the only feedback is a status pill.
- Buttons that trigger POSTs have no pending/disabled state.

### 3.8 Confusing error messages
- Errors surface as plain flash banners (`base.html:52-60`) with identical
  neutral styling for success and failure.
- `book_research.html` / `forward_testing.html` render raw `None`/`—` values
  with little explanation of *why* a metric is unavailable.

### 3.9 Weak mobile responsiveness
- The sidebar in `dashboard/layout.html` collapses to a full-width block at the
  top of the page on mobile (it is not a drawer) — it pushes all content down.
- Wide tables (analyses, journal, sync, mt5, vision) have no mobile behaviour:
  no horizontal scroll wrapper, no stacked-card fallback → horizontal overflow.
- The top nav has no hamburger; six text links wrap awkwardly on small screens.

### 3.10 Unused components
- No reusable template partials for buttons/cards/badges — everything is
  inlined. `partials/theme_toggle.html` is the only shared component.
- `static/css/app.css` scrollbar and htmx-indicator rules are largely unused
  because no template uses the `.htmx-indicator` class.

### 3.11 Accessibility problems
- No skip-to-content link; no `<main>` landmark id.
- Nav links lack `aria-current` for the active page.
- The theme toggle has `aria-label` (good) but no `aria-pressed` state.
- Icon-only and glyph buttons ("←", "→", "×") are used as decorative text.
- No visible `:focus-visible` ring system; relies on browser default.
- Tables lack `<caption>`/`scope` in several places.
- No `aria-live` region for HTMX-driven updates (status card, vision status).
- No `prefers-reduced-motion` handling anywhere.

### 3.12 Missing or misleading feature descriptions
- Landing page (`core/home.html`) describes only three generic cards; it never
  explains the screenshot → analysis → verification workflow, the strategy
  library, or the research limitations.
- `dashboard/index.html` "Project roadmap" implies a build schedule rather than
  describing platform capability.
- Several research pages present experimental strategies next to validated ones
  without a persistent "not approved for decisions" affordance (some pages have
  it, e.g. `book_strategies.html` "Not approved for decisions"; others do not).

---

## 4. Constraints that govern the redesign

These are hard requirements discovered during the audit and must be honoured in
every later phase:

### 4.1 Rendered-text contracts enforced by tests
A redesign **must not** remove or rename these visible strings:

| String | Test |
|---|---|
| `Nazbeen Academy` | `test_pages.py::test_home_page_renders_for_anonymous` |
| display name in dashboard (`Dashboard Tester`) | `test_pages.py::test_dashboard_renders_for_user` |
| `System status` | `test_pages.py::test_status_fragment_renders` |
| `Offline mock`, `no live model configured` | `test_pages.py::test_status_fragment_reports_the_real_vision_state` |
| `not configured (missing API key, model)` | `test_pages.py::…missing_credentials` |
| `Critical integration remediation`, and `Planned` **absent** | `test_pages.py::test_dashboard_roadmap_is_up_to_date` |
| `MT5 market data`, masked login `*******21` | `test_pages.py::test_mt5_dashboard_renders_with_market_data` |
| `class="dark"` on `<html>` for default theme | `test_pages.py::test_theme_cookie_controls_initial_theme` |
| `Analysis`, `Screenshot #` | `test_phase11_frontend.py` |
| `Assessment`, `MT5 verification`, `Calibration`, `Probability unavailable`, `model not calibrated`, `Evidence`, `Sync status`, `NO TRADE`, `Decision reasons` | `test_phase11_frontend.py` |
| `No conversations yet` | `test_phase11_frontend.py::test_cp12_empty_states` |
| `Calibration status` | `test_phase11_frontend.py` |
| `Book strategies`, `Rising Three Method`, `Not approved for decisions` | `test_book_strategies.py` |
| `Bullish engulfing setup`, `Experimental`, `not validated`, `Prior bearish candle` | `test_phase12_knowledge.py` |

> The `class="dark"` assertion means the `<html>` element must keep its exact
> `class="dark"` attribute form (a bare `class="dark"` substring). Collapsing it
> to e.g. `class="dark "` or reordering attributes is fine as long as the exact
> substring `class="dark"` remains.

### 4.2 Backend contracts
- `{% url %}` names and view signatures are frozen.
- HTMX endpoints (`dashboard:status`, `dashboard:vision-status`) and their CSRF
  wiring (`hx-headers` on `<body>`) must keep working.
- File upload (`dashboard:vision-upload`, multipart, field name `image`) stays.
- Permissions: every dashboard route stays `login_required`; owner-scoping and
  404 behaviour stay unchanged.
- No fabricated metrics: every number rendered must come from a real service.

### 4.3 Asset pipeline contract
- `CompressedManifestStaticFilesStorage` hashes assets, so **every** asset must
  be referenced with `{% static %}` and must exist at `collectstatic` time.
- The new compiled CSS must be a committed file under `static/` (or its build
  output must be committed) so production `collectstatic` works with no Node at
  deploy time.

---

## 5. Pages that bypass the shell (must be folded in)

| Template | Currently extends | Should live in |
|---|---|---|
| `dashboard/vision.html` | `base.html` | dashboard shell |
| `dashboard/vision_detail.html` | `base.html` | dashboard shell |
| `dashboard/sync.html` | `base.html` | dashboard shell |
| `dashboard/sync_detail.html` | `base.html` | dashboard shell |
| `dashboard/mt5.html` | `base.html` | dashboard shell |

> Folding these in is a **structural** change only; their content, forms, HTMX
> targets (`#vision-status`) and asserted strings must be preserved.

---

## 6. Audit conclusion

The application is functionally complete but visually immature: a single CDN
Tailwind setup, one 39-line stylesheet, one JS file, ~14 copy-pasted utility
patterns, two competing navigations, five orphaned pages, and no component or
token layer. The redesign therefore proceeds in this order:

1. **Design system** — tokens + compiled Tailwind + component partials (Phase B).
2. **Application shell** — one collapsible sidebar, compact top bar, breadcrumbs,
   mobile drawer; fold the five orphaned pages into the shell (Phase C).
3. **Screenshot analysis** — highest-priority workspace (Phase D1).
4. **Dashboard + AI assistant** (Phase D2).
5. **Strategy + research pages** (Phase D3).
6. **Remaining pages + public site + auth** (Phase D4/D5).
7. **Animation, responsiveness, accessibility, integration, tests, docs.**

No backend model, service, view signature, URL name or asserted string will be
changed. See `docs/FRONTEND-PAGE-INVENTORY.md` for the full page list and
`docs/FRONTEND-DESIGN-SYSTEM.md` for the token/component specification.
