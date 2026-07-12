(function () {
  "use strict";

  const SIDEBAR_KEY = "lcStudioSidebarCollapsed:v1";

  function storageGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (_) {
      return null;
    }
  }

  function storageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (_) {}
  }

  function setupSidebar() {
    const sidebar = document.querySelector(".sidebar");
    const toggle = document.querySelector(".studio-sidebar-collapse");
    if (!sidebar || !toggle) return;

    const compactViewport = () => window.matchMedia("(max-width: 767px)").matches;

    function apply(collapsed, persist) {
      const enabled = !!collapsed && !compactViewport();
      document.body.classList.toggle("studio-sidebar-collapsed", enabled);
      toggle.setAttribute("aria-expanded", enabled ? "false" : "true");
      toggle.setAttribute("aria-label", enabled ? "사이드바 펼치기" : "사이드바 축소");
      toggle.setAttribute("title", enabled ? "사이드바 펼치기" : "사이드바 축소");
      const icon = toggle.querySelector("i");
      if (icon) icon.className = enabled ? "fas fa-angles-right" : "fas fa-angles-left";
      if (persist) storageSet(SIDEBAR_KEY, enabled ? "1" : "0");
    }

    apply(storageGet(SIDEBAR_KEY) === "1", false);
    toggle.addEventListener("click", () => {
      apply(!document.body.classList.contains("studio-sidebar-collapsed"), true);
    });
    window.addEventListener("resize", () => {
      if (compactViewport()) apply(false, false);
    });
  }

  function setupFocusMode() {
    const toggle = document.querySelector(".studio-focus-toggle");
    const main = document.querySelector("main.gallery-collapsible");
    if (!toggle || !main) return;

    function apply(enabled) {
      document.body.classList.toggle("studio-focus-mode", !!enabled);
      toggle.classList.toggle("active", !!enabled);
      toggle.setAttribute("aria-pressed", enabled ? "true" : "false");
      toggle.setAttribute("title", enabled ? "입력 패널 다시 열기" : "캔버스 집중 모드");
      const icon = toggle.querySelector("i");
      if (icon) icon.className = enabled ? "fas fa-compress" : "fas fa-expand";
      const text = toggle.querySelector("span");
      if (text) text.textContent = enabled ? "입력 열기" : "집중 모드";
    }

    toggle.addEventListener("click", () => apply(!document.body.classList.contains("studio-focus-mode")));
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (!document.body.classList.contains("studio-focus-mode")) return;
      apply(false);
    });
  }

  function setupWorkflowMotion() {
    const main = document.querySelector("main.gallery-collapsible");
    if (!main) return;
    let timer = null;
    document.addEventListener("click", (event) => {
      const item = event.target && event.target.closest ? event.target.closest(".workflow-item") : null;
      if (!item) return;
      main.classList.remove("studio-workflow-changing");
      // Force a new animation even when users rapidly switch tools.
      void main.offsetWidth;
      main.classList.add("studio-workflow-changing");
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(() => main.classList.remove("studio-workflow-changing"), 420);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    setupSidebar();
    setupFocusMode();
    setupWorkflowMotion();
    window.requestAnimationFrame(() => document.body.classList.add("studio-ready"));
  });
})();
