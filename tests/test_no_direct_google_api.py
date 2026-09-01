import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _deployment_files():
    roots = (
        PROJECT_ROOT / "app",
        PROJECT_ROOT / "llm",
        PROJECT_ROOT / "scripts",
        PROJECT_ROOT / "static",
        PROJECT_ROOT / "templates",
        PROJECT_ROOT / "workflows",
        PROJECT_ROOT / ".claude",
    )
    allowed_suffixes = {".bat", ".html", ".js", ".json", ".ps1", ".py"}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in allowed_suffixes:
                yield path
    for name in (".env", ".env.example", "requirements.txt", "run.py"):
        path = PROJECT_ROOT / name
        if path.is_file():
            yield path


class DirectGoogleApiBoundaryTests(unittest.TestCase):
    def test_deployment_surfaces_do_not_contain_direct_google_api_access(self):
        # Build the most sensitive tokens in pieces so this guard does not
        # accidentally become a secret-scanner finding itself.
        forbidden = {
            "Google Generative Language endpoint": re.compile(
                re.escape("generativelanguage" + ".googleapis.com"), re.IGNORECASE
            ),
            "Google Vertex AI endpoint": re.compile(
                re.escape("aiplatform" + ".googleapis.com"), re.IGNORECASE
            ),
            "Google API key-shaped token": re.compile("AI" + r"za[0-9A-Za-z_-]{20,}"),
            "Google AI Studio credential": re.compile("GOOGLE_AI_STUDIO" + "_API_KEY"),
            "Google API credential": re.compile("GOOGLE" + "_API_KEY"),
            "Gemini API credential": re.compile("GEMINI" + "_API_KEY"),
            "Vertex API credential": re.compile("VERTEX" + "_API_KEY"),
            "Google provider workflow": re.compile(
                r"[\"']provider[\"']\s*:\s*[\"']google[\"']", re.IGNORECASE
            ),
        }

        violations = []
        for path in sorted(set(_deployment_files())):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for label, pattern in forbidden.items():
                if pattern.search(text):
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}: {label}")

        self.assertEqual(
            violations,
            [],
            "Direct Google API access must not re-enter the deployment; use OpenRouter instead:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
