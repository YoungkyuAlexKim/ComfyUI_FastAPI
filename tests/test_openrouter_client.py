import base64
import os
import unittest
from unittest.mock import Mock, patch

from app.services import openrouter_client


class OpenRouterClientTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_BASE_URL": "https://example.test/api/v1",
                "OPENROUTER_ZDR": "true",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()

    @patch("app.services.openrouter_client.requests.post")
    def test_image_generation_payload_and_response(self, post):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "data": [{"b64_json": base64.b64encode(b"png-bytes").decode("ascii")}]
        }
        post.return_value = response

        result = openrouter_client.generate_image(
            model="google/gemini-3-pro-image",
            prompt="draw a fox",
            images=[b"reference"],
            aspect_ratio="16:9",
            resolution="2K",
        )

        self.assertEqual(result, b"png-bytes")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["json"]["model"], "google/gemini-3-pro-image")
        self.assertEqual(kwargs["json"]["aspect_ratio"], "16:9")
        self.assertEqual(kwargs["json"]["resolution"], "2K")
        reference = kwargs["json"]["input_references"][0]
        self.assertEqual(reference["type"], "image_url")
        self.assertTrue(reference["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(kwargs["json"]["provider"]["data_collection"], "deny")
        self.assertTrue(kwargs["json"]["provider"]["zdr"])
        self.assertNotIn("test-key", str(kwargs["json"]))

    @patch("app.services.openrouter_client.requests.post")
    def test_text_generation_parses_chat_completion(self, post):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": " translated text "}}]}
        post.return_value = response

        result = openrouter_client.generate_text(prompt="translate", max_tokens=42)

        self.assertEqual(result, "translated text")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "google/gemini-3.1-flash-lite")
        self.assertEqual(payload["max_tokens"], 42)
        self.assertEqual(payload["messages"][0]["content"], "translate")

    @patch("app.services.openrouter_client.requests.post")
    def test_credit_error_is_classified(self, post):
        response = Mock(ok=False, status_code=402, headers={})
        response.json.return_value = {"error": {"code": 402, "message": "Insufficient credits"}}
        post.return_value = response

        with self.assertRaises(openrouter_client.OpenRouterUpstreamError) as caught:
            openrouter_client.generate_text(prompt="hello")

        self.assertEqual(caught.exception.kind, "openrouter_credits_exhausted")
        self.assertEqual(caught.exception.http_status, 402)

    @patch("app.services.openrouter_client.requests.post")
    def test_data_url_image_response_is_supported(self, post):
        encoded = base64.b64encode(b"png").decode("ascii")
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"data": [{"b64_json": f"data:image/png;base64,{encoded}"}]}
        post.return_value = response

        self.assertEqual(
            openrouter_client.generate_image(model="google/gemini-3-pro-image", prompt="test"),
            b"png",
        )


if __name__ == "__main__":
    unittest.main()
