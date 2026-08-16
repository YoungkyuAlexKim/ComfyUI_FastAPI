"""Cost-free isolated browser smoke test for the Game UI workflow.

This starts an in-process fake OpenRouter endpoint and Uvicorn app with a
temporary database/output root, drives installed Microsoft Edge over CDP, and
never contacts a paid image provider or the operational data paths.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import suppress
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import urlopen
import zipfile

from PIL import Image, ImageDraw
import websocket


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _synthetic_sheet() -> bytes:
    image = Image.new("RGB", (512, 512), (0, 255, 0))
    draw = ImageDraw.Draw(image)
    for index in range(16):
        column = index % 4
        row = index // 4
        color = (
            (40 + index * 37) % 220,
            (55 + index * 61) % 220,
            (70 + index * 83) % 220,
        )
        draw.rounded_rectangle(
            (column * 128 + 24, row * 128 + 24, column * 128 + 103, row * 128 + 103),
            radius=12,
            fill=color,
        )
    encoded = BytesIO()
    image.save(encoded, format="PNG")
    return encoded.getvalue()


class _FakeProviderHandler(BaseHTTPRequestHandler):
    sheet_bytes = _synthetic_sheet()
    requests: list[dict] = []

    def log_message(self, _format: str, *_args) -> None:
        return

    def _respond(self) -> None:
        content_length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(content_length) if content_length else b""
        if raw:
            with suppress(Exception):
                self.requests.append(json.loads(raw.decode("utf-8")))
        payload = json.dumps(
            {
                "data": [{"b64_json": base64.b64encode(self.sheet_bytes).decode("ascii")}],
                "usage": {"cost": 0},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _respond
    do_POST = _respond


class _Cdp:
    def __init__(self, websocket_url: str):
        self.socket = websocket.create_connection(
            websocket_url,
            timeout=5,
            origin="http://127.0.0.1",
        )
        self.next_id = 0

    def close(self) -> None:
        self.socket.close()

    def command(self, method: str, params: dict | None = None, *, timeout: float = 10) -> dict:
        self.next_id += 1
        command_id = self.next_id
        self.socket.send(
            json.dumps({"id": command_id, "method": method, "params": params or {}})
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = json.loads(self.socket.recv())
            if message.get("id") != command_id:
                continue
            if "error" in message:
                raise RuntimeError(message["error"])
            return message.get("result") or {}
        raise TimeoutError(method)

    def evaluate(self, expression: str, *, await_promise: bool = False):
        result = self.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
                "userGesture": True,
            },
            timeout=20,
        )
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"])
        return (result.get("result") or {}).get("value")

    def wait_for(self, expression: str, *, timeout: float = 30) -> None:
        deadline = time.time() + timeout
        last_value = None
        while time.time() < deadline:
            with suppress(Exception):
                last_value = self.evaluate(expression)
                if last_value:
                    return
            time.sleep(0.2)
        raise TimeoutError(f"Browser condition failed: {expression}; last={last_value!r}")


def _wait_for_json(url: str, *, timeout: float = 20):
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
    raise TimeoutError(f"Endpoint did not become ready: {url}; {last_error}")


def _find_edge() -> Path:
    candidates = (
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("Microsoft Edge executable was not found")


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)


def _drive_browser(debug_port: int) -> dict:
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
        raise RuntimeError("Game UI browser target was not found")

    cdp = _Cdp(str(target["webSocketDebuggerUrl"]))
    try:
        cdp.command("Page.enable")
        cdp.command("Runtime.enable")
        cdp.wait_for("document.readyState === 'complete' && Array.isArray(window.ALL_WORKFLOWS)")
        selected = cdp.evaluate(
            """
            (() => {
              const workflowCard = document.querySelector('[data-workflow-id="GameUI_Elements"]');
              if (!workflowCard) return {ok:false};
              workflowCard.click();
              const grid = document.querySelector('input[name="game-ui-grid"][value="4x4"]');
              grid.checked = true;
              grid.dispatchEvent(new Event('change', {bubbles:true}));
              const prompt = document.getElementById('user_prompt');
              prompt.value = '푸른 수정으로 만든 판타지 마법 스킬 아이콘';
              prompt.dispatchEvent(new Event('input', {bubbles:true}));
              return {
                ok:true,
                grid:document.querySelector('input[name="game-ui-grid"]:checked').value,
                button:document.getElementById('generate-btn').textContent.trim()
              };
            })()
            """
        )
        if not selected or not selected.get("ok"):
            raise RuntimeError("Game UI workflow could not be selected")
        cdp.evaluate("document.getElementById('generate-btn').click(); true")
        cdp.wait_for(
            "document.querySelectorAll('#game-ui-result-grid .game-ui-result__cell').length === 16",
            timeout=45,
        )
        cdp.wait_for(
            "document.querySelectorAll('.game-ui-gallery-group__cells .gallery-item').length === 16",
            timeout=20,
        )
        result = cdp.evaluate(
            """
            (async () => {
              const download = document.getElementById('game-ui-group-download');
              const zipResponse = await fetch(download.href);
              const zipBytes = new Uint8Array(await zipResponse.arrayBuffer());
              const grouped = await (await fetch('/api/v1/images?page=1&size=10&preserve_groups=true')).json();
              const ordinary = await (await fetch('/api/v1/images?page=1&size=10')).json();
              const groupId = grouped.items[0].meta.game_ui_group_id;
              return {
                selectedGrid:document.querySelector('input[name="game-ui-grid"]:checked').value,
                resultCells:document.querySelectorAll('#game-ui-result-grid .game-ui-result__cell').length,
                resultColumns:getComputedStyle(document.getElementById('game-ui-result-grid')).gridTemplateColumns.split(' ').length,
                resultTitle:document.getElementById('game-ui-result-title').textContent.trim(),
                selectedDownloadLinks:document.querySelectorAll('#game-ui-result-footer a').length,
                zipStatus:zipResponse.status,
                zipMagic:Array.from(zipBytes.slice(0, 2)),
                zipPath:new URL(download.href).pathname,
                groupedCount:grouped.items.length,
                groupedTotalPages:grouped.total_pages,
                ordinaryCount:ordinary.items.length,
                groupId,
                groupDeleteButtons:document.querySelectorAll('.game-ui-gallery-group__delete').length,
                bannerImage:getComputedStyle(
                  document.getElementById('workflow-banner'), '::before'
                ).backgroundImage.includes('img_banner_GameUI_Elements.png'),
                bannerFilter:getComputedStyle(
                  document.getElementById('workflow-banner'), '::before'
                ).filter,
                bannerScrimOpacity:Number(getComputedStyle(
                  document.querySelector('.workflow-banner-scrim')
                ).opacity)
              };
            })()
            """,
            await_promise=True,
        )
        result["groupSelection"] = cdp.evaluate(
            """
            (() => {
              document.getElementById('select-toggle-btn').click();
              document.querySelector('.game-ui-gallery-group__cells .gallery-item').click();
              return {
                selectedCells:document.querySelectorAll('.game-ui-gallery-group__cells .gallery-item.selected').length,
                selectedUnits:document.getElementById('selected-count').textContent.trim()
              };
            })()
            """
        )
        cdp.evaluate(
            """
            new Promise(resolve => {
              document.getElementById('select-toggle-btn').click();
              setTimeout(() => resolve(true), 350);
            })
            """,
            await_promise=True,
        )
        cdp.evaluate("document.querySelector('.game-ui-gallery-group__delete').click(); true")
        cdp.wait_for("document.getElementById('confirm-overlay-batch').classList.contains('open')")
        result["deleteConfirmation"] = cdp.evaluate(
            "document.getElementById('batch-confirm-text').textContent.trim()"
        )
        cdp.evaluate("document.getElementById('batch-confirm-ok').click(); true")
        cdp.wait_for("document.querySelectorAll('.game-ui-gallery-group__cells .gallery-item').length === 0")
        result["deletedGalleryCells"] = cdp.evaluate(
            "document.querySelectorAll('.game-ui-gallery-group__cells .gallery-item').length"
        )
        result["restoreStatus"] = cdp.evaluate(
            f"""
            (async () => {{
              const restored = await fetch('/api/v1/game-ui-groups/{result['groupId']}/restore', {{method:'POST'}});
              document.getElementById('tab-generated').click();
              return restored.status;
            }})()
            """,
            await_promise=True,
        )
        cdp.wait_for(
            "document.querySelectorAll('.game-ui-gallery-group__cells .gallery-item').length === 16"
        )
        result["galleryCells"] = cdp.evaluate(
            "document.querySelectorAll('.game-ui-gallery-group__cells .gallery-item').length"
        )
        result["galleryColumns"] = cdp.evaluate(
            "getComputedStyle(document.querySelector('.game-ui-gallery-group__cells')).gridTemplateColumns.split(' ').length"
        )
        result["galleryLabel"] = cdp.evaluate(
            "document.querySelector('.game-ui-gallery-group__header span').textContent.trim()"
        )
        cdp.command("Page.reload", {"ignoreCache": True})
        cdp.wait_for(
            "document.readyState === 'complete' && document.querySelectorAll('.game-ui-gallery-group__cells .gallery-item').length === 16",
            timeout=25,
        )
        result["restoredGrid"] = cdp.evaluate(
            "document.querySelector('input[name=\"game-ui-grid\"]:checked').value"
        )
        result["reloadGalleryCells"] = cdp.evaluate(
            "document.querySelectorAll('.game-ui-gallery-group__cells .gallery-item').length"
        )
        owner_id = str(result["zipPath"]).split("/")[3]
        cdp.command("Page.navigate", {"url": cdp.evaluate("location.origin") + "/admin"})
        cdp.wait_for("document.readyState === 'complete' && document.querySelectorAll('.admin-user').length > 0")
        selected_admin_user = cdp.evaluate(
            f"""
            (() => {{
              const target = Array.from(document.querySelectorAll('.admin-user'))
                .find(element => element.textContent.trim() === {json.dumps(owner_id)});
              if (!target) return false;
              target.click();
              return true;
            }})()
            """
        )
        if not selected_admin_user:
            raise RuntimeError("Generated owner was not listed in the admin UI")
        cdp.wait_for("document.querySelectorAll('.admin-thumb--game-ui').length === 1")
        result["adminGroupCards"] = cdp.evaluate(
            "document.querySelectorAll('.admin-thumb--game-ui').length"
        )
        result["adminGroupImages"] = cdp.evaluate(
            "document.querySelectorAll('.admin-thumb--game-ui img').length"
        )
        result["adminGroupAction"] = cdp.evaluate(
            "document.querySelector('.admin-thumb--game-ui + .admin-actions .btn').textContent.trim()"
        )
        return result
    finally:
        cdp.close()


def run_smoke(*, keep_temp: bool = False) -> dict:
    temporary = None
    if keep_temp:
        root = Path(tempfile.mkdtemp(prefix="lc-gameui-browser-"))
    else:
        temporary = tempfile.TemporaryDirectory(
            prefix="lc-gameui-browser-",
            ignore_cleanup_errors=True,
        )
        root = Path(temporary.name)
    output_root = root / "outputs"
    output_root.mkdir(parents=True)

    fake_server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeProviderHandler)
    fake_thread = threading.Thread(target=fake_server.serve_forever, daemon=True)
    fake_thread.start()
    fake_port = int(fake_server.server_address[1])

    os.environ.update(
        {
            "OUTPUT_DIR": str(output_root),
            "JOB_DB_PATH": str(root / "app_data.db"),
            "PRINCIPAL_COOKIE_SECRET": "s" * 64,
            "PRINCIPAL_COOKIE_SECRET_FILE": "",
            "PRINCIPAL_IDENTITY_MODE": "compat",
            "OPENROUTER_API_KEY": "isolated-smoke-key",
            "OPENROUTER_BASE_URL": f"http://127.0.0.1:{fake_port}",
            "COMFYUI_SERVER": f"127.0.0.1:{fake_port}",
            "ASSET_CATALOG_FALLBACK_ENABLED": "false",
            "BETA_PASSWORD": "",
            "ADMIN_USER": "",
            "ADMIN_PASSWORD": "",
            "ADMIN_ALLOW_UNAUTHENTICATED": "true",
            "LOG_LEVEL": "WARNING",
            "LOG_TO_FILE": "false",
            "HEALTHZ_DISK_MIN_FREE_MB": "1",
        }
    )

    import uvicorn
    from app.main import app

    app_port = _free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=app_port,
        log_level="warning",
        proxy_headers=False,
    )
    app_server = uvicorn.Server(config)
    app_thread = threading.Thread(target=app_server.run, daemon=True)
    app_thread.start()
    _wait_for_json(f"http://127.0.0.1:{app_port}/healthz")

    debug_port = _free_port()
    edge_profile = root / "edge-profile"
    edge = subprocess.Popen(
        [
            str(_find_edge()),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--remote-allow-origins=*",
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={edge_profile}",
            f"http://127.0.0.1:{app_port}/create",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        browser = _drive_browser(debug_port)
        prompt = next(
            (
                str(request.get("prompt") or "")
                for request in reversed(_FakeProviderHandler.requests)
                if request.get("model") == "openai/gpt-image-2"
            ),
            "",
        )
        zip_relative = str(browser["zipPath"]).removeprefix("/outputs/")
        zip_path = output_root.joinpath(*zip_relative.split("/"))
        with zipfile.ZipFile(zip_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            names = archive.namelist()
        audit = app.state.asset_service.audit()
        report = {
            "browser": browser,
            "prompt_has_sixteen": "exactly sixteen equal cells" in prompt,
            "prompt_has_four_by_four": "4 columns by 4 rows" in prompt,
            "zip": {
                "manifest_grid": manifest.get("grid"),
                "manifest_count": manifest.get("count"),
                "masters": sum(name.startswith("masters/") for name in names),
                "derivatives": sum(name.startswith("sizes/") for name in names),
            },
            "audit": audit,
        }
        expected = {
            "selectedGrid": "4x4",
            "resultCells": 16,
            "resultColumns": 4,
            "selectedDownloadLinks": 5,
            "zipStatus": 200,
            "zipMagic": [80, 75],
            "groupedCount": 16,
            "groupedTotalPages": 1,
            "ordinaryCount": 10,
            "groupDeleteButtons": 1,
            "bannerImage": True,
            "bannerScrimOpacity": 0,
            "deletedGalleryCells": 0,
            "restoreStatus": 200,
            "galleryCells": 16,
            "galleryColumns": 4,
            "restoredGrid": "4x4",
            "reloadGalleryCells": 16,
            "adminGroupCards": 1,
            "adminGroupImages": 16,
            "adminGroupAction": "묶음 휴지통으로",
        }
        failures = {
            key: {"expected": value, "actual": browser.get(key)}
            for key, value in expected.items()
            if browser.get(key) != value
        }
        if "묶음 전체" not in str(browser.get("deleteConfirmation") or ""):
            failures["deleteConfirmation"] = {
                "expected": "contains 묶음 전체",
                "actual": browser.get("deleteConfirmation"),
            }
        if browser.get("groupSelection") != {"selectedCells": 16, "selectedUnits": "1개 항목 선택됨"}:
            failures["groupSelection"] = {
                "expected": {"selectedCells": 16, "selectedUnits": "1개 항목 선택됨"},
                "actual": browser.get("groupSelection"),
            }
        if not report["prompt_has_sixteen"] or not report["prompt_has_four_by_four"]:
            failures["prompt"] = {"expected": "4x4 exact-count clauses", "actual": prompt}
        if "brightness(0.68)" in str(browser.get("bannerFilter") or ""):
            failures["bannerFilter"] = {
                "expected": "no forced low-brightness filter",
                "actual": browser.get("bannerFilter"),
            }
        if report["zip"] != {
            "manifest_grid": "4x4",
            "manifest_count": 16,
            "masters": 16,
            "derivatives": 64,
        }:
            failures["zip"] = {"expected": "complete 4x4 bundle", "actual": report["zip"]}
        if any(audit.get(key) for key in ("missing_files", "missing_metadata", "missing_group_files")):
            failures["audit"] = audit
        if failures:
            raise RuntimeError(json.dumps(failures, ensure_ascii=False, indent=2))
        return report
    finally:
        _stop_process(edge)
        app_server.should_exit = True
        app_thread.join(timeout=10)
        fake_server.shutdown()
        fake_server.server_close()
        fake_thread.join(timeout=5)
        if keep_temp:
            print(f"Temporary smoke data kept at: {root}")
        elif temporary is not None:
            temporary.cleanup()


def main() -> int:
    with suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-temp", action="store_true", help="Keep isolated artifacts for debugging")
    args = parser.parse_args()
    report = run_smoke(keep_temp=args.keep_temp)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
