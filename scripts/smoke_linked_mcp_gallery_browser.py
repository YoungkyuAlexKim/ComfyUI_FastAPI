"""Cost-free Edge smoke test for managing explicitly linked MCP gallery images."""

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
from http.server import ThreadingHTTPServer

from PIL import Image

from app.auth.mcp_identity import principal_for_mcp_ip
from scripts.smoke_game_ui_browser import (
    _Cdp,
    _find_edge,
    _free_port,
    _stop_process,
    _wait_for_json,
)
from scripts.smoke_mcp_connect_browser import _HealthHandler


def _seed_linkable_image(app, output_root: Path) -> tuple[str, str]:
    owner_id = principal_for_mcp_ip("127.0.0.1")
    asset_id = "linked-mcp-browser-smoke"
    asset_dir = output_root / "users" / owner_id / "2026" / "08" / "17"
    asset_dir.mkdir(parents=True)
    image_path = asset_dir / f"{asset_id}.png"
    metadata_path = asset_dir / f"{asset_id}.json"
    Image.new("RGB", (96, 64), (48, 112, 192)).save(image_path, format="PNG")
    metadata = {
        "id": asset_id,
        "owner": owner_id,
        "kind": "image",
        "mime": "image/png",
        "created_at": "2026-08-17T00:00:00+00:00",
        "status": "active",
        "workflow_id": "MCP_BROWSER_SMOKE",
    }
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    app.state.asset_service.register(
        owner_id=owner_id,
        kind="image",
        media_path=str(image_path),
        metadata_path=str(metadata_path),
        metadata=metadata,
    )
    return owner_id, asset_id


def _drive_browser(debug_port: int, asset_id: str, screenshot_path: Path | None) -> dict:
    targets = _wait_for_json(f"http://127.0.0.1:{debug_port}/json")
    target = next(
        (
            item
            for item in targets
            if item.get("type") == "page" and "/create" in str(item.get("url") or "")
        ),
        None,
    )
    if not target or not target.get("webSocketDebuggerUrl"):
        raise RuntimeError("Gallery browser target was not found")

    cdp = _Cdp(str(target["webSocketDebuggerUrl"]))
    asset_selector = f'[data-image-id="{asset_id}"]'
    try:
        cdp.command("Page.enable")
        cdp.command("Runtime.enable")
        cdp.wait_for(
            "document.readyState === 'complete' && "
            "document.getElementById('mcp-link-card') && "
            "!document.getElementById('mcp-link-card').hidden && "
            "!document.getElementById('mcp-link-action').disabled"
        )
        before = cdp.evaluate(
            """
            (() => ({
              action:document.getElementById('mcp-link-action').textContent.trim(),
              linkedCards:document.querySelectorAll('.gallery-item--linked-mcp').length
            }))()
            """
        )

        cdp.evaluate("document.getElementById('mcp-link-action').click(); true")
        cdp.wait_for(f"!!document.querySelector('{asset_selector}.gallery-item--linked-mcp')")
        cdp.evaluate("document.getElementById('select-toggle-btn').click(); true")
        cdp.evaluate(f"document.querySelector('{asset_selector}').click(); true")
        cdp.wait_for(f"document.querySelector('{asset_selector}').classList.contains('selected')")
        cdp.wait_for(
            f"getComputedStyle(document.querySelector('{asset_selector} .gallery-select')).opacity === '1'"
        )
        selected = cdp.evaluate(
            f"""
            (() => {{
              const card = document.querySelector('{asset_selector}');
              const checkbox = card.querySelector('.gallery-select');
              const badge = getComputedStyle(card, '::before');
              return {{
                selected:card.classList.contains('selected'),
                checkboxDisplay:getComputedStyle(checkbox).display,
                checkboxOpacity:getComputedStyle(checkbox).opacity,
                badgeRight:badge.right,
                deleteDisabled:document.getElementById('delete-selected-btn').disabled,
                selectedCount:document.getElementById('selected-count').textContent.trim()
              }};
            }})()
            """
        )

        cdp.evaluate("document.getElementById('delete-selected-btn').click(); true")
        cdp.wait_for("document.getElementById('confirm-overlay-batch')?.classList.contains('open')")
        cdp.evaluate("document.getElementById('batch-confirm-ok').click(); true")
        cdp.wait_for(
            f"!document.getElementById('gallery-section').classList.contains('selection-mode') && "
            f"!document.querySelector('{asset_selector}')"
        )
        after_delete = cdp.evaluate(
            f"fetch('/api/v1/images/{asset_id}/restore', {{method:'POST'}})"
            ".then(async response => ({status:response.status, body:await response.json()}))",
            await_promise=True,
        )
        cdp.command("Page.reload", {"ignoreCache": True})
        cdp.wait_for(f"!!document.querySelector('{asset_selector}.gallery-item--linked-mcp')")

        if screenshot_path is not None:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            capture = cdp.command(
                "Page.captureScreenshot",
                {"format": "png", "captureBeyondViewport": True},
                timeout=20,
            )
            screenshot_path.write_bytes(base64.b64decode(capture["data"]))

        return {
            "before": before,
            "selected": selected,
            "restore": after_delete,
            "linkedCardsAfterRestore": cdp.evaluate(
                "document.querySelectorAll('.gallery-item--linked-mcp').length"
            ),
        }
    finally:
        cdp.close()


def run_smoke(*, screenshot_path: Path | None = None) -> dict:
    with tempfile.TemporaryDirectory(
        prefix="lc-linked-mcp-gallery-browser-",
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
                "MCP_WEB_LINK_ENABLED": "true",
                "MCP_ALLOWED_CLIENT_CIDRS": "127.0.0.0/8",
                "MCP_PUBLIC_BASE_URL": "http://127.0.0.1",
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
        owner_id, asset_id = _seed_linkable_image(app, output_root)

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
                f"http://127.0.0.1:{app_port}/create",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            report = _drive_browser(debug_port, asset_id, screenshot_path)
            selected = report["selected"]
            failures = {}
            if report["before"].get("linkedCards") != 0:
                failures["unlinkedInitialState"] = report["before"]
            if not selected.get("selected") or selected.get("deleteDisabled"):
                failures["selection"] = selected
            if selected.get("checkboxDisplay") == "none" or selected.get("checkboxOpacity") != "1":
                failures["selectionCheckbox"] = selected
            if selected.get("badgeRight") == "auto":
                failures["mcpBadgePosition"] = selected
            if report["restore"].get("status") != 200:
                failures["restore"] = report["restore"]
            if report["linkedCardsAfterRestore"] != 1:
                failures["restoredGallery"] = report["linkedCardsAfterRestore"]
            stored = app.state.asset_service.get(owner_id, asset_id)
            if not stored or stored.get("status") != "active":
                failures["preservedOwner"] = stored
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
    print(json.dumps(run_smoke(screenshot_path=args.screenshot), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
