"""Cost-free isolated Edge smoke test for the MCP onboarding page."""

from __future__ import annotations

import argparse
import base64
from contextlib import suppress
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scripts.smoke_game_ui_browser import (
    _Cdp,
    _find_edge,
    _free_port,
    _stop_process,
    _wait_for_json,
)


class _HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args) -> None:
        return

    def do_GET(self) -> None:
        payload = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _drive_browser(debug_port: int, screenshot_path: Path | None) -> dict:
    targets = _wait_for_json(f"http://127.0.0.1:{debug_port}/json")
    target = next(
        (
            item
            for item in targets
            if item.get("type") == "page"
            and "/mcp-connect" in str(item.get("url") or "")
        ),
        None,
    )
    if not target or not target.get("webSocketDebuggerUrl"):
        raise RuntimeError("MCP onboarding browser target was not found")

    cdp = _Cdp(str(target["webSocketDebuggerUrl"]))
    try:
        cdp.command("Page.enable")
        cdp.command("Runtime.enable")
        cdp.wait_for(
            "document.readyState === 'complete' && "
            "document.getElementById('mcp-health-badge').dataset.state === 'ready'"
        )

        desktop = cdp.evaluate(
            """
            (() => ({
              title:document.title,
              heading:document.getElementById('mcp-connect-title').textContent.trim(),
              activeSidebar:document.querySelector('.sidebar-tab.active').getAttribute('href'),
              activeSidebarLabel:document.querySelector('.sidebar-tab.active .sidebar-tab-label').textContent.trim(),
              activeClient:document.querySelector('.mcp-client-tab.is-active').dataset.clientTab,
              codexUrl:document.getElementById('mcp-url-codex').textContent.trim(),
              codexCommand:document.getElementById('codex-command').textContent.trim(),
              health:document.getElementById('mcp-health-label').textContent.trim(),
              brandIcons:document.querySelectorAll('.mcp-client-brand-icon').length,
              brandSvgs:document.querySelectorAll('.mcp-client-brand-icon svg').length,
              codexIconWidth:getComputedStyle(document.querySelector('.mcp-client-brand-icon--codex')).width,
              claudeIconWidth:getComputedStyle(document.querySelector('.mcp-client-brand-icon--claude')).width,
              workflowSection:document.querySelectorAll('.workflow-section').length,
              stepColumns:getComputedStyle(document.querySelector('.mcp-step-grid')).gridTemplateColumns.split(' ').length
            }))()
            """
        )

        cdp.evaluate(
            "document.querySelector('[data-copy-target=\"#mcp-url-codex\"]').click(); true"
        )
        cdp.wait_for(
            "document.querySelector('[data-copy-target=\"#mcp-url-codex\"]').classList.contains('is-copied')"
        )
        desktop["copyFeedback"] = cdp.evaluate(
            "document.querySelector('[data-copy-target=\"#mcp-url-codex\"] span').textContent.trim()"
        )

        cdp.evaluate("document.getElementById('tab-claude-code').click(); true")
        claude = cdp.evaluate(
            """
            (() => ({
              activeClient:document.querySelector('.mcp-client-tab.is-active').dataset.clientTab,
              codexHidden:document.getElementById('panel-codex').hidden,
              claudeHidden:document.getElementById('panel-claude-code').hidden,
              command:document.getElementById('claude-command').textContent.trim()
            }))()
            """
        )

        cdp.evaluate("document.getElementById('tab-codex').click(); true")
        if screenshot_path is not None:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            capture = cdp.command(
                "Page.captureScreenshot",
                {"format": "png", "captureBeyondViewport": True},
                timeout=20,
            )
            screenshot_path.write_bytes(base64.b64decode(capture["data"]))

        cdp.command(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": 390,
                "height": 844,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
        cdp.command("Page.reload", {"ignoreCache": True})
        cdp.wait_for(
            "document.readyState === 'complete' && "
            "document.getElementById('mcp-health-badge').dataset.state === 'ready'"
        )
        mobile = cdp.evaluate(
            """
            (() => ({
              viewport:document.documentElement.clientWidth,
              scrollWidth:document.documentElement.scrollWidth,
              stepColumns:getComputedStyle(document.querySelector('.mcp-step-grid')).gridTemplateColumns.split(' ').length,
              sidebarPosition:getComputedStyle(document.querySelector('.sidebar')).position,
              mainPadding:getComputedStyle(document.querySelector('.mcp-connect-main')).padding
            }))()
            """
        )
        return {
            "desktop": desktop,
            "claude": claude,
            "mobile": mobile,
        }
    finally:
        cdp.close()


def run_smoke(*, screenshot_path: Path | None = None) -> dict:
    with tempfile.TemporaryDirectory(
        prefix="lc-mcp-connect-browser-",
        ignore_cleanup_errors=True,
    ) as temporary_directory:
        root = Path(temporary_directory)
        output_root = root / "outputs"
        output_root.mkdir(parents=True)
        fake_server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
        fake_thread = threading.Thread(target=fake_server.serve_forever, daemon=True)
        fake_thread.start()
        fake_port = int(fake_server.server_address[1])
        os.environ.update(
            {
                "OUTPUT_DIR": str(output_root),
                "JOB_DB_PATH": str(root / "app_data.db"),
                "PRINCIPAL_COOKIE_SECRET": "s" * 64,
                "PRINCIPAL_COOKIE_SECRET_FILE": "",
                "MCP_PUBLIC_BASE_URL": "https://canvas.internal.example",
                "COMFYUI_SERVER": f"127.0.0.1:{fake_port}",
                "ASSET_CATALOG_FALLBACK_ENABLED": "false",
                "LOG_LEVEL": "WARNING",
                "LOG_TO_FILE": "false",
                "HEALTHZ_DISK_MIN_FREE_MB": "1",
            }
        )

        import uvicorn
        from app.main import app

        app_port = _free_port()
        app_server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=app_port,
                log_level="warning",
                proxy_headers=False,
            )
        )
        app_thread = threading.Thread(target=app_server.run, daemon=True)
        app_thread.start()
        _wait_for_json(f"http://127.0.0.1:{app_port}/healthz")

        debug_port = _free_port()
        edge = subprocess.Popen(
            [
                str(_find_edge()),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--remote-allow-origins=*",
                "--window-size=1440,1050",
                f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={root / 'edge-profile'}",
                f"http://127.0.0.1:{app_port}/mcp-connect",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            report = _drive_browser(debug_port, screenshot_path)
            expected = {
                "title": "MCP | LC AI Canvas",
                "heading": "LC AI Canvas MCP",
                "activeSidebar": "/mcp-connect",
                "activeSidebarLabel": "MCP",
                "activeClient": "codex",
                "codexUrl": "https://canvas.internal.example/mcp/",
                "codexCommand": (
                    "codex mcp add lc_ai_canvas --url "
                    "https://canvas.internal.example/mcp/"
                ),
                "health": "서버 연결 가능",
                "brandIcons": 2,
                "brandSvgs": 2,
                "codexIconWidth": "22px",
                "claudeIconWidth": "22px",
                "workflowSection": 0,
                "copyFeedback": "복사됨",
            }
            failures = {
                key: {"expected": value, "actual": report["desktop"].get(key)}
                for key, value in expected.items()
                if report["desktop"].get(key) != value
            }
            if report["desktop"].get("stepColumns") != 1:
                failures["desktopColumns"] = report["desktop"].get("stepColumns")
            if report["claude"].get("activeClient") != "claude-code":
                failures["claudeTab"] = report["claude"]
            if not report["claude"].get("codexHidden") or report["claude"].get("claudeHidden"):
                failures["panelVisibility"] = report["claude"]
            if "--scope user" not in str(report["claude"].get("command") or ""):
                failures["claudeCommand"] = report["claude"].get("command")
            if report["mobile"].get("stepColumns") != 1:
                failures["mobileColumns"] = report["mobile"].get("stepColumns")
            if report["mobile"].get("scrollWidth") != report["mobile"].get("viewport"):
                failures["mobileOverflow"] = report["mobile"]
            if report["mobile"].get("sidebarPosition") != "static":
                failures["mobileSidebar"] = report["mobile"].get("sidebarPosition")
            if failures:
                raise RuntimeError(json.dumps(failures, ensure_ascii=False, indent=2))
            if screenshot_path is not None:
                report["screenshot"] = str(screenshot_path)
            return report
        finally:
            _stop_process(edge)
            app_server.should_exit = True
            app_thread.join(timeout=10)
            fake_server.shutdown()
            fake_server.server_close()
            fake_thread.join(timeout=5)


def main() -> int:
    with suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    report = run_smoke(screenshot_path=args.screenshot)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
