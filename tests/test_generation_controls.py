import gc
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import mock

from app.services.generation_controls import GenerationControlService, GenerationPolicyError


class GenerationControlTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.directory.name, "controls.db")
        self.controls = GenerationControlService(self.db_path, timezone_name="Asia/Seoul")

    def tearDown(self):
        self.controls = None
        gc.collect()
        self.directory.cleanup()

    def payload(self, *, request_id="request-1", idempotency_key="idem-key-1", source="web"):
        return {
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "request_source": source,
            "principal_id": "anon-user-1",
            "client_ip": "10.1.2.3",
            "capability": "create_game_ui_assets",
            "capability_variant": "default",
            "workflow_id": "GameUI_Elements",
            "resolved_workflow_id": "GameUI_Elements",
            "resolved_provider": "openrouter",
            "resolved_model": "openai/gpt-image-2",
            "image_size": "2K",
            "image_quality": "medium",
        }

    def test_defaults_allow_requests_without_changing_current_web_behavior(self):
        result = self.controls.admit(self.payload())
        self.assertFalse(result.is_duplicate)
        self.assertEqual(result.estimated_cost_usd, 0)
        self.assertEqual(self.controls.summary()["total"], 1)

    def test_idempotency_replay_returns_original_job(self):
        payload = self.payload()
        admitted = self.controls.admit(payload)
        payload["control_request_id"] = admitted.control_request_id
        job = SimpleNamespace(id="job-1", status="queued", payload=payload)
        self.controls.sync_job(job)

        replay_payload = self.payload(request_id="request-2")
        replay = self.controls.admit(replay_payload)
        self.assertTrue(replay.is_duplicate)
        self.assertEqual(replay.duplicate_job_id, "job-1")

    def test_enqueue_failure_releases_limit_and_allows_same_key_retry(self):
        self.controls.update_policy({"daily_request_limit": 1})
        first = self.controls.admit(self.payload())
        self.controls.mark_enqueue_failed(first.control_request_id, "queue full")

        retry = self.controls.admit(self.payload(request_id="request-2"))
        self.assertFalse(retry.is_duplicate)
        self.assertEqual(self.controls.summary()["total"], 1)

    def test_daily_request_limit_rejects_and_audits(self):
        self.controls.update_policy({"daily_request_limit": 1})
        self.controls.admit(self.payload())
        with self.assertRaises(GenerationPolicyError) as raised:
            self.controls.admit(self.payload(request_id="request-2", idempotency_key="idem-key-2"))
        self.assertEqual(raised.exception.code, "daily_request_limit_reached")
        summary = self.controls.summary()
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["rejected"], 1)

    def test_daily_request_limit_is_atomic_under_concurrent_admission(self):
        self.controls.update_policy({"daily_request_limit": 3})

        def attempt(index):
            try:
                self.controls.admit(
                    self.payload(request_id=f"request-{index}", idempotency_key=f"idem-key-{index}")
                )
                return "accepted"
            except GenerationPolicyError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=8) as executor:
            decisions = list(executor.map(attempt, range(8)))

        self.assertEqual(decisions.count("accepted"), 3)
        self.assertEqual(decisions.count("daily_request_limit_reached"), 5)
        self.assertEqual(self.controls.summary()["total"], 3)

    def test_global_mcp_and_capability_kill_switches(self):
        cases = [
            ({"generation_enabled": False}, self.payload(), "generation_disabled"),
            ({"mcp_enabled": False}, self.payload(source="mcp"), "mcp_disabled"),
            (
                {"capability_enabled": {"create_game_ui_assets": False}},
                self.payload(),
                "capability_disabled",
            ),
        ]
        for index, (policy, payload, expected_code) in enumerate(cases):
            with self.subTest(expected_code=expected_code):
                path = os.path.join(self.directory.name, f"switch-{index}.db")
                controls = GenerationControlService(path, timezone_name="Asia/Seoul")
                controls.update_policy(policy)
                with self.assertRaises(GenerationPolicyError) as raised:
                    controls.admit(payload)
                self.assertEqual(raised.exception.code, expected_code)

    def test_environment_kill_switch_cannot_be_overridden_by_saved_policy(self):
        self.controls.update_policy({"generation_enabled": True, "mcp_enabled": True})
        with mock.patch.dict(
            os.environ,
            {"GENERATION_ENABLED": "false", "MCP_GENERATION_ENABLED": "false"},
        ):
            policy = self.controls.get_policy()
        self.assertFalse(policy["generation_enabled"])
        self.assertFalse(policy["mcp_enabled"])

    def test_estimated_cost_can_require_confirmation(self):
        self.controls.update_policy(
            {
                "cost_estimates_usd": {"openai/gpt-image-2|2K|medium": 0.25},
                "cost_confirmation_threshold_usd": 0.2,
            }
        )
        with self.assertRaises(GenerationPolicyError) as raised:
            self.controls.admit(self.payload())
        self.assertEqual(raised.exception.code, "cost_confirmation_required")
        self.assertEqual(raised.exception.details["estimated_cost_usd"], 0.25)

        accepted = self.controls.admit(self.payload(request_id="request-2"), cost_confirmed=True)
        self.assertEqual(accepted.estimated_cost_usd, 0.25)

    def test_daily_cost_limit_reserves_estimated_spend_atomically(self):
        self.controls.update_policy(
            {
                "cost_estimates_usd": {"openai/gpt-image-2": 0.6},
                "daily_cost_limit_usd": 1.0,
            }
        )
        self.controls.admit(self.payload())
        with self.assertRaises(GenerationPolicyError) as raised:
            self.controls.admit(self.payload(request_id="request-2", idempotency_key="idem-key-2"))
        self.assertEqual(raised.exception.code, "daily_cost_limit_reached")

    def test_actual_provider_cost_is_synced_to_summary_and_events(self):
        admitted = self.controls.admit(self.payload())
        payload = self.payload()
        payload.update({"control_request_id": admitted.control_request_id, "actual_cost_usd": 0.123456})
        self.controls.sync_job(SimpleNamespace(id="job-1", status="complete", payload=payload))

        summary = self.controls.summary()
        self.assertEqual(summary["complete"], 1)
        self.assertEqual(summary["actual_cost_usd"], 0.123456)
        self.assertEqual(summary["by_source"][0]["name"], "web")
        self.assertEqual(summary["by_capability"][0]["name"], "create_game_ui_assets")
        self.assertEqual(summary["by_model"][0]["actual_cost_usd"], 0.123456)
        events = self.controls.recent_events()
        self.assertTrue(any(event["event_type"] == "job_status" for event in events))


if __name__ == "__main__":
    unittest.main()
