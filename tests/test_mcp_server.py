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
    _generation_result_tool_result,
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

    def _register_asset(
        self,
        owner_id: str,
        asset_id: str,
        *,
        kind: str = "image",
        source_job_id: str | None = None,
        prompt: str = "",
    ) -> Path:
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
            "source_job_id": source_job_id,
            "prompt": prompt,
        }
        atomic_write_json(metadata_path, metadata)
        self.asset_service.register(
            owner_id=owner_id,
            kind=kind,
            media_path=str(media),
            metadata_path=str(metadata_path),
            metadata=metadata,
            source_job_id=source_job_id,
        )
        return media

    def _plan(
        self,
        capability: str,
        *,
        prompt: str,
        options: dict,
        reference_image_ids=None,
        selection_mode: str = "clarify",
    ):
        plan = self.service.plan_generation(
            self.caller,
            capability=capability,
            prompt=prompt,
            options=options,
            selection_mode=selection_mode,
            reference_image_ids=reference_image_ids,
        )
        self.assertTrue(plan["ready_to_generate"], plan)
        self.assertIsNotNone(plan["plan_id"])
        return plan

    def test_create_image_uses_capability_controls_and_mcp_audit_context(self):
        plan = self._plan(
            "create_managed_image_asset",
            prompt="A clean blue potion icon",
            options={
                "image_model": "google/gemini-3-pro-image",
                "aspect_ratio": "square",
                "image_size": "2K",
            },
        )
        response = self.service.create_image(
            self.caller,
            plan_id=plan["plan_id"],
            prompt="A clean blue potion icon",
            image_model="google/gemini-3-pro-image",
            aspect_ratio="square",
            image_size="2K",
            image_quality=None,
            idempotency_key="potion-intent-001",
            cost_confirmed=False,
        )

        self.assertEqual(response["status"], "queued")
        self.assertIsNone(response["estimated_cost_usd"])
        self.assertFalse(response["cost_estimate_available"])
        job = self.manager.get(response["job_id"])
        self.assertEqual(job.payload["capability"], "create_image")
        self.assertEqual(job.payload["workflow_id"], "NanoBanana")
        self.assertEqual(job.payload["request_source"], "mcp")
        self.assertEqual(job.payload["principal_id"], "mcp-ip-test")
        self.assertEqual(job.payload["client_ip"], "10.20.30.40")
        self.assertEqual(job.payload["idempotency_key"], "potion-intent-001")

    def test_generation_plan_requires_clarification_and_prevents_argument_drift(self):
        ambiguous = self.service.plan_generation(
            self.caller,
            capability="create_managed_image_asset",
            prompt="A fantasy character",
            options={},
            selection_mode="clarify",
        )
        self.assertFalse(ambiguous["ready_to_generate"])
        self.assertIsNone(ambiguous["plan_id"])
        self.assertIn("image_model", ambiguous["missing_decisions"])

        ready = self._plan(
            "create_managed_image_asset",
            prompt="A fantasy character",
            options={
                "image_model": "google/gemini-3.1-flash-image",
                "aspect_ratio": "portrait",
                "image_size": "1K",
            },
        )
        with self.assertRaisesRegex(ValueError, "arguments changed"):
            self.service.create_image(
                self.caller,
                plan_id=ready["plan_id"],
                prompt="A fantasy character",
                image_model="google/gemini-3.1-flash-image",
                aspect_ratio="portrait",
                image_size="2K",
                image_quality=None,
                idempotency_key=ready["suggested_idempotency_key"],
                cost_confirmed=False,
            )

    def test_character_plan_requires_one_owned_reference(self):
        result = self.service.plan_generation(
            self.caller,
            capability="create_character_sheet",
            prompt="",
            options={
                "sheet_type": "turnaround",
                "count": 3,
                "image_size": "1K",
                "image_quality": "low",
            },
            selection_mode="clarify",
        )
        self.assertFalse(result["ready_to_generate"])
        self.assertEqual(result["missing_decisions"], ["reference_image_id"])
        self.assertIsNone(result["plan_id"])

    def test_remove_background_requires_owned_image_and_queues_fixed_local_workflow(self):
        missing = self.service.plan_generation(
            self.caller,
            capability="remove_background",
            prompt="",
            options={},
            selection_mode="clarify",
        )
        self.assertFalse(missing["ready_to_generate"])
        self.assertEqual(missing["missing_decisions"], ["reference_image_id"])

        self._register_asset(self.caller.principal_id, "rmbg-input", kind="input")
        plan = self._plan(
            "remove_background",
            prompt="",
            options={"mask_blur": 2, "mask_offset": -1},
            reference_image_ids=["rmbg-input"],
        )
        self.assertEqual(plan["estimated_cost_usd"], 0.0)
        self.assertFalse(plan["provider_cost"])
        response = self.service.remove_background(
            self.caller,
            plan_id=plan["plan_id"],
            image_id="rmbg-input",
            mask_blur=2,
            mask_offset=-1,
            idempotency_key=plan["suggested_idempotency_key"],
        )
        self.assertEqual(response["estimated_cost_usd"], 0.0)
        job = self.manager.get(response["job_id"])
        self.assertEqual(job.payload["capability"], "remove_background")
        self.assertEqual(job.payload["workflow_id"], "RMBG2")
        self.assertEqual(job.payload["resolved_provider"], "comfyui")
        self.assertEqual(job.payload["resolved_model"], "RMBG-2.0")
        self.assertEqual(job.payload["image_model"], "RMBG-2.0")
        self.assertEqual(job.payload["input_image_id"], "rmbg-input")
        self.assertEqual(job.payload["rmbg_mask_blur"], 2)
        self.assertEqual(job.payload["rmbg_mask_offset"], -1)

    def test_create_image_with_owned_reference_uses_edit_capability(self):
        self._register_asset(self.caller.principal_id, "reference123", kind="input")
        plan = self._plan(
            "create_managed_image_asset",
            prompt="Turn it into a blue potion icon",
            options={
                "image_model": "google/gemini-3-pro-image",
                "aspect_ratio": "auto",
                "image_size": "2K",
            },
            reference_image_ids=["reference123"],
        )
        response = self.service.create_image(
            self.caller,
            plan_id=plan["plan_id"],
            prompt="Turn it into a blue potion icon",
            image_model="google/gemini-3-pro-image",
            aspect_ratio="auto",
            image_size="2K",
            image_quality=None,
            idempotency_key="potion-edit-001",
            cost_confirmed=False,
            reference_image_ids=["reference123"],
        )

        job = self.manager.get(response["job_id"])
        self.assertEqual(job.payload["capability_variant"], "edit")
        self.assertEqual(job.payload["workflow_id"], "NanoBanana_Img2Img")
        self.assertEqual(job.payload["input_image_ids"], ["reference123"])
        self.assertEqual(job.payload["aspect_ratio"], "auto")

        self._register_asset("mcp-ip-other", "other-reference", kind="image")
        with self.assertRaisesRegex(ValueError, "Reference image not found"):
            self.service.create_image(
                self.caller,
                plan_id="plan_" + ("x" * 32),
                prompt="Use someone else's image",
                image_model="google/gemini-3-pro-image",
                aspect_ratio="square",
                image_size="2K",
                image_quality=None,
                idempotency_key="other-edit-001",
                cost_confirmed=False,
                reference_image_ids=["other-reference"],
            )

    def test_create_game_ui_assets_uses_stable_capability_contract(self):
        self._register_asset(self.caller.principal_id, "ui-reference", kind="input")
        plan = self._plan(
            "create_game_ui_assets",
            prompt="Four matching fire spell icons",
            options={"background_mode": "transparent", "image_quality": "medium"},
            reference_image_ids=["ui-reference"],
        )
        response = self.service.create_game_ui_assets(
            self.caller,
            plan_id=plan["plan_id"],
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
        self.assertIsNone(response["estimated_cost_usd"])
        self.assertFalse(response["cost_estimate_available"])

    def test_create_character_sheet_maps_variants_counts_and_reference(self):
        self._register_asset(self.caller.principal_id, "character-reference", kind="input")
        turnaround_plan = self._plan(
            "create_character_sheet",
            prompt="clean cel shading",
            options={
                "sheet_type": "turnaround",
                "count": 3,
                "image_size": "1K",
                "image_quality": "low",
            },
            reference_image_ids=["character-reference"],
        )
        turnaround = self.service.create_character_sheet(
            self.caller,
            plan_id=turnaround_plan["plan_id"],
            reference_image_id="character-reference",
            sheet_type="turnaround",
            count=3,
            prompt="clean cel shading",
            image_size="1K",
            image_quality="low",
            idempotency_key="character-turnaround-001",
            cost_confirmed=False,
        )
        turnaround_job = self.manager.get(turnaround["job_id"])
        self.assertEqual(turnaround_job.payload["capability"], "create_character_sheet")
        self.assertEqual(turnaround_job.payload["capability_variant"], "turnaround")
        self.assertEqual(turnaround_job.payload["workflow_id"], "NanoBanana_TurnaroundSheet")
        self.assertEqual(turnaround_job.payload["input_image_ids"], ["character-reference"])
        self.assertEqual(turnaround_job.payload["aspect_ratio"], "landscape")
        self.assertEqual(turnaround_job.payload["image_model"], "openai/gpt-image-2")
        self.assertIn("Exact ordered views (3 total)", turnaround_job.payload["user_prompt"])
        self.assertEqual(turnaround["output_contract"]["count"], 3)

        expression_plan = self._plan(
            "create_character_sheet",
            prompt="watercolor",
            options={
                "sheet_type": "expressions",
                "count": 4,
                "image_size": "2K",
                "image_quality": "medium",
            },
            reference_image_ids=["character-reference"],
        )
        expressions = self.service.create_character_sheet(
            self.caller,
            plan_id=expression_plan["plan_id"],
            reference_image_id="character-reference",
            sheet_type="expressions",
            count=4,
            prompt="watercolor",
            image_size="2K",
            image_quality="medium",
            idempotency_key="character-expressions-001",
            cost_confirmed=False,
        )
        expression_job = self.manager.get(expressions["job_id"])
        self.assertEqual(expression_job.payload["workflow_id"], "NanoBanana_ExpressionPortraitSheet")
        self.assertEqual(expression_job.payload["aspect_ratio"], "square")
        self.assertIn("Exact grid: 2 columns x 2 rows", expression_job.payload["user_prompt"])
        self.assertIn("STYLE OVERRIDE (user)", expression_job.payload["user_prompt"])

    def test_character_sheet_rejects_count_for_other_variant(self):
        self._register_asset(self.caller.principal_id, "character-reference", kind="input")
        with self.assertRaisesRegex(ValueError, "count for expressions"):
            self.service.create_character_sheet(
                self.caller,
                plan_id="plan_" + ("x" * 32),
                reference_image_id="character-reference",
                sheet_type="expressions",
                count=5,
                prompt="",
                image_size="1K",
                image_quality="low",
                idempotency_key="character-invalid-001",
                cost_confirmed=False,
            )

    def test_create_storyboard_builds_exact_grid_and_continuity_request(self):
        self._register_asset(self.caller.principal_id, "story-reference", kind="image")
        plan = self._plan(
            "create_storyboard",
            prompt="The hero enters the ruins, finds the crystal, and escapes a collapse.",
            options={"cuts": 6, "image_size": "1K", "image_quality": "low"},
            reference_image_ids=["story-reference"],
        )
        response = self.service.create_storyboard(
            self.caller,
            plan_id=plan["plan_id"],
            reference_image_id="story-reference",
            prompt="The hero enters the ruins, finds the crystal, and escapes a collapse.",
            cuts=6,
            image_size="1K",
            image_quality="low",
            idempotency_key="storyboard-six-001",
            cost_confirmed=False,
        )
        job = self.manager.get(response["job_id"])
        self.assertEqual(job.payload["capability"], "create_storyboard")
        self.assertEqual(job.payload["capability_variant"], "default")
        self.assertEqual(job.payload["workflow_id"], "NanoBanana_StoryboardCutboard")
        self.assertEqual(job.payload["input_image_id"], "story-reference")
        self.assertEqual(job.payload["aspect_ratio"], "landscape")
        self.assertEqual(job.payload["image_model"], "openai/gpt-image-2")
        self.assertIn("CUTS: 6", job.payload["user_prompt"])
        self.assertIn("GRID: 2x3", job.payload["user_prompt"])
        self.assertEqual(response["output_contract"]["grid"], "2x3")

    def test_direct_input_upload_contract_forbids_base64(self):
        contract = self.service.prepare_input_image_upload(self.caller)
        self.assertEqual(
            contract["upload_url"],
            "https://canvas.internal/api/v1/mcp/inputs/upload",
        )
        self.assertEqual(contract["method"], "POST")
        self.assertEqual(contract["content_type"], "multipart/form-data")
        self.assertEqual(contract["file_field"], "file")
        self.assertFalse(contract["base64_allowed"])
        self.assertIn("file=@<LOCAL_IMAGE_PATH>", contract["curl_template"])

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
        self._register_asset(
            self.caller.principal_id,
            "generated-asset",
            source_job_id=job.id,
            prompt="A clean blue potion icon",
        )

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
        self.assertEqual(len(result["result"]["assets"]), 1)
        self.assertEqual(result["result"]["assets"][0]["asset_id"], "generated-asset")
        self.assertEqual(
            result["result"]["assets"][0]["metadata"]["prompt"],
            "A clean blue potion icon",
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

    def test_generation_result_includes_image_native_presentation_and_link_fallback(self):
        output_dir = os.path.join(self.directory.name, "outputs")
        os.makedirs(output_dir, exist_ok=True)
        original = Image.new("RGB", (1200, 900), (32, 96, 160))
        original.save(Path(output_dir, "result.png"), format="PNG")
        structured = {
            "job_id": "a" * 32,
            "status": "complete",
            "ready": True,
            "result": {
                "image_path": "/outputs/result.png",
                "image_url": "http://10.100.90.242:8000/outputs/result.png",
            },
        }
        with mock.patch.dict(SERVER_CONFIG, {"output_dir": output_dir}):
            result = _generation_result_tool_result(structured)

        self.assertEqual(result.content[0].type, "image")
        self.assertEqual(result.content[0].mime_type, "image/webp")
        self.assertEqual(result.content[0].annotations.audience, ["user"])
        self.assertEqual(result.content[0].annotations.priority, 1.0)
        with Image.open(BytesIO(base64.b64decode(result.content[0].data))) as preview:
            self.assertEqual(preview.format, "WEBP")
            self.assertEqual(preview.size, (768, 576))

        self.assertEqual(result.content[1].type, "text")
        self.assertIn(
            "[Open image in LC AI Canvas](http://10.100.90.242:8000/outputs/result.png)",
            result.content[1].text,
        )
        self.assertIn("USER-VISIBLE IMAGE PRESENTATION IS REQUIRED", result.content[1].text)
        self.assertIn("Tool-result visibility alone is not evidence", result.content[1].text)
        self.assertIn("Codex or Claude Code", result.content[1].text)
        response = result.model_dump(by_alias=True)["structuredContent"]
        presentation = response["presentation"]
        self.assertTrue(presentation["required"])
        self.assertEqual(presentation["preferred"], "download_then_native_image_viewer")
        self.assertEqual(
            presentation["source_url"],
            "http://10.100.90.242:8000/outputs/result.png",
        )
        self.assertEqual(presentation["suggested_filename"], f"lc-ai-canvas-{'a' * 32}.png")
        self.assertEqual(presentation["storage_scope"], "client_temporary_or_session_workspace")
        self.assertFalse(presentation["tool_result_visibility_is_user_visibility"])
        self.assertTrue(presentation["local_agent_action_required_when_available"])
        self.assertFalse(presentation["regenerate_for_preview"])
        self.assertTrue(presentation["keep_original_link"])
        self.assertEqual(presentation["fallback"], "clickable_link")
        self.assertEqual(presentation["preview"]["variant"], "thumbnail")
        self.assertEqual(presentation["preview"]["mime_type"], "image/webp")
        self.assertEqual(presentation["preview"]["width"], 768)
        self.assertEqual(presentation["preview"]["height"], 576)
        self.assertEqual(len(presentation["completion_criteria"]), 3)

    def test_generation_result_preview_falls_back_to_original_for_invalid_image(self):
        output_dir = os.path.join(self.directory.name, "outputs")
        os.makedirs(output_dir, exist_ok=True)
        Path(output_dir, "result.png").write_bytes(b"test-image-bytes")
        structured = {
            "job_id": "b" * 32,
            "status": "complete",
            "ready": True,
            "result": {
                "image_path": "/outputs/result.png",
                "image_url": "http://10.100.90.242:8000/outputs/result.png",
            },
        }
        with mock.patch.dict(SERVER_CONFIG, {"output_dir": output_dir}):
            result = _generation_result_tool_result(structured)

        self.assertEqual(result.content[0].type, "image")
        self.assertEqual(result.content[0].mime_type, "image/png")
        response = result.model_dump(by_alias=True)["structuredContent"]
        self.assertEqual(response["presentation"]["preview"]["variant"], "original_fallback")

    def test_tool_contract_marks_read_write_and_open_world_boundaries(self):
        integration = create_mcp_integration(self.manager, self.store, self.controls, self.asset_service)
        tools = asyncio.run(integration.server.list_tools())
        by_name = {tool.name: tool for tool in tools}
        self.assertEqual(set(by_name), {
            "list_generation_capabilities",
            "get_generation_capability",
            "plan_generation",
            "get_generation_job",
            "get_generation_result",
            "create_managed_image_asset",
            "list_image_assets",
            "get_image_asset",
            "prepare_input_image_upload",
            "create_game_ui_assets",
            "create_character_sheet",
            "create_storyboard",
            "remove_background",
        })
        self.assertNotIn("create_image", by_name)
        self.assertFalse(by_name["create_managed_image_asset"].annotations.read_only_hint)
        self.assertTrue(by_name["create_managed_image_asset"].annotations.open_world_hint)
        self.assertTrue(by_name["get_generation_job"].annotations.read_only_hint)
        self.assertIn("required completion step", by_name["get_generation_result"].description)
        self.assertIn("Claude Code", by_name["get_generation_result"].description)
        self.assertTrue(by_name["plan_generation"].annotations.read_only_hint)
        self.assertFalse(by_name["plan_generation"].annotations.idempotent_hint)
        self.assertTrue(by_name["list_image_assets"].annotations.read_only_hint)
        self.assertTrue(by_name["get_image_asset"].annotations.read_only_hint)
        self.assertTrue(by_name["prepare_input_image_upload"].annotations.read_only_hint)
        self.assertIn("never convert it to base64", by_name["prepare_input_image_upload"].description)
        self.assertFalse(by_name["create_game_ui_assets"].annotations.read_only_hint)
        self.assertFalse(by_name["create_character_sheet"].annotations.read_only_hint)
        self.assertFalse(by_name["create_storyboard"].annotations.read_only_hint)
        self.assertFalse(by_name["remove_background"].annotations.read_only_hint)
        self.assertFalse(by_name["remove_background"].annotations.open_world_hint)
        self.assertIn("image_id", by_name["remove_background"].input_schema["required"])
        self.assertIn("reference_image_id", by_name["create_character_sheet"].input_schema["required"])
        self.assertIn("reference_image_id", by_name["create_storyboard"].input_schema["required"])
        create_schema = by_name["create_managed_image_asset"].input_schema
        self.assertIn("idempotency_key", create_schema["required"])
        self.assertIn("plan_id", create_schema["required"])
        self.assertIn("image_model", create_schema["required"])
        self.assertIn("aspect_ratio", create_schema["required"])
        self.assertIn("image_size", create_schema["required"])
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
                "0.8.0",
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
            self.assertIn("prepare_input_image_upload", names)
            self.assertNotIn("create_input_image_asset", names)
            self.assertIn("create_game_ui_assets", names)
            self.assertIn("create_character_sheet", names)
            self.assertIn("create_storyboard", names)
            self.assertIn("remove_background", names)
            self.assertIn("plan_generation", names)
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
                {
                    "create_managed_image_asset",
                    "create_game_ui_assets",
                    "create_character_sheet",
                    "create_storyboard",
                    "remove_background",
                },
            )

            unplanned = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 31,
                    "method": "tools/call",
                    "params": {
                        "name": "create_managed_image_asset",
                        "arguments": {
                            "prompt": "A minimal red gem icon",
                            "image_model": "google/gemini-3.1-flash-lite-image",
                            "aspect_ratio": "square",
                            "image_size": "1K",
                            "idempotency_key": "unplanned-protocol-gem",
                        },
                    },
                },
            )
            self.assertTrue(unplanned.json()["result"]["isError"])

            planned = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "plan_generation",
                        "arguments": {
                            "capability": "create_managed_image_asset",
                            "prompt": "A minimal red gem icon",
                            "options": {
                                "image_model": "google/gemini-3.1-flash-lite-image",
                                "aspect_ratio": "square",
                                "image_size": "1K",
                            },
                        },
                    },
                },
            )
            planned_result = planned.json()["result"]["structuredContent"]
            self.assertTrue(planned_result["ready_to_generate"])
            called = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {
                        "name": "create_managed_image_asset",
                        "arguments": {
                            **planned_result["tool_arguments"],
                            "plan_id": planned_result["plan_id"],
                            "idempotency_key": planned_result["suggested_idempotency_key"],
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

            upload_contract_response = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": "prepare_input_image_upload", "arguments": {}},
                },
            )
            upload_contract = upload_contract_response.json()["result"]["structuredContent"]
            self.assertFalse(upload_contract["base64_allowed"])
            self.assertTrue(upload_contract["upload_url"].endswith("/api/v1/mcp/inputs/upload"))

            character_plan_response = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {
                        "name": "plan_generation",
                        "arguments": {
                            "capability": "create_character_sheet",
                            "reference_image_ids": ["protocol-owned"],
                            "options": {
                                "sheet_type": "turnaround",
                                "count": 3,
                                "image_size": "1K",
                                "image_quality": "low",
                            },
                        },
                    },
                },
            )
            character_plan = character_plan_response.json()["result"]["structuredContent"]
            character_sheet = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "tools/call",
                    "params": {
                        "name": "create_character_sheet",
                        "arguments": {
                            **character_plan["tool_arguments"],
                            "plan_id": character_plan["plan_id"],
                            "idempotency_key": character_plan["suggested_idempotency_key"],
                        },
                    },
                },
            )
            character_structured = character_sheet.json()["result"]["structuredContent"]
            self.assertEqual(character_structured["output_contract"]["count"], 3)

            storyboard_plan_response = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 11,
                    "method": "tools/call",
                    "params": {
                        "name": "plan_generation",
                        "arguments": {
                            "capability": "create_storyboard",
                            "reference_image_ids": ["protocol-owned"],
                            "prompt": "A hero discovers a glowing gate and steps through it.",
                            "options": {
                                "cuts": 6,
                                "image_size": "1K",
                                "image_quality": "low",
                            },
                        },
                    },
                },
            )
            storyboard_plan = storyboard_plan_response.json()["result"]["structuredContent"]
            storyboard = client.post(
                "/",
                headers=protocol_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 12,
                    "method": "tools/call",
                    "params": {
                        "name": "create_storyboard",
                        "arguments": {
                            **storyboard_plan["tool_arguments"],
                            "plan_id": storyboard_plan["plan_id"],
                            "idempotency_key": storyboard_plan["suggested_idempotency_key"],
                        },
                    },
                },
            )
            storyboard_structured = storyboard.json()["result"]["structuredContent"]
            self.assertEqual(storyboard_structured["output_contract"]["grid"], "2x3")

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
