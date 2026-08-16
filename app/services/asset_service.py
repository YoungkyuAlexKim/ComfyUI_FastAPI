"""Authoritative media asset service shared by web routes and MCP adapters."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import threading
import time
import uuid
from typing import Any, Optional

from ..asset_store import AssetStore
from ..auth.user_management import require_principal_id, validate_principal_id

try:
    from PIL import Image
except Exception:
    Image = None


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
        record = self._group_catalog_record(
            owner_id=owner_id,
            manifest_path=manifest_path,
            metadata=metadata,
        )
        self.store.upsert_group(record)
        return str(record["group_id"])

    def _group_catalog_record(
        self,
        *,
        owner_id: str,
        manifest_path: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        principal_id = require_principal_id(owner_id)
        group_id = _valid_asset_id(metadata.get("id"))
        if not group_id:
            raise ValueError("Invalid or missing asset group ID")
        kind = str(metadata.get("kind") or "")
        if kind != "game_ui_group":
            raise ValueError("Invalid asset group kind")
        status = str(metadata.get("status") or "active")
        if status not in {"active", "trash"}:
            status = "active"
        archive_path = self._path_from_output_url(metadata.get("download_url"))
        preview_path = self._path_from_output_url(metadata.get("sheet_url"))
        return {
            "group_id": group_id,
            "owner_id": principal_id,
            "kind": kind,
            "status": status,
            "manifest_path": self._relative_path(manifest_path),
            "archive_path": self._relative_path(archive_path),
            "preview_path": self._relative_path(preview_path),
            "created_at": self._created_timestamp(metadata, manifest_path),
            "updated_at": time.time(),
            "metadata": metadata,
        }

    def register_asset_group_bundle(
        self,
        *,
        owner_id: str,
        assets: list[dict[str, Any]],
        manifest_path: str,
        group_metadata: dict[str, Any],
    ) -> str:
        """Atomically register prepared child files and their group metadata."""

        records = [
            self._catalog_record(
                owner_id=owner_id,
                kind=str(asset["kind"]),
                media_path=str(asset["media_path"]),
                metadata_path=asset.get("metadata_path"),
                metadata=dict(asset["metadata"]),
                source_job_id=asset.get("source_job_id"),
            )
            for asset in assets
        ]
        group_record = self._group_catalog_record(
            owner_id=owner_id,
            manifest_path=manifest_path,
            metadata=group_metadata,
        )
        self.store.upsert_asset_group_bundle(records, group_record)
        return str(group_record["group_id"])

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

    def list_media_group_preserving_page(
        self,
        owner_id: str,
        kind: str,
        *,
        page: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Return an opt-in gallery page that keeps grouped assets together."""

        principal_id = require_principal_id(owner_id)
        if kind not in {"image", "input", "audio"}:
            raise ValueError("Invalid asset kind")
        rows, pagination = self.store.list_group_preserving_page(
            principal_id,
            kind=kind,
            page=page,
            size=size,
        )
        return [self._to_media_item(row) for row in rows], pagination

    def count_media(self, owner_id: str, kind: str, *, include_trash: bool = False) -> int:
        return self.store.count(require_principal_id(owner_id), kinds=(kind,), include_trash=include_trash)

    def list_assets(
        self,
        owner_id: str,
        *,
        kinds: tuple[str, ...],
        include_trash: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return owner-scoped catalog rows for trusted API adapters."""

        principal_id = require_principal_id(owner_id)
        normalized_kinds = tuple(dict.fromkeys(str(kind).strip() for kind in kinds))
        if not normalized_kinds or any(kind not in {"image", "input", "audio"} for kind in normalized_kinds):
            raise ValueError("Invalid asset kinds")
        return self.store.list(
            principal_id,
            kinds=normalized_kinds,
            include_trash=include_trash,
            limit=limit,
            offset=offset,
        )

    def count_assets(
        self,
        owner_id: str,
        *,
        kinds: tuple[str, ...],
        include_trash: bool = False,
    ) -> int:
        principal_id = require_principal_id(owner_id)
        normalized_kinds = tuple(dict.fromkeys(str(kind).strip() for kind in kinds))
        if not normalized_kinds or any(kind not in {"image", "input", "audio"} for kind in normalized_kinds):
            raise ValueError("Invalid asset kinds")
        return self.store.count(principal_id, kinds=normalized_kinds, include_trash=include_trash)

    def find_active_by_sha256(
        self,
        owner_id: str,
        sha256: str,
        *,
        kinds: tuple[str, ...],
    ) -> Optional[dict[str, Any]]:
        principal_id = require_principal_id(owner_id)
        digest = str(sha256 or "").strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("Invalid SHA-256 digest")
        normalized_kinds = tuple(dict.fromkeys(str(kind).strip() for kind in kinds))
        if not normalized_kinds or any(kind not in {"image", "input", "audio"} for kind in normalized_kinds):
            raise ValueError("Invalid asset kinds")
        return self.store.find_active_by_sha256(principal_id, digest, kinds=normalized_kinds)

    def create_input_image(
        self,
        owner_id: str,
        png_bytes: bytes,
        original_filename: str,
    ) -> dict[str, Any]:
        """Persist a normalized PNG input and compensate files if catalog registration fails."""

        principal_id = require_principal_id(owner_id)
        if not isinstance(png_bytes, bytes) or not png_bytes:
            raise ValueError("Input image bytes are required")
        now = datetime.now(timezone.utc)
        input_id = uuid.uuid4().hex
        dated_dir = self.users_root / principal_id / "inputs" / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
        media_path = dated_dir / f"{input_id}.png"
        metadata_path = dated_dir / f"{input_id}.json"
        thumbnail_path: Path | None = None
        created_paths: list[Path] = []

        try:
            atomic_write_bytes(media_path, png_bytes)
            created_paths.append(media_path)
            if Image is not None:
                try:
                    with Image.open(BytesIO(png_bytes)) as source:
                        has_alpha = source.mode in ("RGBA", "LA") or (
                            source.mode == "P" and "transparency" in (source.info or {})
                        )
                        thumbnail = source.convert("RGBA" if has_alpha else "RGB")
                        thumbnail.thumbnail((384, 384))
                        thumb_dir = dated_dir / "thumb"
                        if has_alpha:
                            thumbnail_path = thumb_dir / f"{input_id}.webp"
                            out = BytesIO()
                            thumbnail.save(out, format="WEBP", quality=82, method=4)
                        else:
                            thumbnail_path = thumb_dir / f"{input_id}.jpg"
                            out = BytesIO()
                            thumbnail.save(out, format="JPEG", quality=85, optimize=True)
                        atomic_write_bytes(thumbnail_path, out.getvalue())
                        created_paths.append(thumbnail_path)
                except Exception:
                    thumbnail_path = None

            digest = hashlib.sha256(png_bytes).hexdigest()
            metadata = {
                "id": input_id,
                "owner": principal_id,
                "kind": "input",
                "original_filename": str(original_filename or "upload.png"),
                "mime": "image/png",
                "bytes": len(png_bytes),
                "sha256": digest,
                "created_at": now.isoformat(),
                "status": "active",
                "thumb": (
                    f"/outputs/{self._relative_path(thumbnail_path)}"
                    if thumbnail_path is not None
                    else None
                ),
                "tags": [],
            }
            atomic_write_json(metadata_path, metadata)
            created_paths.append(metadata_path)
            self.register(
                owner_id=principal_id,
                kind="input",
                media_path=str(media_path),
                metadata_path=str(metadata_path),
                metadata=metadata,
            )
            row = self.get(principal_id, input_id)
            if row is None:
                raise RuntimeError("Input asset registration did not produce a catalog row")
            return row
        except Exception:
            for path in reversed(created_paths):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    def get(self, owner_id: str, asset_id: str) -> Optional[dict[str, Any]]:
        principal_id = require_principal_id(owner_id)
        safe_asset_id = _valid_asset_id(asset_id)
        if not safe_asset_id:
            return None
        return self.store.get(safe_asset_id, principal_id)

    def get_group(self, owner_id: str, group_id: str) -> Optional[dict[str, Any]]:
        principal_id = require_principal_id(owner_id)
        safe_group_id = _valid_asset_id(group_id)
        if not safe_group_id:
            return None
        return self.store.get_group(safe_group_id, principal_id)

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
            group_id = _valid_asset_id(row.get("group_id"))
            if row.get("kind") == "image" and group_id:
                return self.update_group_status(principal_id, group_id, status)
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

    def update_group_status(self, owner_id: str, group_id: str, status: str) -> bool:
        """Move a Game UI bundle and all of its children together.

        JSON sidecars are updated before the single SQLite transaction. If any
        write or catalog update fails, every file already touched is restored
        to its exact previous bytes.
        """

        if status not in {"active", "trash"}:
            raise ValueError("Invalid asset status")
        principal_id = require_principal_id(owner_id)
        safe_group_id = _valid_asset_id(group_id)
        if not safe_group_id:
            return False
        with self._status_lock:
            group = self.store.get_group(safe_group_id, principal_id)
            if not group or group.get("kind") != "game_ui_group":
                return False
            children = self.store.list_group_assets(safe_group_id, principal_id)
            if not children:
                return False

            group_metadata = dict(group.get("metadata") or {})
            group_metadata["status"] = status
            child_metadata: dict[str, dict[str, Any]] = {}
            writes: list[tuple[Path, bytes | None]] = []

            def write_status_file(relative_path: object, metadata: dict[str, Any]) -> None:
                relative = relative_path if isinstance(relative_path, str) else None
                resolved = self.resolve_storage_path(relative)
                if not resolved:
                    return
                path = Path(resolved)
                previous = path.read_bytes() if path.is_file() else None
                atomic_write_json(path, metadata)
                writes.append((path, previous))

            try:
                for child in children:
                    asset_id = str(child["asset_id"])
                    metadata = dict(child.get("metadata") or {})
                    metadata["status"] = status
                    child_metadata[asset_id] = metadata
                    write_status_file(child.get("metadata_path"), metadata)
                write_status_file(group.get("manifest_path"), group_metadata)
                updated = self.store.update_group_bundle_status(
                    safe_group_id,
                    principal_id,
                    status,
                    group_metadata=group_metadata,
                    asset_metadata=child_metadata,
                )
                return updated == len(children)
            except Exception:
                for path, previous in reversed(writes):
                    try:
                        if previous is None:
                            path.unlink(missing_ok=True)
                        else:
                            atomic_write_bytes(path, previous)
                    except OSError:
                        pass
                raise

    def purge_trash_for_owner(self, owner_id: str) -> int:
        """Permanently remove trashed catalog assets for one owner.

        A catalog row is removed only after every existing file was deleted.
        Failures leave the row in trash so the operation can be retried and
        audited instead of falsely reporting success.
        """

        principal_id = require_principal_id(owner_id)
        rows = self.store.list(principal_id, include_trash=True)
        groups = self.store.list_groups(principal_id, include_trash=True)
        purged = 0
        grouped_asset_ids: set[str] = set()
        for group in groups:
            group_id = str(group.get("group_id") or "")
            children = self.store.list_group_assets(group_id, principal_id)
            grouped_asset_ids.update(str(child["asset_id"]) for child in children)
            if group.get("status") != "trash" or not children:
                continue
            # A partially trashed legacy bundle must never be physically
            # dismantled. New status transitions make this state impossible.
            if any(child.get("status") != "trash" for child in children):
                continue
            candidate_paths = [
                self.resolve_storage_path(group.get("manifest_path")),
                self.resolve_storage_path(group.get("archive_path")),
                self.resolve_storage_path(group.get("preview_path")),
            ]
            existing_parents = {Path(path).resolve().parent for path in candidate_paths if path}
            if len(existing_parents) != 1:
                continue
            group_dir = next(iter(existing_parents))
            owner_root = (self.users_root / principal_id).resolve()
            try:
                group_dir.relative_to(owner_root)
            except ValueError:
                continue
            if group_dir.name != group_id or group_dir.parent.name != "game_ui_groups":
                continue
            try:
                if group_dir.exists():
                    shutil.rmtree(group_dir)
            except OSError:
                continue
            purged += self.store.delete_group_bundle(group_id, principal_id)

        for row in rows:
            if row.get("status") != "trash":
                continue
            if str(row.get("asset_id")) in grouped_asset_ids:
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
