# Frontend Design System

**Project:** Nazbeen Academy Binary Ai Asisstance
**Scope:** Phase B deliverable — tokens, build pipeline and component library
**Date:** 2026-10-20

This document is the specification for the visual system. The single source of
truth for tokens is [`tailwind.config.js`](../tailwind.config.js); the component
library lives in [`assets/css/components/`](../assets/css/components/) and is
compiled to [`static/css/app.css`](../static/css/app.css).

---

## 1. Build pipeline

The Tailwind **CDN build was removed**. The stylesheet is now compiled,
versioned and committed.

| Concern | Value |
|---|---|
| Build tool | Tailwind CSS `3.4.17` (Node dev dependency) |
| Source entry | `assets/css/tailwind.source.css` |
| Component sources | `assets/css/components/*.css` (imported by the entry) |
| Config | `tailwind.config.js` |
| **Committed output** | `static/css/app.css` (minified, ~92 KB) |
| Dev build | `npm run build:css:dev` (unminified) |
| Watch | `npm run watch:css` |

Commands (npm is invoked as `npm.cmd` on Windows where the PowerShell execution
policy blocks `npm.ps1`):

```powershell
npm install
npm run build:css      # production, minified -> static/css/app.css
```

The output is committed because `CompressedManifestStaticFilesStorage` hashes
assets at `collectstatic` time, and production must build without Node.

**HTMX is vendored** at `static/vendor/htmx.min.js` (1.9.12) — no public CDN.

---

## 2. Design tokens

All tokens are defined in `tailwind.config.js` under `theme.extend`.

### 2.1 Colour

**Brand — refined violet (primary accent).**

| Token | Value | Use |
|---|---|---|
| `brand-50` | `#f4f2ff` | soft brand surfaces, active nav background |
| `brand-500` | `#7c56f6` | focus ring, progress |
| `brand-600` | `#6d3ceb` | **primary buttons, brand marks** |
| `brand-700` | `#5c2bd0` | active/pressed, brand text on light |
| `brand-950` | `#261254` | dark-theme brand surfaces |

**Accent — subtle cyan (secondary).** `accent-50 … accent-950`, cyan ramp; used
sparingly for data-viz series and info affordances.

**Surfaces — deep navy / charcoal (dark-first).**

| Token | Value | Use |
|---|---|---|
| `surface-light` | `#ffffff` | light card background |
| `surface-light-muted` | `#f6f7fb` | light page background |
| `surface-light-sunken` | `#eef0f7` | light inset wells |
| `surface-light-border` | `#e2e5ef` | light borders |
| `surface-dark` | `#0b1020` | dark page background (deep navy) |
| `surface-dark-raised` | `#131a2e` | dark cards / sidebar |
| `surface-dark-overlay` | `#1b2440` | dark menus / modals |
| `surface-dark-border` | `#28324f` | dark borders |

**Semantic status.** Each status maps to exactly one meaning everywhere:

| Status | Meaning | Tokens |
|---|---|---|
| `success` | confirmed / verified / passed | `status-success*` (emerald) |
| `warning` | needs attention / experimental | `status-warning*` (amber) |
| `danger` | error / failed / destructive | `status-danger*` (rose) |
| `info` | neutral information | `status-info*` (sky) |
| `neutral` | inactive / unknown / not configured | `status-neutral*` (slate) |

Each status exposes a solid (`status-success`), a foreground (`status-success-fg`),
a soft background for light (`status-success-soft`) and dark
(`status-success-dark-soft`) plus a dark-mode foreground (`status-success-dark`).

### 2.2 Typography

Font: **Inter** (falls back to the system sans stack); monospace for candle /
data figures.

