/**
 * Tailwind configuration — Nazbeen Academy Binary Ai Asisstance design system.
 *
 * This is the single source of truth for the compiled stylesheet. Design
 * tokens live here and in `assets/css/tailwind.source.css`; component classes
 * live in `assets/css/components/`.
 *
 * The build output is `static/css/app.css`, which is committed so that
 * production `collectstatic` works without Node present at deploy time.
 *
 * @type {import('tailwindcss').Config}
 */
const colors = require("tailwindcss/colors");

/** Semantic status hues resolve to a single meaning across the whole app. */
const statusColors = {
  success: colors.emerald,
  warning: colors.amber,
  danger: colors.rose,
  info: colors.sky,
  neutral: colors.slate,
};

module.exports = {
  // Class-based dark mode keeps `class="dark"` on <html>, which the server
  // renders from the theme cookie and a test asserts on.
  darkMode: "class",

  content: [
    "./templates/**/*.html",
    "./apps/**/templates/**/*.html",
    "./static/js/**/*.js",
  ],

  // The component layer is authored as @apply rules, so the classes it defines
  // must always be emitted even before a template references them. This keeps
  // the design system complete and prevents "class exists in CSS but not in the
  // build" drift.
  safelist: [
    // Buttons
    "btn",
    "btn-primary",
    "btn-secondary",
    "btn-ghost",
    "btn-danger",
    "btn-danger-subtle",
    "btn-sm",
    "btn-lg",
    "btn-icon",
    "btn-link",
    // Surfaces
    "card",
    "card-body",
    "card-header",
    "card-title",
    "card-subtitle",
    "card-interactive",
    "card-hover",
    "icon-badge",
    "page-header",
    "page-eyebrow",
    "page-title",
    "page-description",
    "section-header",
    "section-title",
    "metric",
    "metric-label",
    "metric-value",
    "metric-value-sm",
    "metric-caption",
    "badge",
    "badge-success",
    "badge-warning",
    "badge-danger",
    "badge-info",
    "badge-neutral",
    "badge-brand",
    "status-dot",
    "status-dot-success",
    "status-dot-warning",
    "status-dot-danger",
    "status-dot-info",
    "status-dot-neutral",
    "status-dot-pulse",
    "status-pill",
    "status-pill-success",
    "status-pill-warning",
    "status-pill-danger",
    "status-pill-info",
    "status-pill-neutral",
    "meta-strip",
    "meta-item",
    "meta-key",
    "meta-value",
    "hero-glow",
    "breadcrumbs",    "empty-state",
    "empty-state-icon",
    "empty-state-title",
    "empty-state-text",
    "error-state",
    "notice",
    "notice-info",
    "notice-warning",
    "notice-success",
    "notice-danger",
    "notice-brand",
    "notice-neutral",
    // Forms
    "form-label",
    "form-help",
    "form-error",
    "form-control",
    "form-control-error",
    "form-select",
    "form-textarea",
    "form-checkbox",
    "form-radio",
    "form-file",
    "form-group",
    "form-row",
    "form-actions",
    "form-prose",
    "upload-area",
    "upload-area-icon",
    "is-dragover",
    "is-invalid",
    "progress",
    "progress-bar",
    "progress-bar-indeterminate",
    // Navigation
    "app-shell",
    "sidebar",
    "sidebar-brand",
    "sidebar-nav",
    "sidebar-brand-text",
    "nav-group-label",
    "nav-item",
    "nav-item-label",
    "topbar",
    "main-content",
    "shell-body",
    "drawer-scrim",
    "tabs",
    "tab",
    "menu",
    "menu-item",
    "menu-divider",
    "site-header",
    "site-nav-link",
    "is-open",
    "is-visible",
    "is-active",
    // Feedback
    "toast-region",
    "toast",
    "toast-success",
    "toast-error",
    "toast-info",
    "toast-title",
    "toast-text",
    "toast-close",
    "skeleton",
    "skeleton-text",
    "skeleton-title",
    "spinner",
    "spinner-lg",
    "tooltip",
    "dialog",
    "dialog-title",
    "dialog-text",
    "dialog-actions",
    "disclosure",
    "disclosure-body",
    "live-region",
    // Data
    "table",
    "table-numeric",
    "table-card",
    "table-wrapper",
    "table-responsive",
    "pagination",
    "pagination-meta",
    "pagination-controls",
    "page-link",
    "chart-container",
    "chart-title",
    "chart-canvas",
    "chart-empty",
    "kv-list",
    "kv-row",
    "kv-key",
    "kv-value",
    // Utilities defined in the source stylesheet
    "skip-link",
    "visually-hidden",
    "table-scroll",
    "htmx-indicator",
    "stagger",
  ],

  theme: {
    extend: {
      colors: {
        // --- Brand: refined violet primary, subtle cyan secondary ---------
        brand: {
          50: "#f4f2ff",
          100: "#ebe6ff",
          200: "#d9d1ff",
          300: "#bcacff",
          400: "#9b80ff",
          500: "#7c56f6",
          600: "#6d3ceb",
          700: "#5c2bd0",
          800: "#4c25aa",
          900: "#40228a",
          950: "#261254",
        },
        accent: {
          50: "#ecfeff",
          100: "#cffafe",
          200: "#a5f3fc",
          300: "#67e8f9",
          400: "#22d3ee",
          500: "#06b6d4",
          600: "#0891b2",
          700: "#0e7490",
          800: "#155e75",
          900: "#164e63",
          950: "#083344",
        },

        // --- Surfaces: deep navy / charcoal, dark-first ---------------------
        // Used for page background, raised panels and borders so that both
        // themes share one structural vocabulary.
        surface: {
          light: "#ffffff",
          "light-muted": "#f6f7fb",
          "light-sunken": "#eef0f7",
          dark: "#0b1020", // deep navy page background
          "dark-raised": "#131a2e", // raised panels / cards
          "dark-overlay": "#1b2440", // popovers, menus, modals
          "dark-border": "#28324f",
          "light-border": "#e2e5ef",
        },

        // --- Semantic status (each has a soft background + strong fg) ------
        status: {
          success: statusColors.success[500],
          "success-fg": statusColors.success[700],
          "success-soft": statusColors.success[50],
          "success-dark": statusColors.success[300],
          "success-dark-soft": "rgba(16,185,129,0.12)",

          warning: statusColors.warning[500],
          "warning-fg": statusColors.warning[700],
          "warning-soft": statusColors.warning[50],
          "warning-dark": statusColors.warning[300],
          "warning-dark-soft": "rgba(245,158,11,0.12)",

          danger: statusColors.danger[500],
          "danger-fg": statusColors.danger[700],
          "danger-soft": statusColors.danger[50],
          "danger-dark": statusColors.danger[300],
          "danger-dark-soft": "rgba(244,63,94,0.12)",

          info: statusColors.info[500],
          "info-fg": statusColors.info[700],
          "info-soft": statusColors.info[50],
          "info-dark": statusColors.info[300],
          "info-dark-soft": "rgba(14,165,233,0.12)",

          neutral: statusColors.neutral[400],
          "neutral-fg": statusColors.neutral[600],
          "neutral-soft": statusColors.neutral[100],
          "neutral-dark": statusColors.neutral[300],
          "neutral-dark-soft": "rgba(148,163,184,0.12)",
        },
      },

      // --- Typography ------------------------------------------------------
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "JetBrains Mono",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      fontSize: {
        // A restrained scale: display / title / heading / body / caption.
        display: ["2.5rem", { lineHeight: "1.1", letterSpacing: "-0.02em", fontWeight: "700" }],
        title: ["1.75rem", { lineHeight: "1.2", letterSpacing: "-0.01em", fontWeight: "700" }],
        heading: ["1.125rem", { lineHeight: "1.35", fontWeight: "600" }],
        eyebrow: ["0.75rem", { lineHeight: "1.2", letterSpacing: "0.08em", fontWeight: "600" }],
        caption: ["0.75rem", { lineHeight: "1.4" }],
      },

      // --- Spacing / sizing helpers ---------------------------------------
      spacing: {
        18: "4.5rem",
        88: "22rem",
        sidebar: "16rem",
        "sidebar-collapsed": "4.5rem",
        topbar: "3.5rem",
      },

      // --- Border radius ---------------------------------------------------
      borderRadius: {
        sm: "0.375rem",
        DEFAULT: "0.625rem",
        md: "0.75rem",
        lg: "1rem",
        xl: "1.25rem",
        "2xl": "1.5rem",
      },

      // --- Shadows / elevation (restrained) --------------------------------
      boxShadow: {
        xs: "0 1px 2px 0 rgb(15 23 42 / 0.05)",
        sm: "0 1px 3px 0 rgb(15 23 42 / 0.08), 0 1px 2px -1px rgb(15 23 42 / 0.06)",
        card: "0 1px 3px 0 rgb(15 23 42 / 0.06), 0 1px 2px -1px rgb(15 23 42 / 0.05)",
        raised: "0 8px 24px -12px rgb(15 23 42 / 0.18)",
        overlay: "0 16px 48px -16px rgb(2 6 23 / 0.35)",
        "focus-brand": "0 0 0 3px rgba(124,86,246,0.35)",
        "dark-card": "0 1px 3px 0 rgb(0 0 0 / 0.4)",
        "dark-raised": "0 12px 32px -16px rgb(0 0 0 / 0.65)",
      },

      // --- Animation timing -------------------------------------------------
      transitionTimingFunction: {
        standard: "cubic-bezier(0.2, 0, 0, 1)",
        emphasized: "cubic-bezier(0.2, 0, 0, 1)",
      },
      transitionDuration: {
        fast: "120ms",
        base: "180ms",
        slow: "280ms",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "scale-in": {
          from: { opacity: "0", transform: "scale(0.97)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
        "spin-slow": {
          to: { transform: "rotate(360deg)" },
        },
      },
      animation: {
        "fade-in": "fade-in 180ms cubic-bezier(0.2,0,0,1) both",
        "slide-up": "slide-up 220ms cubic-bezier(0.2,0,0,1) both",
        "scale-in": "scale-in 160ms cubic-bezier(0.2,0,0,1) both",
        shimmer: "shimmer 1.6s infinite",
        "pulse-soft": "pulse-soft 1.8s cubic-bezier(0.4,0,0.6,1) infinite",
        "spin-slow": "spin-slow 1.2s linear infinite",
      },

      // --- Breakpoints ------------------------------------------------------
      screens: {
        xs: "420px",
        sm: "640px",
        md: "768px",
        lg: "1024px",
        xl: "1280px",
        "2xl": "1440px",
      },

      // --- Charts / data ----------------------------------------------------
      maxWidth: {
        prose: "68ch",
        workspace: "90rem",
      },
    },
  },

  plugins: [],
};
