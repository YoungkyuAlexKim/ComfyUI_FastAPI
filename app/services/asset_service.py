"""Authoritative media asset service shared by web routes and MCP adapters."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
import uuid
from typing import Any, Optional

from ..asset_store import AssetStore
from ..auth.user_management import require_principal_id, validate_principal_id


_ASSET_ID_PATTERN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def _valid_asset_id(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 128 or value[0] not in _ASSET_ID_PATTERN_CHARS:
        return None
    return value if all(ch in _ASSET_ID_PATTERN_CHARS for ch in value) else None


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass


def atomic_write_json(path: str | Path, value: dict[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    atomic_write_bytes(path, encoded)


class AssetService:
    def __init__(self, store: AssetStore, output_root: str):
        self.store = store
        self.output_root = Path(output_root).resolve()
        self.users_root = (self.output_root / "users").resolve()
        self._status_lock = threading.RLock()

    def _relative_path(self, path: str | Path | None) -> Optional[str]:
        if path is None:
            return None
        resolved = Path(path).resolve()
        try:
            relative = resolved.relative_to(self.output_root)
        except ValueError as exc:
            raise ValueError("Asset path escaped the output root") from exc
        return relative.as_posix()

    def resolve_storage_path(self, relative_path: str | None) -> Optional[str]:
        if not relative_path:
            return None
        resolved = (self.output_root / relative_path).resolve()
        try:
            resolved.relative_to(self.output_root)
        except ValueError as exc:
            raise ValueError("Catalog path escaped the output root") from exc
        return str(resolved)

    def _path_from_output_url(self, value: object) -> Optional[str]:
        if isinstance(value, str) and value.startswith("/outputs/"):
            return self.resolve_storage_path(value[len("/outputs/") :])
        return None

    @staticmethod
    def _created_timestamp(meta: dict[str, Any], media_path: str) -> float:
        raw = meta.get("created_at")
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str) and raw.strip():
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
        return os.path.getmtime(media_path)

    def _catalog_record(
        self,
        *,
        owner_id: str,
        kind: str,
        media_path: str,
        metadata_path: str | None,
        metadata: dict[str, Any],
        source_job_id: str | None = None,
    ) -> dict[str, Any]:
        principal_id = require_principal_id(owner_id)
        asset_id = _valid_asset_id(metadata.get("id"))
        if not asset_id:
            raise ValueError("Invalid or missing asset ID")
        if kind not in {"image", "input", "audio"}:
            raise ValueError("Invalid asset kind")
        status = str(metadata.get("status") or "active")
        if status not in {"active", "trash"}:
            status = "active"
        thumb_path = None
        raw_thumb = metadata.get("thumb")
        if isinstance(raw_thumb, str) and raw_thumb.startswith("/outputs/"):
            thumb_path = self.resolve_storage_path(raw_thumb[len("/outputs/") :])
        created_at = self._created_timestamp(metadata, media_path)
        return {
            "asset_id": asset_id,
            "owner_id": principal_id,
            "kind": kind,
            "status": status,
            "storage_path": self._relative_path(media_path),
            "metadata_path": self._relative_path(metadata_path),
            "thumbnail_path": self._relative_path(thumb_path),
            "mime_type": metadata.get("mime"),
            "byte_size": metadata.get("bytes"),
            "sha256": metadata.get("sha256"),
            "group_id": metadata.get("game_ui_group_id") or metadata.get("group_id"),
            "source_job_id": source_job_id or metadata.get("source_job_id"),
            "created_at": created_at,
            "updated_at": time.time(),
            "deleted_at": time.time() if status == "trash" else None,
            "metadata": metadata,
        }

    def register(
        self,
        *,
        owner_id: str,
        kind: str,
        media_path: str,
        metadata_path: str | None,
        metadata: dict[str, Any],
        source_job_id: str | None = None,
    ) -> str:
        record = self._catalog_record(
            owner_id=owner_id,
            kind=kind,
            media_path=media_path,
            metadata_path=metadata_path,
            metadata=metadata,
            source_job_id=source_job_id,
        )
        self.store.upsert(record)
        return str(record["asset_id"])

    def register_group(
        self,
        *,
        owner_id: str,
        manifest_path: str,
        metadata: dict[str, Any],
    ) -> str:
        principal_id = require_principal_id(owner_id)
        group_id = _valid_asset_id(metadata.get("id"))
        if not group_id:
            raise ValueError("Invalid or missing asset group ID")
        kind = str(metadata.get("kind") or "")
        if kind != "game_ui_group":
            raise ValueError("Invalid asset group kind")
        archive_path = self._path_from_output_url(metadata.get("download_url"))
        preview_path = self._path_from_output_url(metadata.get("sheet_url"))
        self.store.upsert_group(
            {
                "group_id": group_id,
                "owner_id": principal_id,
                "kind": kind,
                "status": "active",
                "manifest_path": self._relative_path(manifest_path),
                "archive_path": self._relative_path(archive_path),
                "preview_path": self._relative_path(preview_path),
                "created_at": self._created_timestamp(metadata, manifest_path),
                "updated_at": time.time(),
                "metadata": metadata,
            }
        )
        return group_id

    def _to_media_item(self, row: dict[str, Any]) -> dict[str, Any]:
        storage_path = self.resolve_storage_path(row.get("storage_path"))
        thumb_path = self.resolve_storage_path(row.get("thumbnail_path"))
        return {
            "id": row["asset_id"],
            "url": f"/outputs/{row['storage_path']}",
            "thumb_url": f"/outputs/{row['thumbnail_path']}" if thumb_path else None,
            "meta": row.get("metadata") or {},
            "status": row.get("status") or "active",
            "mtime": float(row.get("created_at") or 0),
            "path": storage_path,
        }

    def list_media(
        self,
        owner_id: str,
        kind: str,
        *,
        include_trash: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        principal_id = require_principal_id(owner_id)
        return [
            self._to_media_item(row)
            for row in self.store.list(
                principal_id,
                kinds=(kind,),
                include_trash=include_trash,
                limit=limit,
                offset=offset,
            )
        ]

    def count_media(self, owner_id: str, kind: str, *, include_trash: bool = False) -> int:
        return self.store.count(require_principal_id(owner_id), kinds=(kind,), include_trash=include_trash)

    def get(self, owner_id: str, asset_id: str) -> Optional[dict[str, Any]]:
        principal_id = require_principal_id(owner_id)
        safe_asset_id = _valid_asset_id(asset_id)
        if not safe_asset_id:
            return None
        return self.store.get(safe_asset_id, principal_id)

    def locate_metadata(self, owner_id: str, asset_id: str, *, kind: str | None = None) -> Optional[str]:
        row = self.get(owner_id, asset_id)
        if not row or (kind is not None and row.get("kind") != kind):
            return None
        path = self.resolve_storage_path(row.get("metadata_path"))
        return path if path and os.path.isfile(path) else None

    def update_status(self, owner_id: str, asset_id: str, status: str, *, kind: str | None = None) -> bool:
        if status not in {"active", "trash"}:
            raise ValueError("Invalid asset status")
        principal_id = require_principal_id(owner_id)
        with self._status_lock:
            row = self.get(principal_id, asset_id)
            if not row or (kind is not None and row.get("kind") != kind):
                return False
            meta_path = self.resolve_storage_path(row.get("metadata_path"))
            old_meta = dict(row.get("metadata") or {})
            new_meta = dict(old_meta)
            new_meta["status"] = status
            if meta_path:
                atomic_write_json(meta_path, new_meta)
            try:
                updated = self.store.update_status(asset_id, principal_id, status, new_meta)
            except Exception:
                if meta_path:
                    atomic_write_json(meta_path, old_meta)
                raise
            return updated

    def purge_trash_for_owner(self, owner_id: str) -> int:
        """Permanently remove trashed catalog assets for one owner.

        A catalog row is removed only after every existing file was deleted.
        Failures leave the row in trash so the operation can be retried and
        audited instead of falsely reporting success.
        """

        principal_id = require_principal_id(owner_id)
        rows = self.store.list(principal_id, include_trash=True)
        purged = 0
        for row in rows:
            if row.get("status") != "trash":
                continue
            paths = [
                self.resolve_storage_path(row.get("storage_path")),
                self.resolve_storage_path(row.get("thumbnail_path")),
                self.resolve_storage_path(row.get("metadata_path")),
            ]
            failed = False
            for path in paths:
                if not path or not os.path.exists(path):
                    continue
                try:
                    os.remove(path)
                except OSError:
                    failed = True
                    break
            if failed:
                continue
            if self.store.delete(row["asset_id"], principal_id):
                purged += 1
        return purged

    def backfill_legacy(self, *, dry_run: bool = False, only_missing: bool = False) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "scanned_metadata": 0,
            "registered": 0,
            "groups_registered": 0,
            "invalid_owner_directories": 0,
            "invalid_metadata": 0,
            "missing_media": 0,
            "errors": 0,
        }
        if not self.users_root.is_dir():
            return summary

        pending_records: list[dict[str, Any]] = []
        pending_groups: list[tuple[str, str, dict[str, Any]]] = []
        known_asset_ids = self.store.asset_ids() if only_missing and not dry_run else set()

        for owner_dir in self.users_root.iterdir():
            if not owner_dir.is_dir():
                continue
            owner_id = validate_principal_id(owner_dir.name)
            if not owner_id:
                summary["invalid_owner_directories"] += 1
                continue
            for meta_path in owner_dir.rglob("*.json"):
                summary["scanned_metadata"] += 1
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    summary["invalid_metadata"] += 1
                    continue
                if not isinstance(meta, dict):
                    summary["invalid_metadata"] += 1
                    continue
                if meta.get("kind") == "game_ui_group" and meta_path.name == "manifest.json":
                    if dry_run:
                        summary["groups_registered"] += 1
                    else:
                        pending_groups.append((owner_id, str(meta_path), meta))
                    continue
                asset_id = _valid_asset_id(meta.get("id"))
                if not asset_id or meta_path.stem != asset_id:
                    # Group manifests and other operational JSON are not assets.
                    continue
                if asset_id in known_asset_ids:
                    continue
                relative_parts = meta_path.relative_to(owner_dir).parts
                if "inputs" in relative_parts:
                    kind = "input"
                    extensions = (".png",)
                elif "audio" in relative_parts:
                    kind = "audio"
                    extensions = (".mp3", ".wav", ".flac", ".ogg", ".m4a")
                else:
                    kind = "image"
                    extensions = (".png",)
                media_path = None
                for extension in extensions:
                    candidate = meta_path.with_name(f"{asset_id}{extension}")
                    if candidate.is_file():
                        media_path = candidate
                        break
                if media_path is None:
                    summary["missing_media"] += 1
                    continue
                if dry_run:
                    summary["registered"] += 1
                    continue
                try:
                    pending_records.append(
                        self._catalog_record(
                            owner_id=owner_id,
                            kind=kind,
                            media_path=str(media_path),
                            metadata_path=str(meta_path),
                            metadata=meta,
                        )
                    )
                except Exception:
                    summary["errors"] += 1
        if not dry_run and pending_records:
            try:
                summary["registered"] = self.store.upsert_many(pending_records)
            except Exception:
                summary["errors"] += len(pending_records)
        if not dry_run:
            for owner_id, manifest_path, metadata in pending_groups:
                try:
                    self.register_group(owner_id=owner_id, manifest_path=manifest_path, metadata=metadata)
                    summary["groups_registered"] += 1
                except Exception:
                    summary["errors"] += 1
        summary["catalog"] = self.store.stats() if not dry_run else {}
        summary["groups"] = self.store.group_stats() if not dry_run else {}
        return summary

    def audit(self) -> dict[str, Any]:
        rows_missing_files = 0
        rows_missing_metadata = 0
        with self.store._connect() as con:
            rows = con.execute("SELECT storage_path, metadata_path FROM assets").fetchall()
            group_rows = con.execute(
                "SELECT manifest_path, archive_path, preview_path FROM asset_groups"
            ).fetchall()
        for row in rows:
            media = self.resolve_storage_path(row["storage_path"])
            meta = self.resolve_storage_path(row["metadata_path"])
            if not media or not os.path.isfile(media):
                rows_missing_files += 1
            if row["metadata_path"] and (not meta or not os.path.isfile(meta)):
                rows_missing_metadata += 1
        missing_group_files = 0
        for row in group_rows:
            for key in ("manifest_path", "archive_path", "preview_path"):
                path = self.resolve_storage_path(row[key])
                if row[key] and (not path or not os.path.isfile(path)):
                    missing_group_files += 1
        return {
            "catalog": self.store.stats(),
            "groups": self.store.group_stats(),
            "rows": len(rows),
            "group_rows": len(group_rows),
            "missing_files": rows_missing_files,
            "missing_metadata": rows_missing_metadata,
            "missing_group_files": missing_group_files,
        }
