"""Operational CLI for the media asset catalog.

Examples:
    python -m app.asset_admin audit
    python -m app.asset_admin backfill --dry-run
    python -m app.asset_admin backfill
    python -m app.asset_admin backup-db
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from .asset_store import AssetStore
from .config import JOB_DB_PATH, SERVER_CONFIG
from .services.asset_service import AssetService


def _service() -> AssetService:
    return AssetService(AssetStore(JOB_DB_PATH), SERVER_CONFIG["output_dir"])


def _backup_db(destination: str | None) -> dict:
    source = Path(JOB_DB_PATH).resolve()
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Asset catalog maintenance")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("audit", help="Check catalog rows against files")
    backfill = sub.add_parser("backfill", help="Index legacy sidecars without moving files")
    backfill.add_argument("--dry-run", action="store_true")
    backup = sub.add_parser("backup-db", help="Create and verify an online SQLite backup")
    backup.add_argument("--destination")
    args = parser.parse_args()

    if args.command == "backup-db":
        result = _backup_db(args.destination)
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
