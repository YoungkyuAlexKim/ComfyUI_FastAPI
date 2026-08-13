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
                workflows = client.get("/api/v1/workflows")
                initialized = client.post("/mcp/", headers=headers, json=initialize)
                listed = client.post(
                    "/mcp/",
                    headers={**headers, "MCP-Protocol-Version": "2025-06-18"},
                    json=tools_list,
                )
                assert health.status_code == 200, health.text
                assert create_page.status_code == 200, create_page.text
                assert 'name="game-ui-grid" value="3x3"' in create_page.text
                assert 'name="game-ui-grid" value="4x4"' in create_page.text
                assert "preserve_groups', 'true'" in create_page.text
                game_ui = next(item for item in workflows.json()["workflows"] if item["id"] == "GameUI_Elements")
                assert [item["id"] for item in game_ui["ui"]["gameUiTool"]["supportedGrids"]] == [
                    "2x2", "3x3", "4x4"
                ]
                assert "lc_principal" not in health.headers.get("set-cookie", "")
                assert initialized.json()["result"]["serverInfo"]["version"] == "0.4.0"
                assert "lc_principal" not in initialized.headers.get("set-cookie", "")
                names = {item["name"] for item in listed.json()["result"]["tools"]}
                assert {
                    "list_image_assets",
                    "get_image_asset",
                    "create_input_image_asset",
                    "create_managed_image_asset",
                    "create_game_ui_assets",
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
                }
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(
            completed.returncode,
            0,
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
