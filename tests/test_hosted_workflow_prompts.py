import unittest

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

    def test_relight_prompt_preserves_content_and_existing_text(self):
        prompt = WORKFLOW_CONFIGS["NanoBanana_Relight"]["style_prompt"]
        self.assertIn("CHANGE ONLY", prompt)
        self.assertIn("Preserve existing text and logos", prompt)
        self.assertIn("original framing and aspect ratio", prompt)

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


if __name__ == "__main__":
    unittest.main()
