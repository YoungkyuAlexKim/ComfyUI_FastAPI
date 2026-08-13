import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from app.asset_store import AssetStore
from app.auth.user_management import (
    _principal_from_signed_cookie,
    _signed_cookie_value,
    require_principal_id,
    validate_principal_id,
)
from app.services.asset_service import AssetService, atomic_write_json
from app.routers.admin import require_admin
from fastapi import HTTPException


class PrincipalBoundaryTests(unittest.TestCase):
    def test_principal_validation_rejects_path_components(self):
        self.assertIsNone(validate_principal_id("anon-/../../../outside"))
        self.assertIsNone(validate_principal_id("anon-\\..\\outside"))
        self.assertIsNone(validate_principal_id("anon-user.name"))
        self.assertEqual(validate_principal_id("anon-user_123"), "anon-user_123")
        with self.assertRaises(ValueError):
            require_principal_id("anon-/outside")

    def test_signed_principal_cookie_rejects_tampering(self):
        with mock.patch.dict(os.environ, {"PRINCIPAL_COOKIE_SECRET": "test-secret-value"}, clear=False):
            token = _signed_cookie_value("anon-user_123")
            self.assertEqual(_principal_from_signed_cookie(token), "anon-user_123")
            self.assertIsNone(_principal_from_signed_cookie(token[:-1] + ("A" if token[-1] != "A" else "B")))


class AdminBoundaryTests(unittest.TestCase):
    def test_missing_admin_configuration_fails_closed(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPException) as caught:
                require_admin(None)
            self.assertEqual(caught.exception.status_code, 503)

    def test_unsafe_admin_bypass_requires_explicit_opt_in(self):
        with mock.patch.dict(os.environ, {"ADMIN_ALLOW_UNAUTHENTICATED": "true"}, clear=True):
            self.assertTrue(require_admin(None))


class AssetServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.output_root = root / "outputs"
        self.output_root.mkdir()
        self.store = AssetStore(str(root / "catalog.db"))
        self.service = AssetService(self.store, str(self.output_root))

    def tearDown(self):
        self.temp.cleanup()

    def _legacy_asset(self, owner="anon-owner", asset_id="asset123", kind="image"):
        base = self.output_root / "users" / owner
        if kind == "input":
            base = base / "inputs"
        elif kind == "audio":
            base = base / "audio"
        base = base / "2026" / "08" / "13"
        base.mkdir(parents=True, exist_ok=True)
        extension = ".mp3" if kind == "audio" else ".png"
        media = base / f"{asset_id}{extension}"
        media.write_bytes(b"asset-bytes")
        meta = {
            "id": asset_id,
            "owner": owner,
            "kind": kind,
            "mime": "audio/mpeg" if kind == "audio" else "image/png",
            "bytes": len(b"asset-bytes"),
            "sha256": "abc",
            "created_at": "2026-08-13T00:00:00+00:00",
            "status": "active",
            "thumb": None,
        }
        meta_path = base / f"{asset_id}.json"
        atomic_write_json(meta_path, meta)
        return media, meta_path, meta

    def test_backfill_indexes_files_without_moving_them(self):
        media, _, _ = self._legacy_asset()
        before = media.resolve()
        summary = self.service.backfill_legacy()
        self.assertEqual(summary["registered"], 1)
        self.assertEqual(media.resolve(), before)
        item = self.service.get("anon-owner", "asset123")
        self.assertIsNotNone(item)
        self.assertEqual(item["storage_path"], "users/anon-owner/2026/08/13/asset123.png")

    def test_backfill_registers_game_ui_group_as_first_class_record(self):
        group_id = "group123"
        group_dir = self.output_root / "users" / "anon-owner" / "2026" / "08" / "13" / "game_ui_groups" / group_id
        group_dir.mkdir(parents=True)
        sheet = group_dir / "source_sheet.png"
        archive = group_dir / f"game_ui_{group_id}.zip"
        manifest = group_dir / "manifest.json"
        sheet.write_bytes(b"sheet")
        archive.write_bytes(b"zip")
        atomic_write_json(
            manifest,
            {
                "id": group_id,
                "kind": "game_ui_group",
                "status": "active",
                "created_at": "2026-08-13T00:00:00+00:00",
                "sheet_url": f"/outputs/{sheet.relative_to(self.output_root).as_posix()}",
                "download_url": f"/outputs/{archive.relative_to(self.output_root).as_posix()}",
                "items": [],
            },
        )
        summary = self.service.backfill_legacy()
        self.assertEqual(summary["groups_registered"], 1)
        self.assertEqual(self.store.group_stats(), {"game_ui_group:active": 1})
        self.assertEqual(self.service.audit()["missing_group_files"], 0)

    def test_owner_isolation_and_status_updates(self):
        media, meta_path, meta = self._legacy_asset()
        self.service.register(
            owner_id="anon-owner",
            kind="image",
            media_path=str(media),
            metadata_path=str(meta_path),
            metadata=meta,
        )
        self.assertIsNone(self.service.get("anon-other", "asset123"))
        self.assertFalse(self.service.update_status("anon-other", "asset123", "trash"))
        self.assertTrue(self.service.update_status("anon-owner", "asset123", "trash"))
        stored_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(stored_meta["status"], "trash")
        self.assertEqual(self.service.get("anon-owner", "asset123")["status"], "trash")

    def test_asset_id_collision_cannot_transfer_ownership(self):
        media, meta_path, meta = self._legacy_asset()
        self.service.register(
            owner_id="anon-owner",
            kind="image",
            media_path=str(media),
            metadata_path=str(meta_path),
            metadata=meta,
        )
        other_media, other_meta_path, other_meta = self._legacy_asset(owner="anon-other")
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.register(
                owner_id="anon-other",
                kind="image",
                media_path=str(other_media),
                metadata_path=str(other_meta_path),
                metadata=other_meta,
            )
        self.assertEqual(self.store.get("asset123")["owner_id"], "anon-owner")

    def test_catalog_paths_cannot_escape_output_root(self):
        outside = Path(self.temp.name) / "outside.png"
        outside.write_bytes(b"x")
        with self.assertRaises(ValueError):
            self.service.register(
                owner_id="anon-owner",
                kind="image",
                media_path=str(outside),
                metadata_path=None,
                metadata={"id": "asset123", "status": "active"},
            )

    def test_purge_removes_only_trashed_owned_asset(self):
        media, meta_path, meta = self._legacy_asset()
        self.service.register(
            owner_id="anon-owner",
            kind="image",
            media_path=str(media),
            metadata_path=str(meta_path),
            metadata=meta,
        )
        self.service.update_status("anon-owner", "asset123", "trash")
        self.assertEqual(self.service.purge_trash_for_owner("anon-other"), 0)
        self.assertEqual(self.service.purge_trash_for_owner("anon-owner"), 1)
        self.assertFalse(media.exists())
        self.assertFalse(meta_path.exists())
        self.assertIsNone(self.service.get("anon-owner", "asset123"))


if __name__ == "__main__":
    unittest.main()
