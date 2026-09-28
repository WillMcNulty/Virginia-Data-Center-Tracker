// Color theme: Auto (follows the device), Light or Dark. Loaded in <head> so the page never flashes the wrong
// theme. The choice is kept only in this browser, under one key shared by every willmcnulty.github.io page
// (portfolio, demos, trackers), so picking Dark once applies everywhere. Any button with the
// data-theme-toggle attribute cycles Auto -> Light -> Dark. Pages that draw with JavaScript (charts, maps)
// listen for the "themechange" event, which carries the effective theme ("light" or "dark").
(function () {
  var KEY = "wm-theme", MODES = ["auto", "light", "dark"];
  var LABEL = { auto: "◐ Auto", light: "☀ Light", dark: "☾ Dark" };
  var mode = "auto";
  try { mode = localStorage.getItem(KEY) || localStorage.getItem("jobstracker-theme") || "auto"; } catch (e) {}
  if (MODES.indexOf(mode) < 0) mode = "auto";
  var mq = window.matchMedia("(prefers-color-scheme: dark)");

  function effective() { return mode === "auto" ? (mq.matches ? "dark" : "light") : mode; }
  function apply() {
    if (mode === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", mode);
  }
  function announce() { window.dispatchEvent(new CustomEvent("themechange", { detail: effective() })); }
  function paint() {
    var next = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
    document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      b.textContent = LABEL[mode];
      b.setAttribute("aria-label", "Color theme: " + mode + ". Switch to " + next);
      b.title = "Color theme: " + mode + " (click for " + next + ")";
    });
  }
  function set(m) {
    mode = m;
    try { localStorage.setItem(KEY, m); } catch (e) {}
    apply(); paint(); announce();
  }

  apply();
  mq.addEventListener("change", function () { if (mode === "auto") announce(); });
  window.siteTheme = { mode: function () { return mode; }, effective: effective, set: set };
  function wire() {
    document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      b.addEventListener("click", function () { set(MODES[(MODES.indexOf(mode) + 1) % MODES.length]); });
    });
    paint();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire); else wire();
})();