Type scale (custom sizes layered on Tailwind's):

| Utility | Size / line-height | Use |
|---|---|---|
| `text-display` | 2.5rem / 1.1, 700 | landing hero |
| `text-title` | 1.75rem / 1.2, 700 | page titles |
| `text-heading` | 1.125rem / 1.35, 600 | card / section headings |
| `text-eyebrow` | 0.75rem / 1.2, 600, +0.08em | section labels, page eyebrows |
| `text-caption` | 0.75rem / 1.4 | captions, table headers, help text |

### 2.3 Spacing, radius, elevation

- Spacing: Tailwind's 4 px scale plus `18` (4.5rem), `88` (22rem).
- Radius: `sm` 6px · DEFAULT 10px · `md` 12px · `lg` 16px · `xl` 20px · `2xl` 24px.
- Shadows (restrained): `xs`, `sm`, `card`, `raised`, `overlay`, `focus-brand`,
  `dark-card`, `dark-raised`.

### 2.4 Motion

| Token | Value |
|---|---|
| `duration-fast` | 120 ms |
| `duration-base` | 180 ms |
| `duration-slow` | 280 ms |
| `ease-standard` | `cubic-bezier(0.2, 0, 0, 1)` |

Animations: `animate-fade-in`, `animate-slide-up`, `animate-scale-in`,
`animate-shimmer`, `animate-pulse-soft`, `animate-spin-slow`. All are disabled
under `prefers-reduced-motion: reduce` (enforced globally in the base layer).

### 2.5 Breakpoints

`xs` 420 · `sm` 640 · `md` 768 · `lg` 1024 · `xl` 1280 · `2xl` 1440 (px).
The shell switches from the off-canvas drawer to the fixed sidebar at `lg`.

---

## 3. Component library

Classes live in `assets/css/components/` and are emitted via the Tailwind
`safelist`, so the whole system is present even before a page adopts it.

### Buttons (`buttons.css`)
`.btn` + one of `.btn-primary` · `.btn-secondary` · `.btn-ghost` ·
`.btn-danger` · `.btn-danger-subtle` · `.btn-link`; sizes `.btn-sm`, `.btn-lg`,
`.btn-icon`.

### Surfaces (`surfaces.css`)
`.card` / `.card-body` / `.card-header` / `.card-title` / `.card-subtitle` /
`.card-interactive`; page headers (`.page-header`, `.page-eyebrow`,
`.page-title`, `.page-description`); `.metric` family; badges (`.badge-success`
… `.badge-brand`); status dots (`.status-dot-*`); `.breadcrumbs`;
`.empty-state` family; `.error-state`; notices (`.notice-info` … `.notice-neutral`).

### Forms (`forms.css`)
`.form-label` · `.form-help` · `.form-error` · `.form-control` (with
`.form-control-error`) · `.form-select` · `.form-textarea` · `.form-checkbox` ·
`.form-radio` · `.form-file` · `.form-group` / `.form-row` / `.form-actions` ·
`.form-prose` (styles raw `{{ form.as_p }}` output) · `.upload-area` (with
`.is-dragover` / `.is-invalid`) · `.progress` / `.progress-bar` /
`.progress-bar-indeterminate`.

### Navigation (`navigation.css`)
`.app-shell` · `.sidebar` (`.is-open`) · `.sidebar-brand` · `.sidebar-nav` ·
`.nav-group-label` · `.nav-item` (`aria-current="page"` = active) · `.topbar` ·
`.main-content` · `.shell-body` · `.drawer-scrim` · `.tabs` / `.tab` · `.menu` /
`.menu-item` / `.menu-divider` · `.site-header` / `.site-nav-link`.

### Feedback (`feedback.css`)
`.toast-region` / `.toast-*` · `.skeleton` / `.skeleton-text` /
`.skeleton-title` · `.spinner` · `.tooltip` · `.dialog` family · `.disclosure` ·
`.live-region`.

### Data (`data.css`)
`.table` (+ `.table-numeric`) · `.table-card` · `.table-wrapper` ·
`.table-responsive` (stacks rows into labelled cards under 640 px) ·
`.pagination` / `.page-link` · `.chart-container` / `.chart-title` /
`.chart-canvas` / `.chart-empty` · `.kv-list` / `.kv-row`.

### Utilities (`tailwind.source.css`)
`.skip-link` · `.visually-hidden` · `.table-scroll` · `.htmx-indicator` ·
`.stagger` (staggered entrance).

---

## 4. Icons

An inline SVG sprite at `templates/partials/icons.html` (rendered once in
`base.html`) provides ~55 single-stroke icons that inherit `currentColor`.
Usage:

```html
<svg class="h-5 w-5" aria-hidden="true"><use href="#icon-dashboard"></use></svg>
```

Decorative icons always carry `aria-hidden="true"`; icon-only controls carry an
`aria-label`.

---

## 5. JavaScript

Two small, dependency-free files, both `defer`-loaded:

- `static/js/theme.js` — light/dark toggle, cookie + localStorage persistence,
  `aria-pressed` sync, no flash on repeat visits.
- `static/js/ui.js` — toast API (`window.nazbeen.toast`), mobile drawer, desktop
  sidebar collapse (persisted), dropdown menus, pending-submit state, drag &
  drop upload zones, dismissible elements.

Everything is progressive enhancement: with JavaScript disabled, all forms still
submit and all navigation still works.

---

## 6. Accessibility rules baked into the system

- Global `:focus-visible` ring using the brand accent and a surface-matched offset.
- `.skip-link` to `#main-content`; `<main id="main-content">` on every shell.
- Semantic status colours are paired with text, never colour alone.
- `prefers-reduced-motion` disables all animation/transition globally.
- Tables use `<caption>`/`scope`; `.table-responsive` gives mobile a labelled
  card layout instead of horizontal overflow.
- HTMX/async regions use `aria-live` (`role="status"` / `role="alert"`).
- Nav links expose `aria-current="page"`; the drawer toggle exposes
  `aria-expanded`; the theme toggle exposes `aria-pressed`.

---

## 7. Theme behaviour

Dark-first: `DEFAULT_THEME = "dark"` in `apps/core/context_processors.py`, so
`<html>` renders with `class="dark"` on first visit. The cookie `theme` is
authoritative on the server; `localStorage` smooths the first paint. Both themes
are first-class and use the same component classes.
