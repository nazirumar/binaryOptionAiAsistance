// Light/dark theme switching.
//
// The server renders the initial `dark` class from the `theme` cookie (see the
// context processor). This script toggles the class, updates the cookie so the
// choice survives reloads, and mirrors the value into localStorage for a
// smoother first paint.
(function () {
  "use strict";

  var root = document.documentElement;

  function persist(theme) {
    document.cookie = "theme=" + theme + ";path=/;max-age=31536000;SameSite=Lax";
    try {
      window.localStorage.setItem("theme", theme);
    } catch (err) {
      /* localStorage may be unavailable (private mode); ignore. */
    }
  }

  function apply(theme) {
    root.classList.toggle("dark", theme === "dark");
    persist(theme);
  }

  // Apply the locally remembered theme before the toggle is even used, to
  // avoid a flash of the default theme on repeat visits.
  try {
    var remembered = window.localStorage.getItem("theme");
    if (remembered === "light" || remembered === "dark") {
      root.classList.toggle("dark", remembered === "dark");
    }
  } catch (err) {
    /* ignore */
  }

  document.addEventListener("DOMContentLoaded", function () {
    var button = document.getElementById("theme-toggle");
    if (!button) {
      return;
    }
    button.addEventListener("click", function () {
      apply(root.classList.contains("dark") ? "light" : "dark");
    });
  });
})();
