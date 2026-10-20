// Nazbeen Academy — shared UI behaviours.
//
// Loaded after theme.js on every page. Everything here is progressive
// enhancement: if this file fails to load, every page still works (forms
// submit, links navigate). Features:
//
//   * toast notifications            window.nazbeen.toast(...)
//   * mobile sidebar drawer          [data-sidebar-toggle], [data-drawer-scrim]
//   * desktop sidebar collapse       persisted in localStorage
//   * dropdown / profile menu        [data-menu-toggle]
//   * submit pending state           form[data-pending] buttons
//   * drag-and-drop upload area      [data-upload-zone]
//   * dismissible disclosures        [data-dismiss]
//
// No framework, no network calls, no build step.
(function () {
  "use strict";

  var STORAGE_KEY = "nazbeen:ui";

  function readPrefs() {
    try {
      return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}");
    } catch (err) {
      return {};
    }
  }

  function writePrefs(prefs) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch (err) {
      /* ignore (private mode) */
    }
  }

  /* ---------------------------------------------------------------- *
   * Toast notifications
   * ---------------------------------------------------------------- */
  var ICONS = {
    success: "icon-check-circle",
    error: "icon-alert-circle",
    info: "icon-info",
  };

  function toast(message, options) {
    var opts = options || {};
    var kind = opts.kind === "error" || opts.kind === "success" ? opts.kind : "info";
    var region = document.getElementById("toast-region");
    if (!region) {
      return;
    }

    var node = document.createElement("div");
    node.className = "toast toast-" + kind;
    node.setAttribute("role", kind === "error" ? "alert" : "status");

    var icon = document.createElement("svg");
    icon.setAttribute("class", "h-5 w-5 shrink-0");
    icon.setAttribute("aria-hidden", "true");
    var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#" + (ICONS[kind] || ICONS.info));
    icon.appendChild(use);

    var body = document.createElement("div");
    body.className = "min-w-0";
    if (opts.title) {
      var title = document.createElement("p");
      title.className = "toast-title";
      title.textContent = opts.title;
      body.appendChild(title);
    }
    var text = document.createElement("p");
    text.className = "toast-text";
    text.textContent = message;
    body.appendChild(text);

    var close = document.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("aria-label", "Dismiss notification");
    close.innerHTML =
      '<svg class="h-4 w-4" aria-hidden="true"><use href="#icon-close"></use></svg>';
    close.addEventListener("click", function () {
      node.remove();
    });

    node.appendChild(icon);
    node.appendChild(body);
    node.appendChild(close);
    region.appendChild(node);

    var ttl = typeof opts.duration === "number" ? opts.duration : 5000;
    if (ttl > 0) {
      window.setTimeout(function () {
        node.remove();
      }, ttl);
    }
  }

  /* ---------------------------------------------------------------- *
   * Sidebar drawer (mobile) + collapse (desktop)
   * ---------------------------------------------------------------- */
  var shell = document.querySelector("[data-app-shell]");
  var sidebar = document.getElementById("app-sidebar");
  var scrim = document.querySelector("[data-drawer-scrim]");

  function setDrawer(open) {
    if (!sidebar || !scrim) {
      return;
    }
    sidebar.classList.toggle("is-open", open);
    scrim.classList.toggle("is-visible", open);
    scrim.setAttribute("aria-hidden", open ? "false" : "true");
    document.querySelectorAll("[data-sidebar-toggle]").forEach(function (btn) {
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    if (open) {
      var first = sidebar.querySelector("a, button");
      if (first) {
        first.focus();
      }
    }
  }

  if (scrim) {
    scrim.addEventListener("click", function () {
      setDrawer(false);
    });
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && sidebar && sidebar.classList.contains("is-open")) {
      setDrawer(false);
    }
  });

  document.querySelectorAll("[data-sidebar-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var desktop = window.matchMedia("(min-width: 1024px)").matches;
      if (desktop && shell) {
        var collapsed = shell.getAttribute("data-sidebar") === "collapsed";
        shell.setAttribute("data-sidebar", collapsed ? "expanded" : "collapsed");
        var prefs = readPrefs();
        prefs.sidebar = collapsed ? "expanded" : "collapsed";
        writePrefs(prefs);
      } else {
        setDrawer(!sidebar.classList.contains("is-open"));
      }
    });
  });

  // Restore the desktop collapse preference before first paint.
  if (shell) {
    var prefs = readPrefs();
    if (prefs.sidebar === "collapsed") {
      shell.setAttribute("data-sidebar", "collapsed");
    }
  }

  /* ---------------------------------------------------------------- *
   * Dropdown menus
   * ---------------------------------------------------------------- */
  document.querySelectorAll("[data-menu-toggle]").forEach(function (trigger) {
    var menuId = trigger.getAttribute("aria-controls");
    var menu = menuId ? document.getElementById(menuId) : null;
    if (!menu) {
      return;
    }
    trigger.addEventListener("click", function (event) {
      event.stopPropagation();
      var open = menu.hasAttribute("hidden");
      menu.toggleAttribute("hidden", !open);
      trigger.setAttribute("aria-expanded", open ? "true" : "false");
    });
  });

  document.addEventListener("click", function (event) {
    document.querySelectorAll("[data-menu]").forEach(function (menu) {
      if (menu.hasAttribute("hidden")) {
        return;
      }
      if (!menu.contains(event.target)) {
        menu.setAttribute("hidden", "");
        var trigger = document.querySelector('[aria-controls="' + menu.id + '"]');
        if (trigger) {
          trigger.setAttribute("aria-expanded", "false");
        }
      }
    });
  });

  /* ---------------------------------------------------------------- *
   * Pending submit state — prevents double-submits and shows progress
   * ---------------------------------------------------------------- */
  document.querySelectorAll("form[data-pending]").forEach(function (form) {
    form.addEventListener("submit", function () {
      if (form.dataset.submitting === "1") {
        return;
      }
      form.dataset.submitting = "1";
      form.querySelectorAll('button[type="submit"]').forEach(function (btn) {
        btn.setAttribute("aria-busy", "true");
        btn.setAttribute("disabled", "disabled");
      });
    });
  });

  /* ---------------------------------------------------------------- *
   * Dismissible elements
   * ---------------------------------------------------------------- */
  document.querySelectorAll("[data-dismiss]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var target = btn.closest("[data-dismissible]") || btn.parentElement;
      if (target) {
        target.remove();
      }
    });
  });

  /* ---------------------------------------------------------------- *
   * Drag & drop upload zones
   * ---------------------------------------------------------------- */
  document.querySelectorAll("[data-upload-zone]").forEach(function (zone) {
    var input = zone.querySelector('input[type="file"]');
    if (!input) {
      return;
    }

    function highlight(on) {
      zone.classList.toggle("is-dragover", on);
    }

    ["dragenter", "dragover"].forEach(function (evt) {
      zone.addEventListener(evt, function (event) {
        event.preventDefault();
        highlight(true);
      });
    });
    ["dragleave", "drop"].forEach(function (evt) {
      zone.addEventListener(evt, function (event) {
        event.preventDefault();
        highlight(false);
      });
    });
    zone.addEventListener("drop", function (event) {
      if (event.dataTransfer && event.dataTransfer.files.length) {
        input.files = event.dataTransfer.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });

    input.addEventListener("change", function () {
      var name = input.files && input.files[0] ? input.files[0].name : "";
      var label = zone.querySelector("[data-upload-filename]");
      if (label) {
        label.textContent = name;
      }
    });
  });

  /* ---------------------------------------------------------------- *
   * Public API
   * ---------------------------------------------------------------- */
  window.nazbeen = window.nazbeen || {};
  window.nazbeen.toast = toast;
})();
