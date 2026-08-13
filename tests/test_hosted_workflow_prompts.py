import asyncio
import unittest

from app.routers.workflows import get_workflows
from app.workflow_configs import WORKFLOW_CONFIGS


class HostedWorkflowPromptTests(unittest.TestCase):
    def test_non_prompt_utility_keeps_empty_style_prompt(self):
        self.assertEqual(WORKFLOW_CONFIGS["RMBG2"]["style_prompt"], "")

    def test_basic_generation_and_editing_have_distinct_roles(self):
        generate = WORKFLOW_CONFIGS["NanoBanana"]
        edit = WORKFLOW_CONFIGS["NanoBanana_Img2Img"]

        self.assertEqual(generate["openrouter"]["mode"], "text-to-image")
        self.assertIn("Create one finished image", generate["style_prompt"])
        self.assertNotIn("Change only what the user requests", generate["style_prompt"])

        self.assertEqual(edit["openrouter"]["mode"], "image-edit")
        self.assertIn("Change only what the user requests", edit["style_prompt"])
        self.assertIn("Treat Image 1 as the base image", edit["style_prompt"])

    def test_turnaround_prompt_defers_to_selected_view_specification(self):
        prompt = WORKFLOW_CONFIGS["NanoBanana_TurnaroundSheet"]["style_prompt"]
        self.assertIn("exact view count", prompt)
        self.assertIn("full body visible", prompt)
        self.assertNotIn("front, 3/4 front, side, back", prompt)

    def test_expression_prompt_requires_exact_grid_population(self):
        prompt = WORKFLOW_CONFIGS["NanoBanana_ExpressionPortraitSheet"]["style_prompt"]
        self.assertIn("exact portrait count", prompt)
        self.assertIn("each requested expression exactly once", prompt)

    def test_general_editing_exposes_relighting_prompt_examples(self):
        templates = WORKFLOW_CONFIGS["NanoBanana_Img2Img"]["ui"]["promptTemplates"]
        prompts = "\n".join(item["text"] for item in templates)
        self.assertIn("조명", prompts)
        self.assertIn("구도", prompts)
        self.assertIn("그대로", prompts)

    def test_storyboard_prompt_requires_order_and_continuity(self):
        prompt = WORKFLOW_CONFIGS["NanoBanana_StoryboardCutboard"]["style_prompt"]
        self.assertIn("left to right, then top to bottom", prompt)
        self.assertIn("exactly the requested number of panels", prompt)
        self.assertIn("spatial relationships", prompt)

    def test_gpt_image_2_recommendation_is_scoped_to_specialized_workflows(self):
        recommended = {
            workflow_id
            for workflow_id, config in WORKFLOW_CONFIGS.items()
            if (config.get("ui") or {}).get("hostedModelRecommendation")
        }
        self.assertEqual(
            recommended,
            {
                "NanoBanana_StoryboardCutboard",
                "NanoBanana_ChainsawJuiceKingCharacter",
            },
        )
        for workflow_id in recommended:
            recommendation = WORKFLOW_CONFIGS[workflow_id]["ui"]["hostedModelRecommendation"]
            self.assertIn("GPT Image 2", recommendation["title"])
            self.assertIn("권장", recommendation["message"])

    def test_chainsaw_workflow_is_gpt_image_2_only_and_defaults_to_high(self):
        config = WORKFLOW_CONFIGS["NanoBanana_ChainsawJuiceKingCharacter"]
        self.assertEqual(config["openrouter"]["model"], "openai/gpt-image-2")
        self.assertEqual(config["openrouter"]["allowed_models"], ["openai/gpt-image-2"])
        self.assertEqual(config["openrouter"]["default_quality"], "high")
        self.assertNotIn("allowed_models", WORKFLOW_CONFIGS["NanoBanana"]["openrouter"])

        response = asyncio.run(get_workflows(include_openrouter=True, include_google=None))
        workflow = next(item for item in response["workflows"] if item["id"] == "NanoBanana_ChainsawJuiceKingCharacter")
        hosted = workflow["ui"]["hostedImageGeneration"]
        self.assertTrue(hosted["model_locked"])
        self.assertEqual([item["id"] for item in hosted["models"]], ["openai/gpt-image-2"])
        self.assertEqual(hosted["models"][0]["resolutions"], ["1K", "2K"])
        self.assertEqual(hosted["models"][0]["default_quality"], "high")

        basic = next(item for item in response["workflows"] if item["id"] == "NanoBanana")
        self.assertFalse(basic["ui"]["hostedImageGeneration"]["model_locked"])
        self.assertGreater(len(basic["ui"]["hostedImageGeneration"]["models"]), 1)


if __name__ == "__main__":
    unittest.main()
