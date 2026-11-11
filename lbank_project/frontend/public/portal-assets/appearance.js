/* TITANIUM IRIS: pre-paint controller shared by Next.js, the terminal and offline UI.
   Only a non-sensitive appearance enum is persisted. Never store session/API data. */
(function () {
  "use strict";
  if (window.TradeAppearance) return;
  var key = "trade.appearance";
  var root = document.documentElement;
  var media = window.matchMedia("(prefers-color-scheme: dark)");
  var valid = function (value) {
    return value === "dark" || value === "light" || value === "system";
  };
  var preference = "dark";
  try {
    var saved = localStorage.getItem(key);
    if (valid(saved)) preference = saved;
  } catch (_) {}
  function apply() {
    var resolved =
      preference === "system" ? (media.matches ? "dark" : "light") : preference;
    root.setAttribute("data-theme", resolved);
    root.setAttribute("data-appearance", preference);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta)
      meta.setAttribute("content", resolved === "dark" ? "#0C101B" : "#F7F6FA");
    document
      .querySelectorAll("select[data-legacy-theme-switch]")
      .forEach(function (select) {
        select.value = preference;
      });
    window.dispatchEvent(new Event("trade:appearancechange"));
  }
  window.TradeAppearance = {
    getPreference: function () {
      return preference;
    },
    setPreference: function (value) {
      if (!valid(value)) return;
      preference = value;
      try {
        localStorage.setItem(key, value);
      } catch (_) {}
      apply();
    },
    subscribe: function (listener) {
      window.addEventListener("trade:appearancechange", listener);
      return function () {
        window.removeEventListener("trade:appearancechange", listener);
      };
    },
  };
  media.addEventListener("change", function () {
    if (preference === "system") apply();
  });
  window.addEventListener("storage", function (event) {
    if (event.key === key || event.key === null) {
      preference = valid(event.newValue) ? event.newValue : "dark";
      apply();
    }
  });
  document.addEventListener("change", function (event) {
    if (
      event.target.matches &&
      event.target.matches("select[data-legacy-theme-switch]")
    )
      window.TradeAppearance.setPreference(event.target.value);
  });
  document.addEventListener("DOMContentLoaded", apply, { once: true });
  apply();
})();
