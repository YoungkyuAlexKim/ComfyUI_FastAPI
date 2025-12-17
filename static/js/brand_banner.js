(function () {
  function applyBrandBanner() {
    try {
      const el = document.getElementById("brand-banner");
      if (!el) return;

      const textWrap = document.getElementById("brand-banner-text");
      const b = (window.APP_CONFIG && window.APP_CONFIG.brand) || {};

      const h = Number.isFinite(b.heightPx) ? b.heightPx : 80;
      el.style.setProperty("--brand-banner-height", `${h}px`);

      const pad = Number.isFinite(b.paddingPx) ? b.paddingPx : 12;
      el.style.setProperty("--brand-padding", `${pad}px`);

      const url = typeof b.url === "string" ? b.url : "";
      if (url) {
        el.style.setProperty("--brand-banner-img", `url("${url}")`);
        el.style.setProperty("--brand-hasimg", "1");
        if (textWrap) textWrap.style.display = b.showTextByDefault === false ? "none" : "";
      } else {
        el.style.removeProperty("--brand-banner-img");
        el.style.setProperty("--brand-hasimg", "0");
        if (textWrap) textWrap.style.display = "";
      }
    } catch (_) {}
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyBrandBanner);
  } else {
    applyBrandBanner();
  }
})();


