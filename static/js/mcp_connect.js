(function () {
    "use strict";

    function toast(kind, message) {
        if (window.UIToast && typeof window.UIToast[kind] === "function") {
            window.UIToast[kind](message);
        }
    }

    async function copyText(value) {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(value);
            return;
        }

        const textarea = document.createElement("textarea");
        textarea.value = value;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand("copy");
        textarea.remove();
        if (!copied) {
            throw new Error("copy command failed");
        }
    }

    function installCopyButtons() {
        document.querySelectorAll("[data-copy-target]").forEach(function (button) {
            button.addEventListener("click", async function () {
                const selector = button.getAttribute("data-copy-target");
                const source = selector ? document.querySelector(selector) : null;
                const value = source ? String(source.textContent || "").trim() : "";
                if (!value) {
                    toast("error", "복사할 내용을 찾지 못했습니다.");
                    return;
                }

                const label = button.querySelector("span");
                const original = label ? label.textContent : "";
                try {
                    await copyText(value);
                    button.classList.add("is-copied");
                    if (label) label.textContent = "복사됨";
                    toast("success", "클립보드에 복사했습니다.");
                    window.setTimeout(function () {
                        button.classList.remove("is-copied");
                        if (label) label.textContent = original;
                    }, 1600);
                } catch (_) {
                    toast("error", "자동 복사가 되지 않았습니다. 내용을 직접 선택해 복사해 주세요.");
                }
            });
        });
    }

    function selectClient(name, focusTab) {
        const tabs = Array.from(document.querySelectorAll("[data-client-tab]"));
        const panels = Array.from(document.querySelectorAll("[data-client-panel]"));
        const selected = tabs.find(function (tab) {
            return tab.getAttribute("data-client-tab") === name;
        }) || tabs[0];
        if (!selected) return;

        const selectedName = selected.getAttribute("data-client-tab");
        tabs.forEach(function (tab) {
            const active = tab === selected;
            tab.classList.toggle("is-active", active);
            tab.setAttribute("aria-selected", active ? "true" : "false");
            tab.setAttribute("tabindex", active ? "0" : "-1");
        });
        panels.forEach(function (panel) {
            const active = panel.getAttribute("data-client-panel") === selectedName;
            panel.classList.toggle("is-active", active);
            panel.hidden = !active;
        });

        try {
            window.localStorage.setItem("lc_mcp_client_tab", selectedName);
        } catch (_) {
            // Local storage can be unavailable in locked-down browsers.
        }
        if (focusTab) selected.focus();
    }

    function installClientTabs() {
        const tabs = Array.from(document.querySelectorAll("[data-client-tab]"));
        if (!tabs.length) return;

        let stored = "codex";
        try {
            stored = window.localStorage.getItem("lc_mcp_client_tab") || stored;
        } catch (_) {
            // Use the verified Codex tab by default.
        }
        selectClient(stored, false);

        tabs.forEach(function (tab, index) {
            tab.addEventListener("click", function () {
                selectClient(tab.getAttribute("data-client-tab"), false);
            });
            tab.addEventListener("keydown", function (event) {
                if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
                event.preventDefault();
                let nextIndex = index;
                if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
                if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
                if (event.key === "Home") nextIndex = 0;
                if (event.key === "End") nextIndex = tabs.length - 1;
                selectClient(tabs[nextIndex].getAttribute("data-client-tab"), true);
            });
        });
    }

    async function updateHealth() {
        const badge = document.getElementById("mcp-health-badge");
        const label = document.getElementById("mcp-health-label");
        if (!badge || !label) return;

        try {
            const response = await fetch("/healthz", {
                method: "GET",
                headers: { Accept: "application/json" },
                cache: "no-store",
            });
            if (!response.ok) throw new Error("health request failed");
            badge.setAttribute("data-state", "ready");
            label.textContent = "서버 연결 가능";
        } catch (_) {
            badge.setAttribute("data-state", "error");
            label.textContent = "서버 확인 필요";
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        installClientTabs();
        installCopyButtons();
        updateHealth();
    });
})();
