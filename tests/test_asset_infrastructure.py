import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from app.asset_store import AssetStore
from app.asset_admin import (
    _backup_all,
    _catalog_canary,
    _prune_backups,
    _restore_drill,
    _verify_backup,
)
from app.auth.user_management import (
    _principal_from_signed_cookie,
    _signed_cookie_value,
    prepare_request_principal,
    require_principal_id,
    validate_principal_id,
)
from app.services.asset_service import AssetService, atomic_write_json
from app.services import asset_runtime, media_store
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

    def test_principal_preparation_marks_legacy_upgrade_for_observation(self):
        request = SimpleNamespace(
            cookies={"anon_id": "anon-existing_user"},
            state=SimpleNamespace(),
        )
        with mock.patch.dict(os.environ, {"PRINCIPAL_IDENTITY_MODE": "compat"}, clear=False):
            principal_id, needs_upgrade = prepare_request_principal(request)
        self.assertEqual(principal_id, "anon-existing_user")
        self.assertTrue(needs_upgrade)
        self.assertEqual(request.state.principal_identity_source, "legacy_cookie")

    def test_enforced_mode_rejects_and_marks_legacy_cookie(self):
        request = SimpleNamespace(
            cookies={"anon_id": "anon-existing_user"},
            state=SimpleNamespace(),
        )
        with mock.patch.dict(os.environ, {"PRINCIPAL_IDENTITY_MODE": "enforced"}, clear=False):
            principal_id, needs_upgrade = prepare_request_principal(request)
        self.assertNotEqual(principal_id, "anon-existing_user")
        self.assertTrue(principal_id.startswith("anon-"))
        self.assertTrue(needs_upgrade)
        self.assertEqual(request.state.principal_identity_source, "legacy_cookie_rejected")


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


class CompleteBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output_root = self.root / "outputs"
        self.output_root.mkdir()
        self.db_path = self.root / "app_data.db"
        self.secret_path = self.root / "principal_cookie.secret"
        self.secret_path.write_bytes(b"s" * 48)
        self.service = AssetService(AssetStore(str(self.db_path)), str(self.output_root))

        media_dir = self.output_root / "users" / "anon-owner" / "2026" / "08" / "13"
        media_dir.mkdir(parents=True)
        media = media_dir / "asset123.png"
        metadata_path = media_dir / "asset123.json"
        media.write_bytes(b"asset-bytes")
        metadata = {
            "id": "asset123",
            "owner": "anon-owner",
            "kind": "image",
            "mime": "image/png",
            "bytes": len(b"asset-bytes"),
            "sha256": "abc",
            "created_at": "2026-08-13T00:00:00+00:00",
            "status": "active",
            "thumb": None,
        }
        atomic_write_json(metadata_path, metadata)
        self.service.register(
            owner_id="anon-owner",
            kind="image",
            media_path=str(media),
            metadata_path=str(metadata_path),
            metadata=metadata,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_backup_contains_and_verifies_all_recovery_parts(self):
        result = _backup_all(
            self.root / "backups",
            database_path=self.db_path,
            output_root=self.output_root,
            principal_secret_path=self.secret_path,
        )

        bundle = Path(result["backup"])
        self.assertTrue((bundle / "app_data.db").is_file())
        self.assertTrue((bundle / "outputs" / "users" / "anon-owner" / "2026" / "08" / "13" / "asset123.png").is_file())
        self.assertEqual((bundle / "principal_cookie.secret").read_bytes(), b"s" * 48)
        verified = _verify_backup(bundle)
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["catalog"]["missing_files"], 0)

    def test_complete_backup_verification_detects_tampering(self):
        result = _backup_all(
            self.root / "backups",
            database_path=self.db_path,
            output_root=self.output_root,
            principal_secret_path=self.secret_path,
        )
        bundle = Path(result["backup"])
        (bundle / "outputs" / "users" / "anon-owner" / "2026" / "08" / "13" / "asset123.png").write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch|size mismatch"):
            _verify_backup(bundle)

    def test_complete_backup_rejects_destination_inside_outputs(self):
        with self.assertRaisesRegex(ValueError, "inside the outputs"):
            _backup_all(
                self.output_root / "backups",
                database_path=self.db_path,
                output_root=self.output_root,
                principal_secret_path=self.secret_path,
            )

    def test_restore_drill_uses_isolated_copy_and_restored_secret(self):
        result = _backup_all(
            self.root / "backups",
            database_path=self.db_path,
            output_root=self.output_root,
            principal_secret_path=self.secret_path,
        )

        drill = _restore_drill(result["backup"])

        self.assertTrue(drill["ok"])
        self.assertTrue(drill["principal_cookie_roundtrip"])
        self.assertTrue(drill["staging_removed"])
        self.assertEqual(drill["catalog"]["missing_files"], 0)

    def test_backup_retention_only_removes_recognized_expired_bundles(self):
        backup_root = self.root / "backups"
        now = datetime(2026, 8, 13, tzinfo=timezone.utc)
        bundles = []
        for age_days in (60, 45, 1):
            result = _backup_all(
                backup_root,
                database_path=self.db_path,
                output_root=self.output_root,
                principal_secret_path=self.secret_path,
            )
            bundle = Path(result["backup"])
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["created_at"] = (now - timedelta(days=age_days)).isoformat()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            bundles.append(bundle)
        unknown = backup_root / "lc-ai-canvas-unknown"
        unknown.mkdir()

        preview = _prune_backups(
            backup_root,
            retention_days=30,
            minimum_bundles=1,
            now=now,
        )
        self.assertEqual(len(preview["expired"]), 2)
        self.assertEqual(preview["deleted"], [])
        applied = _prune_backups(
            backup_root,
            retention_days=30,
            minimum_bundles=1,
            apply=True,
            now=now,
        )
        self.assertEqual(len(applied["deleted"]), 2)
        self.assertTrue(bundles[2].is_dir())
        self.assertTrue(unknown.is_dir())


