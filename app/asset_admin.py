"""Operational CLI for the media asset catalog.

Examples:
    python -m app.asset_admin audit
    python -m app.asset_admin backfill --dry-run
    python -m app.asset_admin backfill
    python -m app.asset_admin backup-db
    python -m app.asset_admin backup-all
    python -m app.asset_admin verify-backup backups/lc-ai-canvas-...
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any
import uuid

from .asset_store import AssetStore
from .config import JOB_DB_PATH, SERVER_CONFIG
from .services.asset_service import AssetService


def _service() -> AssetService:
    return AssetService(AssetStore(JOB_DB_PATH), SERVER_CONFIG["output_dir"])


BACKUP_FORMAT_VERSION = 1


def _backup_db(destination: str | None, *, source_path: str | Path | None = None) -> dict:
    source = Path(source_path or JOB_DB_PATH).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Database does not exist: {source}")
    if destination:
        target = Path(destination).resolve()
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = Path("backups") / f"app_data-{stamp}.db"
        target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.tmp")
    try:
        src = sqlite3.connect(source)
        dst = sqlite3.connect(temp)
        try:
            src.backup(dst)
            integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
            dst.commit()
        finally:
            dst.close()
            src.close()
        if integrity != "ok":
            raise RuntimeError(f"Backup integrity check failed: {integrity}")
        os.replace(temp, target)
    finally:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass
    return {"ok": True, "source": str(source), "backup": str(target), "integrity": "ok"}


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _principal_secret_bytes(secret_path: str | Path | None = None) -> tuple[bytes, str]:
    if secret_path is not None:
        path = Path(secret_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Principal cookie secret does not exist: {path}")
        raw = path.read_bytes().strip()
        source = str(path)
    else:
        configured = str(os.getenv("PRINCIPAL_COOKIE_SECRET") or "").strip()
        if configured:
            raw = configured.encode("utf-8")
            source = "PRINCIPAL_COOKIE_SECRET"
        else:
            configured_path = str(
                os.getenv("PRINCIPAL_COOKIE_SECRET_FILE")
                or "db/principal_cookie.secret"
            ).strip()
            path = Path(configured_path).resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Principal cookie secret does not exist: {path}")
            raw = path.read_bytes().strip()
            source = str(path)
    if len(raw) < 32:
        raise RuntimeError("Principal cookie secret must contain at least 32 bytes")
    return raw, source


def _backup_file_entries(bundle_path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(bundle_path.rglob("*"), key=lambda item: item.as_posix()):
        if path.name == "manifest.json" or path.is_dir():
            continue
        if path.is_symlink():
            raise RuntimeError(f"Backup contains a symbolic link: {path}")
        entries.append(
            {
                "path": path.relative_to(bundle_path).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return entries


def _catalog_backup_audit(database_path: Path, outputs_path: Path) -> dict[str, int]:
    # The backup is a closed, immutable snapshot. immutable=1 prevents a WAL-mode
    # database from creating -wal/-shm sidecars during verification.
    uri = f"{database_path.resolve().as_uri()}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True, timeout=30.0)
    con.row_factory = sqlite3.Row
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Backup database integrity check failed: {integrity}")
        rows = con.execute("SELECT storage_path, metadata_path FROM assets").fetchall()
        group_rows = con.execute(
            "SELECT manifest_path, archive_path, preview_path FROM asset_groups"
        ).fetchall()
    finally:
        con.close()

    missing_files = 0
    missing_metadata = 0
    missing_group_files = 0

    def existing(relative_path: object) -> bool:
        if not isinstance(relative_path, str) or not relative_path:
            return False
        candidate = (outputs_path / relative_path).resolve()
        if not _is_relative_to(candidate, outputs_path.resolve()):
            return False
        return candidate.is_file()

    for row in rows:
        if not existing(row["storage_path"]):
            missing_files += 1
        if row["metadata_path"] and not existing(row["metadata_path"]):
            missing_metadata += 1
    for row in group_rows:
        for key in ("manifest_path", "archive_path", "preview_path"):
            if row[key] and not existing(row[key]):
                missing_group_files += 1
    return {
        "rows": len(rows),
        "group_rows": len(group_rows),
        "missing_files": missing_files,
        "missing_metadata": missing_metadata,
        "missing_group_files": missing_group_files,
    }


def _verify_backup(bundle: str | Path) -> dict[str, Any]:
    bundle_path = Path(bundle).resolve()
    manifest_path = bundle_path / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Backup manifest does not exist: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format_version") != BACKUP_FORMAT_VERSION:
        raise RuntimeError("Unsupported or invalid backup manifest")

    expected_items = manifest.get("files")
    if not isinstance(expected_items, list):
        raise RuntimeError("Backup manifest files list is invalid")
    expected = {
        str(item.get("path")): item
        for item in expected_items
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if len(expected) != len(expected_items):
        raise RuntimeError("Backup manifest contains invalid or duplicate file entries")
    actual_items = _backup_file_entries(bundle_path)
    actual = {item["path"]: item for item in actual_items}
    if set(expected) != set(actual):
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        raise RuntimeError(f"Backup file set mismatch: missing={missing}, unexpected={unexpected}")
    for relative_path, item in expected.items():
        actual_item = actual[relative_path]
        if int(item.get("bytes", -1)) != actual_item["bytes"]:
            raise RuntimeError(f"Backup file size mismatch: {relative_path}")
        if str(item.get("sha256") or "") != actual_item["sha256"]:
            raise RuntimeError(f"Backup file checksum mismatch: {relative_path}")

    database_path = bundle_path / "app_data.db"
    outputs_path = bundle_path / "outputs"
    secret_path = bundle_path / "principal_cookie.secret"
    if not database_path.is_file() or not outputs_path.is_dir() or not secret_path.is_file():
        raise RuntimeError("Backup must contain app_data.db, outputs, and principal_cookie.secret")
    if len(secret_path.read_bytes().strip()) < 32:
        raise RuntimeError("Backed-up principal cookie secret is invalid")
    catalog = _catalog_backup_audit(database_path, outputs_path)
    if any(catalog[key] for key in ("missing_files", "missing_metadata", "missing_group_files")):
        raise RuntimeError(f"Backup catalog audit failed: {catalog}")
    return {
        "ok": True,
        "backup": str(bundle_path),
        "files": len(actual_items),
        "bytes": sum(int(item["bytes"]) for item in actual_items),
        "integrity": "ok",
        "catalog": catalog,
    }


def _backup_all(
    destination_root: str | Path | None,
    *,
    database_path: str | Path | None = None,
    output_root: str | Path | None = None,
    principal_secret_path: str | Path | None = None,
) -> dict[str, Any]:
    source_database = Path(database_path or JOB_DB_PATH).resolve()
    source_outputs = Path(output_root or SERVER_CONFIG["output_dir"]).resolve()
    if not source_outputs.is_dir():
        raise FileNotFoundError(f"Output directory does not exist: {source_outputs}")
    for path in source_outputs.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"Output backup does not follow symbolic links: {path}")

    backup_root = Path(destination_root or "backups").resolve()
    if _is_relative_to(backup_root, source_outputs):
        raise ValueError("Backup destination cannot be inside the outputs directory")
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle_name = f"lc-ai-canvas-{stamp}-{uuid.uuid4().hex[:8]}"
    target = backup_root / bundle_name
    temp = backup_root / f".{bundle_name}.tmp"
    secret_bytes, secret_source = _principal_secret_bytes(principal_secret_path)

    try:
        temp.mkdir()
        _backup_db(str(temp / "app_data.db"), source_path=source_database)
        shutil.copytree(source_outputs, temp / "outputs", copy_function=shutil.copy2)
        secret_target = temp / "principal_cookie.secret"
        secret_target.write_bytes(secret_bytes)
        try:
            os.chmod(secret_target, 0o600)
        except OSError:
            pass
        manifest = {
            "format_version": BACKUP_FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database_source": str(source_database),
            "outputs_source": str(source_outputs),
            "principal_secret_source": secret_source,
            "files": _backup_file_entries(temp),
        }
        (temp / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        verification = _verify_backup(temp)
        os.replace(temp, target)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    return {**verification, "backup": str(target)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Asset catalog maintenance")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("audit", help="Check catalog rows against files")
    backfill = sub.add_parser("backfill", help="Index legacy sidecars without moving files")
    backfill.add_argument("--dry-run", action="store_true")
    backup = sub.add_parser("backup-db", help="Create and verify an online SQLite backup")
    backup.add_argument("--destination")
    backup_all = sub.add_parser(
        "backup-all",
        help="Create and verify a DB + outputs + principal secret recovery set",
    )
    backup_all.add_argument("--destination-root")
    verify = sub.add_parser("verify-backup", help="Verify a complete recovery set without restoring it")
    verify.add_argument("backup")
    args = parser.parse_args()

    if args.command == "backup-db":
        result = _backup_db(args.destination)
    elif args.command == "backup-all":
        result = _backup_all(args.destination_root)
    elif args.command == "verify-backup":
        result = _verify_backup(args.backup)
    else:
        service = _service()
        if args.command == "audit":
            result = service.audit()
        else:
            result = service.backfill_legacy(dry_run=args.dry_run)
            if not args.dry_run and int(result.get("errors") or 0) == 0:
                service.store.mark_migration("asset_backfill", 1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
