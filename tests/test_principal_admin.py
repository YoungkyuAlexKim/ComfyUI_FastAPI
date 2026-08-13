import json
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app.principal_admin import principal_readiness


class PrincipalReadinessTests(unittest.TestCase):
    def _write_log(self, root: Path, records: list[dict]) -> None:
        (root / "app.log").write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )

    def test_readiness_requires_verified_backup_after_quiet_observation(self):
        now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {
                "PRINCIPAL_COOKIE_SECRET": "s" * 48,
                "PRINCIPAL_IDENTITY_MODE": "compat",
                "ALLOW_LEGACY_ANON_HEADER": "false",
            },
            clear=False,
        ):
            root = Path(directory)
            self._write_log(
                root,
                [
                    {"ts": (now - timedelta(days=15)).isoformat(), "event": "startup"},
                    {
                        "ts": (now - timedelta(days=8)).isoformat(),
                        "event": "principal_identity_cookie_issued",
                        "identity_source": "legacy_cookie",
                    },
                    {"ts": now.isoformat(), "event": "health"},
                ],
            )
            result = principal_readiness(log_dir=root, now=now)

        self.assertTrue(result["technical_ready"])
        self.assertFalse(result["ready_for_enforced"])
        self.assertEqual(result["blockers"], ["verified_complete_backup_required"])

    def test_readiness_blocks_recent_legacy_cookie_upgrade(self):
        now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {
                "PRINCIPAL_COOKIE_SECRET": "s" * 48,
                "PRINCIPAL_IDENTITY_MODE": "compat",
                "ALLOW_LEGACY_ANON_HEADER": "false",
            },
            clear=False,
        ):
            root = Path(directory)
            self._write_log(
                root,
                [
                    {"ts": (now - timedelta(days=20)).isoformat(), "event": "startup"},
                    {
                        "ts": (now - timedelta(hours=2)).isoformat(),
                        "event": "principal_identity_cookie_issued",
                        "identity_source": "legacy_cookie",
                    },
                ],
            )
            result = principal_readiness(log_dir=root, now=now)

        self.assertIn("recent_legacy_cookie_upgrade", result["blockers"])
        self.assertFalse(result["ready_for_enforced"])


if __name__ == "__main__":
    unittest.main()
