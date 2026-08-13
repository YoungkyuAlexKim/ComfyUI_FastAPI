import asyncio
import base64
import gc
from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from app.asset_store import AssetStore
from app.job_store import JobStore
from app.config import SERVER_CONFIG
from app.mcp_server import (
    McpCaller,
    McpGenerationService,
    _principal_for_ip,
    _result_image_content,
    create_mcp_integration,
)
from app.services.generation_controls import GenerationControlService
from app.services.asset_service import AssetService, atomic_write_json


class FakeJobManager:
    def __init__(self):
        self.jobs = {}

    def enqueue(self, owner_id, job_type, payload):
        job = SimpleNamespace(
            id="a" * 32,
            owner_id=owner_id,
            type=job_type,
            payload=payload,
            status="queued",
            progress=0.0,
            created_at=1.0,
            started_at=None,
            ended_at=None,
            error_message=None,
            result={},
        )
        self.jobs[job.id] = job
        return job

    def get(self, job_id):
        return self.jobs.get(job_id)

    def get_position(self, job_id):
        return 0 if job_id in self.jobs else None


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.directory.name, "mcp.db")
        self.controls = GenerationControlService(self.db_path, timezone_name="Asia/Seoul")
        self.manager = FakeJobManager()
        self.store = JobStore(self.db_path)
        self.output_dir = Path(self.directory.name, "outputs")
        self.output_dir.mkdir()
        self.asset_service = AssetService(AssetStore(self.db_path), str(self.output_dir))
        self.service = McpGenerationService(
            self.manager,
            self.store,
            self.controls,
            self.asset_service,
        )
        self.caller = McpCaller(
            principal_id="mcp-ip-test",
            client_ip="10.20.30.40",
            client_ip_source="socket",
            base_url="https://canvas.internal",
        )

    def tearDown(self):
        self.service = None
        self.store = None
        self.controls = None
        self.asset_service = None
        gc.collect()
        self.directory.cleanup()

    def _register_asset(self, owner_id: str, asset_id: str, *, kind: str = "image") -> Path:
        base = self.output_dir / "users" / owner_id
        if kind == "input":
            base = base / "inputs"
        base = base / "2026" / "08" / "13"
        base.mkdir(parents=True, exist_ok=True)
        media = base / f"{asset_id}.png"
        metadata_path = base / f"{asset_id}.json"
        media.write_bytes(b"test-image-bytes")
        metadata = {
            "id": asset_id,
            "owner": owner_id,
            "kind": kind,
            "mime": "image/png",
            "bytes": len(b"test-image-bytes"),
            "sha256": "abc",
            "created_at": "2026-08-13T00:00:00+00:00",
            "status": "active",
            "thumb": None,
        }
        atomic_write_json(metadata_path, metadata)
        self.asset_service.register(
            owner_id=owner_id,
            kind=kind,
            media_path=str(media),
            metadata_path=str(metadata_path),
            metadata=metadata,
        )
        return media

    @staticmethod
    def _png_base64() -> str:
        image = Image.new("RGBA", (8, 6), (10, 20, 30, 128))
        out = BytesIO()
        image.save(out, format="PNG")
        return base64.b64encode(out.getvalue()).decode("ascii")

    def test_create_image_uses_capability_controls_and_mcp_audit_context(self):
        response = self.service.create_image(
            self.caller,
            prompt="A clean blue potion icon",
            aspect_ratio="square",
            image_size="2K",
            idempotency_key="potion-intent-001",
            cost_confirmed=False,
        )

        self.assertEqual(response["status"], "queued")
        job = self.manager.get(response["job_id"])
        self.assertEqual(job.payload["capability"], "create_image")
        self.assertEqual(job.payload["workflow_id"], "NanoBanana")
        self.assertEqual(job.payload["request_source"], "mcp")
        self.assertEqual(job.payload["principal_id"], "mcp-ip-test")
        self.assertEqual(job.payload["client_ip"], "10.20.30.40")
        self.assertEqual(job.payload["idempotency_key"], "potion-intent-001")

    def test_create_image_with_owned_reference_uses_edit_capability(self):
        self._register_asset(self.caller.principal_id, "reference123", kind="input")
        response = self.service.create_image(
            self.caller,
            prompt="Turn it into a blue potion icon",
            aspect_ratio="square",
            image_size="2K",
            idempotency_key="potion-edit-001",
            cost_confirmed=False,
            reference_image_ids=["reference123"],
        )

        job = self.manager.get(response["job_id"])
        self.assertEqual(job.payload["capability_variant"], "edit")
        self.assertEqual(job.payload["workflow_id"], "NanoBanana_Img2Img")
        self.assertEqual(job.payload["input_image_ids"], ["reference123"])

        self._register_asset("mcp-ip-other", "other-reference", kind="image")
        with self.assertRaisesRegex(ValueError, "Reference image not found"):
            self.service.create_image(
                self.caller,
                prompt="Use someone else's image",
                aspect_ratio="square",
                image_size="2K",
                idempotency_key="other-edit-001",
                cost_confirmed=False,
                reference_image_ids=["other-reference"],
            )

    def test_create_game_ui_assets_uses_stable_capability_contract(self):
        self._register_asset(self.caller.principal_id, "ui-reference", kind="input")
        response = self.service.create_game_ui_assets(
            self.caller,
            prompt="Four matching fire spell icons",
            background_mode="transparent",
            image_quality="medium",
            idempotency_key="game-ui-intent-001",
            cost_confirmed=False,
            reference_image_ids=["ui-reference"],
        )

        job = self.manager.get(response["job_id"])
        self.assertEqual(job.payload["capability"], "create_game_ui_assets")
        self.assertEqual(job.payload["capability_variant"], "default")
        self.assertEqual(job.payload["workflow_id"], "GameUI_Elements")
        self.assertEqual(job.payload["input_image_ids"], ["ui-reference"])
        self.assertEqual(job.payload["game_ui_background_mode"], "transparent")
        self.assertEqual(job.payload["game_ui_grid"], "2x2")
        self.assertEqual(response["output_contract"]["asset_count"], 4)

    def test_client_attachment_registration_is_deduplicated(self):
        encoded = self._png_base64()
        first = self.service.create_input_image_asset(
            self.caller,
            image_base64=encoded,
            mime_type="image/png",
            filename="attachment.png",
        )
        second = self.service.create_input_image_asset(
            self.caller,
            image_base64=encoded,
            mime_type="image/png",
            filename="attachment-retry.png",
        )
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["asset_id"], second["asset_id"])
        self.assertEqual(first["kind"], "input")

    def test_image_asset_listing_and_lookup_are_owner_scoped(self):
        self._register_asset(self.caller.principal_id, "owned-image", kind="image")
        self._register_asset(self.caller.principal_id, "owned-input", kind="input")
        self._register_asset("mcp-ip-other", "other-image", kind="image")

        listed = self.service.list_image_assets(
            self.caller,
            asset_kind="all",
            limit=10,
            offset=0,
        )
        self.assertEqual({item["asset_id"] for item in listed["items"]}, {"owned-image", "owned-input"})
        self.assertEqual(listed["total"], 2)
        self.assertTrue(listed["items"][0]["content_url"].startswith("https://canvas.internal/outputs/"))

        item = self.service.get_image_asset(self.caller, "owned-image")
        self.assertEqual(item["asset_id"], "owned-image")
        self.assertNotIn("path", item)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.service.get_image_asset(self.caller, "other-image")

    def test_job_results_are_owner_scoped_and_paths_gain_absolute_urls(self):
        job = self.manager.enqueue(self.caller.principal_id, "generate", {})
        job.status = "complete"
        job.progress = 100
        job.result = {
            "image_path": "/outputs/mcp-ip-test/asset.png",
            "asset_group": {
                "download_url": "/outputs/mcp-ip-test/group.zip",
                "items": [{"url": "/outputs/mcp-ip-test/item.png"}],
            },
        }

        result = self.service.get_result(self.caller, job.id)
        self.assertTrue(result["ready"])
        self.assertEqual(
            result["result"]["image_url"],
            "https://canvas.internal/outputs/mcp-ip-test/asset.png",
        )
        self.assertEqual(
            result["result"]["asset_group"]["download_url"],
            "https://canvas.internal/outputs/mcp-ip-test/group.zip",
        )
        self.assertEqual(
            result["result"]["asset_group"]["items"][0]["url"],
            "https://canvas.internal/outputs/mcp-ip-test/item.png",
        )

        other = McpCaller("mcp-ip-other", "10.20.30.41", "socket", "https://canvas.internal")
        with self.assertRaises(ValueError):
            self.service.get_result(other, job.id)

    def test_persisted_job_can_be_read_after_memory_is_gone(self):
        self.store.upsert_job(
            {
                "id": "b" * 32,
                "owner_id": self.caller.principal_id,
                "type": "generate",
                "status": "complete",
                "progress": 100,
                "created_at": 1,
                "result": {"image_path": "/outputs/archive.png"},
            }
        )
        result = self.service.get_result(self.caller, "b" * 32)
        self.assertTrue(result["ready"])
        self.assertEqual(result["result"]["image_url"], "https://canvas.internal/outputs/archive.png")

    def test_completed_image_is_returned_as_mcp_image_content(self):
        output_dir = os.path.join(self.directory.name, "outputs")
        os.makedirs(output_dir, exist_ok=True)
        Path(output_dir, "result.png").write_bytes(b"test-image-bytes")
        with mock.patch.dict(SERVER_CONFIG, {"output_dir": output_dir}):
            content = _result_image_content(
                {"result": {"image_path": "/outputs/result.png"}}
            )
        self.assertIsNotNone(content)
        self.assertEqual(content.type, "image")
        self.assertEqual(content.mime_type, "image/png")

    def test_tool_contract_marks_read_write_and_open_world_boundaries(self):
        integration = create_mcp_integration(self.manager, self.store, self.controls, self.asset_service)
        tools = asyncio.run(integration.server.list_tools())
        by_name = {tool.name: tool for tool in tools}
        self.assertEqual(set(by_name), {
            "list_generation_capabilities",
            "get_generation_capability",
            "get_generation_job",
            "get_generation_result",
            "create_managed_image_asset",
            "list_image_assets",
            "get_image_asset",
            "create_input_image_asset",
            "create_game_ui_assets",
        })
        self.assertNotIn("create_image", by_name)
        self.assertFalse(by_name["create_managed_image_asset"].annotations.read_only_hint)
        self.assertTrue(by_name["create_managed_image_asset"].annotations.open_world_hint)
        self.assertTrue(by_name["get_generation_job"].annotations.read_only_hint)
        self.assertTrue(by_name["list_image_assets"].annotations.read_only_hint)
        self.assertTrue(by_name["get_image_asset"].annotations.read_only_hint)
        self.assertFalse(by_name["create_input_image_asset"].annotations.read_only_hint)
        self.assertFalse(by_name["create_input_image_asset"].annotations.open_world_hint)
        self.assertFalse(by_name["create_game_ui_assets"].annotations.read_only_hint)
        create_schema = by_name["create_managed_image_asset"].input_schema
        self.assertIn("idempotency_key", create_schema["required"])
        self.assertIn("company-managed", by_name["create_managed_image_asset"].description)

    def test_streamable_http_protocol_lists_and_invokes_tools(self):
        self._register_asset(_principal_for_ip("testclient"), "protocol-owned", kind="image")
        integration = create_mcp_integration(self.manager, self.store, self.controls, self.asset_service)
        headers = {"Accept": "application/json, text/event-stream"}
        with TestClient(integration.http_app) as client:
            initialized = client.post(
                "/",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "1.0"},
                    },
                },
            )
            self.assertEqual(initialized.status_code, 200, initialized.text)
            self.assertEqual(
                initialized.json()["result"]["serverInfo"]["version"],
                "0.4.0",
            )

            protocol_headers = {**headers, "MCP-Protocol-Version": "2025-06-18"}
            listed = client.post(
                "/",
                headers=protocol_headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            self.assertEqual(listed.status_code, 200, listed.text)
            names = {item["name"] for item in listed.json()["result"]["tools"]}
            self.assertIn("create_managed_image_asset", names)
            self.assertIn("list_image_assets", names)
            self.assertIn("get_image_asset", names)
            self.assertIn("create_input_image_asset", names)
            self.assertIn("create_game_ui_assets", names)
            self.assertNotIn("create_image", names)

            capabilities = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "list_generation_capabilities", "arguments": {}},
                },
            )
            public_capabilities = capabilities.json()["result"]["structuredContent"]["capabilities"]
            self.assertEqual(
                {item["name"] for item in public_capabilities},
                {"create_managed_image_asset", "create_game_ui_assets"},
            )

            called = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "create_managed_image_asset",
                        "arguments": {
                            "prompt": "A minimal red gem icon",
                            "idempotency_key": "protocol-gem-001",
                        },
                    },
                },
            )
            self.assertEqual(called.status_code, 200, called.text)
            structured = called.json()["result"]["structuredContent"]
            self.assertEqual(structured["status"], "queued")

            listed_assets = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {
                        "name": "list_image_assets",
                        "arguments": {"asset_kind": "image", "limit": 10, "offset": 0},
                    },
                },
            )
            listed_structured = listed_assets.json()["result"]["structuredContent"]
            self.assertEqual(listed_structured["total"], 1)
            self.assertEqual(listed_structured["items"][0]["asset_id"], "protocol-owned")

            fetched_asset = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {
                        "name": "get_image_asset",
                        "arguments": {"asset_id": "protocol-owned"},
                    },
                },
            )
            fetched_result = fetched_asset.json()["result"]
            self.assertEqual(fetched_result["structuredContent"]["asset_id"], "protocol-owned")
            self.assertTrue(any(item["type"] == "image" for item in fetched_result["content"]))

            attachment_arguments = {
                "image_base64": self._png_base64(),
                "mime_type": "image/png",
                "filename": "protocol-attachment.png",
            }
            attachment = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": "create_input_image_asset", "arguments": attachment_arguments},
                },
            )
            attachment_result = attachment.json()["result"]["structuredContent"]
            self.assertFalse(attachment_result["duplicate"])
            self.assertEqual(attachment_result["kind"], "input")

            attachment_retry = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 8,
                    "method": "tools/call",
                    "params": {"name": "create_input_image_asset", "arguments": attachment_arguments},
                },
            )
            retry_result = attachment_retry.json()["result"]["structuredContent"]
            self.assertTrue(retry_result["duplicate"])
            self.assertEqual(retry_result["asset_id"], attachment_result["asset_id"])

    def test_mcp_cidr_allowlist_denies_other_clients_and_invalid_policy_fails_closed(self):
        integration = create_mcp_integration(self.manager, self.store, self.controls, self.asset_service)
        with mock.patch.dict(os.environ, {"MCP_ALLOWED_CLIENT_CIDRS": "10.0.0.0/8"}):
            with TestClient(integration.http_app) as client:
                denied = client.post("/", json={})
                self.assertEqual(denied.status_code, 403)

        invalid_integration = create_mcp_integration(self.manager, self.store, self.controls, self.asset_service)
        with mock.patch.dict(os.environ, {"MCP_ALLOWED_CLIENT_CIDRS": "not-a-cidr"}):
            with TestClient(invalid_integration.http_app) as client:
                invalid = client.post("/", json={})
                self.assertEqual(invalid.status_code, 503)


if __name__ == "__main__":
    unittest.main()
