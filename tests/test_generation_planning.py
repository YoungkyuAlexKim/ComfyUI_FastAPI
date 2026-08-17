import unittest

from app.services.generation_planning import (
    EphemeralGenerationPlanStore,
    HostedGenerationPlanner,
    generation_capability_contract,
    hosted_capability_contract,
)


class HostedGenerationPlannerTests(unittest.TestCase):
    def setUp(self):
        self.planner = HostedGenerationPlanner()

    def test_ambiguous_general_image_lists_decisions_without_a_write_plan(self):
        result = self.planner.plan(
            "create_managed_image_asset",
            prompt="A fantasy character",
            options={},
            selection_mode="clarify",
        )
        self.assertFalse(result["ready_to_generate"])
        self.assertEqual(
            result["missing_decisions"],
            ["image_model", "aspect_ratio", "image_size"],
        )
        self.assertEqual(
            {question["field"] for question in result["questions"]},
            {"image_model", "aspect_ratio", "image_size"},
        )
        self.assertEqual(result["conditional_questions"][0]["field"], "image_quality")
        self.assertEqual(
            result["conditional_questions"][0]["required_when"],
            {"image_model": "openai/gpt-image-2"},
        )

    def test_each_specialized_workflow_reports_its_own_ambiguous_options(self):
        cases = {
            "create_game_ui_assets": (
                "Four matching icons",
                ["background_mode", "image_quality"],
            ),
            "create_character_sheet": (
                "",
                ["sheet_type", "count", "image_size", "image_quality"],
            ),
            "create_storyboard": (
                "The hero enters the ruins",
                ["cuts", "image_size", "image_quality"],
            ),
        }
        for capability, (prompt, expected) in cases.items():
            with self.subTest(capability=capability):
                result = self.planner.plan(
                    capability,
                    prompt=prompt,
                    options={},
                    selection_mode="clarify",
                )
                self.assertEqual(result["missing_decisions"], expected)
                self.assertFalse(result["ready_to_generate"])

    def test_recommend_mode_resolves_only_after_choice_delegation(self):
        result = self.planner.plan(
            "create_managed_image_asset",
            prompt="A fantasy character",
            options={},
            selection_mode="recommend",
        )
        self.assertTrue(result["ready_to_generate"])
        self.assertEqual(result["resolved_options"]["image_model"], "google/gemini-3.1-flash-image")
        self.assertEqual(result["resolved_options"]["aspect_ratio"], "square")
        self.assertEqual(result["resolved_options"]["image_size"], "1K")
        self.assertEqual(
            result["recommendations_applied"],
            ["image_model", "aspect_ratio", "image_size"],
        )

    def test_gpt_image_requires_quality_but_google_models_reject_it(self):
        gpt = self.planner.plan(
            "create_managed_image_asset",
            prompt="Edit the title precisely",
            options={
                "image_model": "openai/gpt-image-2",
                "aspect_ratio": "landscape",
                "image_size": "1K",
            },
            selection_mode="clarify",
        )
        self.assertEqual(gpt["missing_decisions"], ["image_quality"])

        with self.assertRaisesRegex(ValueError, "supported only by GPT Image 2"):
            self.planner.plan(
                "create_managed_image_asset",
                prompt="A landscape",
                options={
                    "image_model": "google/gemini-3-pro-image",
                    "aspect_ratio": "landscape",
                    "image_size": "2K",
                    "image_quality": "high",
                },
                selection_mode="clarify",
            )

    def test_model_specific_resolution_is_validated(self):
        with self.assertRaisesRegex(ValueError, "image_size must be one of: 1K"):
            self.planner.plan(
                "create_managed_image_asset",
                prompt="Cheap draft",
                options={
                    "image_model": "google/gemini-3.1-flash-lite-image",
                    "aspect_ratio": "square",
                    "image_size": "2K",
                },
                selection_mode="clarify",
            )

    def test_character_count_depends_on_selected_sheet_type(self):
        with self.assertRaisesRegex(ValueError, "count for expressions"):
            self.planner.plan(
                "create_character_sheet",
                prompt="",
                options={
                    "sheet_type": "expressions",
                    "count": 5,
                    "image_size": "1K",
                    "image_quality": "low",
                },
                selection_mode="clarify",
            )

    def test_contract_exposes_all_models_and_plan_requirement(self):
        contract = hosted_capability_contract("create_managed_image_asset")
        models = contract["inputs"]["image_model"]["choices"]
        self.assertEqual(len(models), 4)
        self.assertTrue(contract["planning"]["required_before_write"])
        self.assertTrue(any(model["value"] == "openai/gpt-image-2" for model in models))

    def test_local_rmbg_plan_has_safe_defaults_and_no_provider_cost(self):
        result = self.planner.plan(
            "remove_background",
            prompt="",
            options={},
            selection_mode="clarify",
            has_reference_images=True,
        )
        self.assertTrue(result["ready_to_generate"])
        self.assertEqual(result["resolved_options"]["model"], "RMBG-2.0")
        self.assertEqual(result["resolved_options"]["mask_blur"], 0)
        self.assertEqual(result["resolved_options"]["mask_offset"], 0)
        self.assertFalse(result["provider_cost"])

        contract = generation_capability_contract("remove_background")
        self.assertTrue(contract["local_execution"])
        self.assertEqual(contract["execution_class"], "fast")
        self.assertEqual(contract["cost"]["provider_api_cost_usd"], 0.0)

    def test_local_rmbg_processing_controls_are_validated(self):
        with self.assertRaisesRegex(ValueError, "mask_blur must be between"):
            self.planner.plan(
                "remove_background",
                prompt="",
                options={"mask_blur": 65},
                selection_mode="clarify",
                has_reference_images=True,
            )


class EphemeralGenerationPlanStoreTests(unittest.TestCase):
    def test_plan_is_owner_bound_and_arguments_cannot_drift(self):
        store = EphemeralGenerationPlanStore()
        arguments = {"prompt": "gem", "image_size": "1K"}
        issued = store.issue("owner-a", "create_managed_image_asset", arguments)
        store.validate(
            issued["plan_id"],
            principal_id="owner-a",
            capability="create_managed_image_asset",
            arguments=arguments,
        )
        with self.assertRaisesRegex(ValueError, "owner or capability"):
            store.validate(
                issued["plan_id"],
                principal_id="owner-b",
                capability="create_managed_image_asset",
                arguments=arguments,
            )
        with self.assertRaisesRegex(ValueError, "arguments changed"):
            store.validate(
                issued["plan_id"],
                principal_id="owner-a",
                capability="create_managed_image_asset",
                arguments={"prompt": "gem", "image_size": "2K"},
            )


if __name__ == "__main__":
    unittest.main()
