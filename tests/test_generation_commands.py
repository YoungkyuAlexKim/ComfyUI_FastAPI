import gc
import tempfile
import unittest

from app.job_store import JobStore
from app.services.generation_commands import (
    CAPABILITY_ROUTES,
    DEFAULT_CAPABILITY_DISPATCHER,
    GenerationCommand,
    GenerationContext,
    dispatch_legacy_web_request,
    resolve_client_ip,
)
from app.workflow_configs import WORKFLOW_CONFIGS


class GenerationCommandTests(unittest.TestCase):
    def setUp(self):
        self.context = GenerationContext(
            principal_id="anon-user-1",
            source="web",
            client_ip="10.1.2.3",
            client_ip_source="socket",
            request_id="request-1",
            idempotency_key="request-key-1",
        )

    def test_registry_covers_every_current_workflow(self):
        self.assertEqual(set(CAPABILITY_ROUTES.values()), set(WORKFLOW_CONFIGS))

    def test_legacy_web_request_round_trips_through_capability_route(self):
        resolved = dispatch_legacy_web_request(
            {
                "workflow_id": "NanoBanana_Img2Img",
                "user_prompt": "조명만 따뜻하게 바꿔줘",
                "aspect_ratio": "auto",
                "input_image_id": "image-1",
            },
            self.context,
        )

        self.assertEqual(resolved.command.capability, "create_image")
        self.assertEqual(resolved.command.variant, "edit")
        self.assertEqual(resolved.workflow_id, "NanoBanana_Img2Img")
        self.assertEqual(resolved.payload["workflow_id"], "NanoBanana_Img2Img")
        self.assertEqual(resolved.payload["user_prompt"], "조명만 따뜻하게 바꿔줘")

    def test_game_ui_resolves_to_gpt_image_2(self):
        resolved = dispatch_legacy_web_request(
            {
                "workflow_id": "GameUI_Elements",
                "user_prompt": "얼음 스킬 아이콘",
                "aspect_ratio": "square",
            },
            self.context,
        )
        self.assertEqual(resolved.command.capability, "create_game_ui_assets")
        self.assertEqual(resolved.provider, "openrouter")
        self.assertEqual(resolved.model, "openai/gpt-image-2")
        self.assertEqual(resolved.payload["resolved_image_size"], "2K")
        self.assertEqual(resolved.payload["resolved_image_quality"], "medium")

    def test_server_owned_audit_fields_replace_spoofed_payload_values(self):
        resolved = dispatch_legacy_web_request(
            {
                "workflow_id": "NanoBanana",
                "user_prompt": "테스트",
                "aspect_ratio": "square",
                "capability": "generate_music",
                "request_source": "mcp",
                "principal_id": "someone-else",
                "client_ip": "203.0.113.99",
                "resolved_provider": "fake",
            },
            self.context,
        )
        payload = resolved.payload
        self.assertEqual(payload["capability"], "create_image")
        self.assertEqual(payload["request_source"], "web")
        self.assertEqual(payload["principal_id"], "anon-user-1")
        self.assertEqual(payload["client_ip"], "10.1.2.3")
        self.assertEqual(payload["resolved_provider"], "openrouter")
        self.assertEqual(payload["request_id"], "request-1")
        self.assertEqual(payload["idempotency_key"], "request-key-1")

    def test_direct_capability_command_uses_same_dispatcher(self):
        command = GenerationCommand(
            capability="create_character_sheet",
            variant="expressions",
            parameters={"user_prompt": "수채화", "input_image_id": "image-1"},
            context=self.context,
        )
        resolved = DEFAULT_CAPABILITY_DISPATCHER.resolve(command)
        self.assertEqual(resolved.workflow_id, "NanoBanana_ExpressionPortraitSheet")

    def test_unknown_workflow_is_rejected_before_enqueue(self):
        with self.assertRaises(ValueError):
            dispatch_legacy_web_request(
                {"workflow_id": "RemovedWorkflow", "user_prompt": "test"},
                self.context,
            )

    def test_job_store_persists_dispatch_and_ip_audit_metadata(self):
        resolved = dispatch_legacy_web_request(
            {
                "workflow_id": "NanoBanana",
                "user_prompt": "테스트",
                "aspect_ratio": "square",
            },
            self.context,
        )
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(f"{directory}/jobs.db")
            store.upsert_job(
                {
                    "id": "job-1",
                    "owner_id": self.context.principal_id,
                    "type": "generate",
                    "status": "queued",
                    "progress": 0,
                    "created_at": 1,
                    "payload": resolved.payload,
                }
            )
            persisted = store.fetch_recent(1)[0]
            # sqlite3 connection finalizers can otherwise lag on Windows and
            # keep the temporary DB locked during directory cleanup.
            store = None
            gc.collect()

        self.assertEqual(persisted["workflow_id"], "NanoBanana")
        self.assertEqual(persisted["payload"]["capability"], "create_image")
        self.assertEqual(persisted["payload"]["client_ip"], "10.1.2.3")
        self.assertEqual(persisted["payload"]["request_source"], "web")


class ClientIpResolutionTests(unittest.TestCase):
    def test_forwarded_header_is_ignored_without_trusted_proxy_config(self):
        value, source = resolve_client_ip("10.0.0.9", "203.0.113.5", "")
        self.assertEqual((value, source), ("10.0.0.9", "socket"))

    def test_forwarded_header_is_ignored_from_untrusted_peer(self):
        value, source = resolve_client_ip("10.0.0.9", "203.0.113.5", "192.168.0.0/16")
        self.assertEqual((value, source), ("10.0.0.9", "socket"))

    def test_trusted_proxy_chain_returns_closest_untrusted_hop(self):
        value, source = resolve_client_ip(
            "10.0.0.9",
            "198.51.100.200, 203.0.113.5, 10.0.0.8",
            "10.0.0.0/8",
        )
        self.assertEqual((value, source), ("203.0.113.5", "forwarded"))

    def test_malformed_forwarded_header_falls_back_to_socket(self):
        value, source = resolve_client_ip("10.0.0.9", "not-an-ip", "10.0.0.0/8")
        self.assertEqual((value, source), ("10.0.0.9", "socket"))


if __name__ == "__main__":
    unittest.main()
