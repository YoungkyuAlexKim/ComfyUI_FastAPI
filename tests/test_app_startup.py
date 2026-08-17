import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class ApplicationStartupTests(unittest.TestCase):
    def test_isolated_startup_health_and_mcp_contract(self):
        script = textwrap.dedent(
            """
            from io import BytesIO
            from fastapi.testclient import TestClient
            from PIL import Image
            from pydantic import ValidationError
            from app.main import GenerateRequest, app

            assert GenerateRequest(
                user_prompt="button",
                aspect_ratio="square",
                workflow_id="GameUI_Elements",
                game_ui_grid="4x4",
            ).game_ui_grid == "4x4"
            try:
                GenerateRequest(
                    user_prompt="button",
                    aspect_ratio="square",
                    workflow_id="GameUI_Elements",
                    game_ui_grid="5x5",
                )
            except ValidationError:
                pass
            else:
                raise AssertionError("unsupported Game UI grid was accepted")

            headers = {"Accept": "application/json, text/event-stream"}
            initialize = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "startup-test", "version": "1.0"},
                },
            }
            tools_list = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            with TestClient(app) as client:
                health = client.get("/healthz")
                create_page = client.get("/create")
                banner_config = client.get("/static/js/app_config.js")
                game_ui_banner = client.get(
                    "/static/img/banner/img_banner_GameUI_Elements.png"
                )
                workflows = client.get("/api/v1/workflows")
                admin_auth = ("startup-admin", "startup-pass")
                admin_page = client.get("/admin", auth=admin_auth)
                cost_report = client.get(
                    "/api/v1/admin/generation-controls/cost-report?days=30",
                    auth=admin_auth,
                )
                initialized = client.post("/mcp/", headers=headers, json=initialize)
                listed = client.post(
                    "/mcp/",
                    headers={**headers, "MCP-Protocol-Version": "2025-06-18"},
                    json=tools_list,
                )
                assert health.status_code == 200, health.text
                assert create_page.status_code == 200, create_page.text
                assert 'id="mcp-link-card"' in create_page.text
                assert banner_config.status_code == 200, banner_config.text
                assert "img_banner_GameUI_Elements.png" in banner_config.text
                assert game_ui_banner.status_code == 200, game_ui_banner.text
                assert game_ui_banner.headers["content-type"] == "image/png"
                with Image.open(BytesIO(game_ui_banner.content)) as banner_image:
                    assert banner_image.size == (422, 180)
                assert admin_page.status_code == 200, admin_page.text
                assert 'id="cost-ip-table"' in admin_page.text
                assert 'id="cost-filter-ip"' in admin_page.text
                assert cost_report.status_code == 200, cost_report.text
                assert cost_report.json()["summary"]["actual_cost_record_count"] == 0
                assert 'name="game-ui-grid" value="3x3"' in create_page.text
                assert 'name="game-ui-grid" value="4x4"' in create_page.text
                assert "preserve_groups', 'true'" in create_page.text
                game_ui = next(item for item in workflows.json()["workflows"] if item["id"] == "GameUI_Elements")
                assert [item["id"] for item in game_ui["ui"]["gameUiTool"]["supportedGrids"]] == [
                    "2x2", "3x3", "4x4"
                ]
                assert "lc_principal" not in health.headers.get("set-cookie", "")
                assert initialized.json()["result"]["serverInfo"]["version"] == "0.7.0"
                assert "lc_principal" not in initialized.headers.get("set-cookie", "")
                names = {item["name"] for item in listed.json()["result"]["tools"]}
                assert {
                    "list_image_assets",
                    "get_image_asset",
                    "create_input_image_asset",
                    "plan_generation",
                    "create_managed_image_asset",
                    "create_game_ui_assets",
                    "create_character_sheet",
                    "create_storyboard",
                    "remove_background",
                } <= names

                image = Image.new("RGB", (8, 6), (20, 40, 60))
                encoded = BytesIO()
                image.save(encoded, format="JPEG")
                uploaded = client.post(
                    "/api/v1/inputs/upload",
                    files={"file": ("reference.jpg", encoded.getvalue(), "image/jpeg")},
                )
                assert uploaded.status_code == 200, uploaded.text
                upload_result = uploaded.json()
                assert upload_result["ok"] is True
                owner_cookies = dict(client.cookies)
                content = client.get(upload_result["url"])
                assert content.status_code == 200
                assert content.content.startswith(b"\\x89PNG\\r\\n\\x1a\\n")

                client.cookies.clear()
                foreign_content = client.get(upload_result["url"])
                assert foreign_content.status_code == 404
                client.cookies.update(owner_cookies)

                deleted = client.post(f"/api/v1/inputs/{upload_result['id']}/delete")
                after_delete = client.get("/api/v1/inputs?page=1&size=10")
                restored = client.post(f"/api/v1/inputs/{upload_result['id']}/restore")
                after_restore = client.get("/api/v1/inputs?page=1&size=10")
                assert deleted.status_code == 200, deleted.text
                assert after_delete.json()["total"] == 0
                assert restored.status_code == 200, restored.text
                assert after_restore.json()["total"] == 1
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "outputs"
            output_dir.mkdir()
            environment = dict(os.environ)
            environment.update(
                {
                    "JOB_DB_PATH": str(root / "app_data.db"),
                    "OUTPUT_DIR": str(output_dir),
                    "PRINCIPAL_COOKIE_SECRET": "startup-test-secret-" + ("x" * 40),
                    "LOG_TO_FILE": "false",
                    "BETA_PASSWORD": "",
                    "MCP_ALLOWED_CLIENT_CIDRS": "",
                    "ASSET_CATALOG_FALLBACK_ENABLED": "false",
                    "ADMIN_USER": "startup-admin",
                    "ADMIN_PASSWORD": "startup-pass",
                }
            )
            completed = None
            for _ in range(2):
                completed = subprocess.run(
                    [sys.executable, "-c", script],
                    cwd=Path(__file__).resolve().parents[1],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                if completed.returncode not in {3221225477, -1073741819}:
                    break
        self.assertEqual(
            completed.returncode,
            0,
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )

    def test_beta_gate_allows_only_ip_owned_mcp_output(self):
        script = textwrap.dedent(
            """
            import hashlib
            import os
            from pathlib import Path
            import zipfile

            from fastapi.testclient import TestClient

            output_root = Path(os.environ["OUTPUT_DIR"])
            client_ip = "testclient"
            owner = "mcp-ip-" + hashlib.sha256(
                f"mcp-ip:{client_ip}".encode("utf-8")
            ).hexdigest()[:24]
            foreign_owner = "mcp-ip-" + hashlib.sha256(
                b"mcp-ip:203.0.113.9"
            ).hexdigest()[:24]

            relative = Path("2026/08/17/game_ui_groups/group-1/group.zip")
            owned_zip = output_root / "users" / owner / relative
            foreign_zip = output_root / "users" / foreign_owner / relative
            owned_zip.parent.mkdir(parents=True, exist_ok=True)
            foreign_zip.parent.mkdir(parents=True, exist_ok=True)
            for archive_path in (owned_zip, foreign_zip):
                with zipfile.ZipFile(archive_path, "w") as archive:
                    archive.writestr("manifest.json", '{"count": 4}')
                    archive.writestr("masters/cell_01.png", b"png-placeholder")

            hidden_sidecar = owned_zip.with_name("manifest.json")
            hidden_sidecar.write_text('{"private": true}', encoding="utf-8")

            from app.main import app

            owned_url = f"/outputs/users/{owner}/{relative.as_posix()}"
            foreign_url = f"/outputs/users/{foreign_owner}/{relative.as_posix()}"
            sidecar_url = owned_url.rsplit("/", 1)[0] + "/manifest.json"

            with TestClient(app) as client:
                beta_page = client.get("/create", follow_redirects=False)
                owned = client.get(owned_url, follow_redirects=False)
                spoofed = client.get(
                    owned_url,
                    headers={"X-Forwarded-For": "203.0.113.9"},
                    follow_redirects=False,
                )
                foreign = client.get(foreign_url, follow_redirects=False)
                sidecar = client.get(sidecar_url, follow_redirects=False)

                assert beta_page.status_code == 303, beta_page.text
                assert beta_page.headers["location"] == "/beta-login"
                assert owned.status_code == 200, owned.text
                assert owned.headers["content-type"] in {
                    "application/zip",
                    "application/x-zip-compressed",
                }, owned.headers["content-type"]
                assert owned.content.startswith(b"PK")
                assert "lc_principal" not in owned.headers.get("set-cookie", "")
                assert spoofed.status_code == 200, spoofed.text
                assert foreign.status_code == 404, foreign.text
                assert sidecar.status_code == 404, sidecar.text
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "outputs"
            output_dir.mkdir()
            environment = dict(os.environ)
            environment.update(
                {
                    "JOB_DB_PATH": str(root / "app_data.db"),
                    "OUTPUT_DIR": str(output_dir),
                    "PRINCIPAL_COOKIE_SECRET": "startup-test-secret-" + ("x" * 40),
                    "LOG_TO_FILE": "false",
                    "BETA_PASSWORD": "beta-test-password",
                    "MCP_ALLOWED_CLIENT_CIDRS": "",
                    "TRUSTED_PROXY_CIDRS": "",
                    "ASSET_CATALOG_FALLBACK_ENABLED": "false",
                }
            )
            completed = None
            for _ in range(2):
                completed = subprocess.run(
                    [sys.executable, "-c", script],
                    cwd=Path(__file__).resolve().parents[1],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                if completed.returncode not in {3221225477, -1073741819}:
                    break
        self.assertEqual(
            completed.returncode,
            0,
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
