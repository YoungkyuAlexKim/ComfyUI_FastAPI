import asyncio
import gc
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from app.job_store import JobStore
from app.config import SERVER_CONFIG
from app.mcp_server import (
    McpCaller,
    McpGenerationService,
    _result_image_content,
    create_mcp_integration,
)
from app.services.generation_controls import GenerationControlService


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
        self.service = McpGenerationService(self.manager, self.store, self.controls)
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
        gc.collect()
        self.directory.cleanup()

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

    def test_job_results_are_owner_scoped_and_paths_gain_absolute_urls(self):
        job = self.manager.enqueue(self.caller.principal_id, "generate", {})
        job.status = "complete"
        job.progress = 100
        job.result = {"image_path": "/outputs/mcp-ip-test/asset.png"}

        result = self.service.get_result(self.caller, job.id)
        self.assertTrue(result["ready"])
        self.assertEqual(
            result["result"]["image_url"],
            "https://canvas.internal/outputs/mcp-ip-test/asset.png",
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

    def test_tool_contract_marks_only_managed_image_asset_as_write(self):
        integration = create_mcp_integration(self.manager, self.store, self.controls)
        tools = asyncio.run(integration.server.list_tools())
        by_name = {tool.name: tool for tool in tools}
        self.assertEqual(set(by_name), {
            "list_generation_capabilities",
            "get_generation_capability",
            "get_generation_job",
            "get_generation_result",
            "create_managed_image_asset",
        })
        self.assertNotIn("create_image", by_name)
        self.assertFalse(by_name["create_managed_image_asset"].annotations.read_only_hint)
        self.assertTrue(by_name["create_managed_image_asset"].annotations.open_world_hint)
        self.assertTrue(by_name["get_generation_job"].annotations.read_only_hint)
        create_schema = by_name["create_managed_image_asset"].input_schema
        self.assertIn("idempotency_key", create_schema["required"])
        self.assertIn("company-managed", by_name["create_managed_image_asset"].description)

    def test_streamable_http_protocol_lists_and_invokes_tools(self):
        integration = create_mcp_integration(self.manager, self.store, self.controls)
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
                "0.2.0",
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
            self.assertEqual(public_capabilities[0]["name"], "create_managed_image_asset")

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

    def test_mcp_cidr_allowlist_denies_other_clients_and_invalid_policy_fails_closed(self):
        integration = create_mcp_integration(self.manager, self.store, self.controls)
        with mock.patch.dict(os.environ, {"MCP_ALLOWED_CLIENT_CIDRS": "10.0.0.0/8"}):
            with TestClient(integration.http_app) as client:
                denied = client.post("/", json={})
                self.assertEqual(denied.status_code, 403)

        invalid_integration = create_mcp_integration(self.manager, self.store, self.controls)
        with mock.patch.dict(os.environ, {"MCP_ALLOWED_CLIENT_CIDRS": "not-a-cidr"}):
            with TestClient(invalid_integration.http_app) as client:
                invalid = client.post("/", json={})
                self.assertEqual(invalid.status_code, 503)


if __name__ == "__main__":
    unittest.main()
