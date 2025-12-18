(function () {
  const DEFAULT_TIMEOUT_MS = 3200;
  const MAX_TOASTS = 3;

  function ensureHost() {
    let host = document.getElementById("ui-toast-host");
    if (host) return host;
    host = document.createElement("div");
    host.id = "ui-toast-host";
    host.className = "ui-toast-host";
    host.setAttribute("aria-live", "polite");
    host.setAttribute("aria-relevant", "additions");
    document.body.appendChild(host);
    return host;
  }

  function removeOldToasts(host) {
    try {
      const toasts = host.querySelectorAll(".ui-toast");
      const extra = toasts.length - MAX_TOASTS;
      if (extra <= 0) return;
      for (let i = 0; i < extra; i += 1) {
        const t = toasts[i];
        if (t && t.parentNode) t.parentNode.removeChild(t);
      }
    } catch (_) {}
  }

  function showToast(message, opts) {
    const text = typeof message === "string" ? message : "";
    if (!text) return;

    const type = (opts && opts.type) || "info";
    const timeoutMs = Number.isFinite(Number(opts && opts.timeoutMs))
      ? Number(opts.timeoutMs)
      : DEFAULT_TIMEOUT_MS;

    const host = ensureHost();
    removeOldToasts(host);

    const toast = document.createElement("div");
    toast.className = `ui-toast ui-toast--${type}`;
    toast.setAttribute("role", "status");
    toast.textContent = text;

    host.appendChild(toast);

    requestAnimationFrame(() => {
      toast.classList.add("show");
    });

    const close = () => {
      try {
        toast.classList.remove("show");
        toast.classList.add("hide");
        setTimeout(() => {
          if (toast && toast.parentNode) toast.parentNode.removeChild(toast);
        }, 220);
      } catch (_) {}
    };

    if (timeoutMs > 0) {
      setTimeout(close, timeoutMs);
    }

    toast.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      close();
    });
  }

  window.UIToast = {
    show: (opts) => showToast(opts && opts.message ? String(opts.message) : "", opts),
    info: (msg, timeoutMs) => showToast(String(msg || ""), { type: "info", timeoutMs }),
    success: (msg, timeoutMs) => showToast(String(msg || ""), { type: "success", timeoutMs }),
    error: (msg, timeoutMs) => showToast(String(msg || ""), { type: "error", timeoutMs }),
  };
})();