class CatalogFallbackTests(unittest.TestCase):
    def test_filesystem_fallback_can_be_disabled_for_catalog_only_canary(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            asset_runtime, "_asset_service", None
        ), mock.patch.object(media_store, "OUTPUT_DIR", directory), mock.patch.dict(
            os.environ, {"ASSET_CATALOG_FALLBACK_ENABLED": "false"}, clear=False
        ):
            with self.assertRaisesRegex(RuntimeError, "AssetService is required"):
                media_store._gather_user_images("anon-owner")

    def test_catalog_canary_checks_inventory_parity_and_fail_closed_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = root / "outputs"
            media_dir = outputs / "users" / "anon-owner" / "2026" / "08" / "13"
            media_dir.mkdir(parents=True)
            media = media_dir / "asset123.png"
            metadata_path = media_dir / "asset123.json"
            media.write_bytes(b"asset-bytes")
            metadata = {
                "id": "asset123",
                "owner": "anon-owner",
                "kind": "image",
                "mime": "image/png",
                "bytes": len(b"asset-bytes"),
                "sha256": "abc",
                "created_at": "2026-08-13T00:00:00+00:00",
                "status": "active",
                "thumb": None,
            }
            atomic_write_json(metadata_path, metadata)
            store = AssetStore(str(root / "app_data.db"))
            service = AssetService(store, str(outputs))
            service.register(
                owner_id="anon-owner",
                kind="image",
                media_path=str(media),
                metadata_path=str(metadata_path),
                metadata=metadata,
            )
            store.mark_migration("asset_backfill", 1)

            result = _catalog_canary(database_path=store.db_path, output_root=outputs)

        self.assertTrue(result["ok"])
        self.assertTrue(result["catalog_only_fail_closed"])
        self.assertEqual(result["parity"]["asset_rows"], 1)
        self.assertEqual(result["parity"]["filesystem_assets"], 1)


if __name__ == "__main__":
    unittest.main()
