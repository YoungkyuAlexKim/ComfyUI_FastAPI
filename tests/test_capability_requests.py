import unittest

from pydantic import TypeAdapter, ValidationError

from app.schemas.capability_requests import (
    CapabilityRequest,
    CreateCharacterSheetRequest,
    CreateGameUiAssetsRequest,
    CreateImageRequest,
    MCP_CAPABILITY_REQUEST_MODELS,
)
from app.workflow_configs import WORKFLOW_CONFIGS
from app.services.generation_planning import PUBLIC_GENERATION_CAPABILITIES


class CapabilityRequestTests(unittest.TestCase):
    def test_public_workflows_map_to_declared_mcp_capabilities(self):
        public_capabilities = {
            config["capability"]
            for config in WORKFLOW_CONFIGS.values()
            if config.get("mcp_public")
        }
        public_contracts = {
            "create_managed_image_asset" if capability == "create_image" else capability
            for capability in public_capabilities
        }
        self.assertEqual(public_contracts, set(PUBLIC_GENERATION_CAPABILITIES))
        self.assertTrue(public_capabilities <= set(MCP_CAPABILITY_REQUEST_MODELS))
        self.assertFalse(WORKFLOW_CONFIGS["AceStep15XL"]["mcp_public"])
        self.assertFalse(WORKFLOW_CONFIGS["seethrough-basic"]["mcp_public"])

    def test_game_ui_belongs_to_image_generation(self):
        config = WORKFLOW_CONFIGS["GameUI_Elements"]
        self.assertEqual(config["category"], "image_generation")
        self.assertEqual(config["capability"], "create_game_ui_assets")

    def test_relight_is_not_a_standalone_workflow(self):
        self.assertNotIn("NanoBanana_Relight", WORKFLOW_CONFIGS)

    def test_image_edit_requires_a_reference(self):
        with self.assertRaises(ValidationError):
            CreateImageRequest(
                idempotency_key="request-123",
                operation="edit",
                prompt="조명만 바꿔줘",
            )

    def test_character_sheet_count_depends_on_sheet_type(self):
        with self.assertRaises(ValidationError):
            CreateCharacterSheetRequest(
                idempotency_key="request-123",
                sheet_type="expressions",
                reference_image_id="image-1",
                count=5,
            )

    def test_discriminated_request_parses_game_ui(self):
        request = TypeAdapter(CapabilityRequest).validate_python(
            {
                "capability": "create_game_ui_assets",
                "idempotency_key": "request-123",
                "prompt": "얼음 마법 스킬 아이콘",
            }
        )
        self.assertIsInstance(request, CreateGameUiAssetsRequest)
        self.assertEqual(request.grid, "2x2")

    def test_mcp_game_ui_contract_rejects_web_only_grids(self):
        with self.assertRaises(ValidationError):
            CreateGameUiAssetsRequest(
                idempotency_key="request-123",
                prompt="얼음 마법 스킬 아이콘",
                grid="3x3",
            )


if __name__ == "__main__":
    unittest.main()
