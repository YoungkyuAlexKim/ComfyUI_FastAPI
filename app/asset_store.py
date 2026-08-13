"""SQLite catalog for media assets.

Files remain on disk; this catalog is the authoritative index for ownership,
lifecycle and lookup.  Storage paths are relative to the configured output
root so the files can be moved as a unit later without rewriting every row.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterable, Optional


ASSET_SCHEMA_VERSION = 2


class AssetStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=30.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _init_db(self) -> None:
        with self._connect() as con:
            # WAL permits gallery reads while generation workers register new
            # assets.  journal_mode is database-wide and persists in SQLite.
            con.execute("PRAGMA journal_mode=WAL")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    name TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    applied_at REAL NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active', 'trash')),
                    storage_path TEXT NOT NULL,
                    metadata_path TEXT,
                    thumbnail_path TEXT,
                    mime_type TEXT,
                    byte_size INTEGER,
                    sha256 TEXT,
                    group_id TEXT,
                    source_job_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    deleted_at REAL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_assets_owner_kind_status_created "
                "ON assets(owner_id, kind, status, created_at DESC)"
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_assets_group ON assets(group_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_assets_sha256 ON assets(sha256)")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS asset_groups (
                    group_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active', 'trash')),
                    manifest_path TEXT,
                    archive_path TEXT,
                    preview_path TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_asset_groups_owner_status_created "
                "ON asset_groups(owner_id, status, created_at DESC)"
            )
            con.execute(
                """
                INSERT INTO schema_migrations(name, version, applied_at)
                VALUES('asset_catalog', ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    version=excluded.version,
                    applied_at=CASE
                        WHEN schema_migrations.version < excluded.version THEN excluded.applied_at
                        ELSE schema_migrations.applied_at
                    END
                """,
                (ASSET_SCHEMA_VERSION, time.time()),
            )

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
        if row is None:
            return None
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except Exception:
            item["metadata"] = {}
        return item

    @staticmethod
    def _upsert_on_connection(con: sqlite3.Connection, asset: dict[str, Any]) -> None:
        now = float(asset.get("updated_at") or time.time())
        metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
        cursor = con.execute(
            """
            INSERT INTO assets(
                asset_id, owner_id, kind, status, storage_path,
                metadata_path, thumbnail_path, mime_type, byte_size, sha256,
                group_id, source_job_id, created_at, updated_at, deleted_at,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, json(?))
            ON CONFLICT(asset_id) DO UPDATE SET
                kind=excluded.kind,
                status=excluded.status,
                storage_path=excluded.storage_path,
                metadata_path=excluded.metadata_path,
                thumbnail_path=excluded.thumbnail_path,
                mime_type=excluded.mime_type,
                byte_size=excluded.byte_size,
                sha256=excluded.sha256,
                group_id=excluded.group_id,
                source_job_id=COALESCE(excluded.source_job_id, assets.source_job_id),
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                deleted_at=excluded.deleted_at,
                metadata_json=excluded.metadata_json
            WHERE assets.owner_id=excluded.owner_id
            """,
            (
                asset["asset_id"],
                asset["owner_id"],
                asset["kind"],
                asset.get("status") or "active",
                asset["storage_path"],
                asset.get("metadata_path"),
                asset.get("thumbnail_path"),
                asset.get("mime_type"),
                asset.get("byte_size"),
                asset.get("sha256"),
                asset.get("group_id"),
                asset.get("source_job_id"),
                float(asset.get("created_at") or now),
                now,
                asset.get("deleted_at"),
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("Asset ID is already owned by another principal")

    def upsert(self, asset: dict[str, Any]) -> None:
        with self._connect() as con:
            self._upsert_on_connection(con, asset)

    def upsert_many(self, assets: Iterable[dict[str, Any]]) -> int:
        count = 0
        with self._connect() as con:
            for asset in assets:
                self._upsert_on_connection(con, asset)
                count += 1
        return count

    def get(self, asset_id: str, owner_id: str | None = None) -> Optional[dict[str, Any]]:
        sql = "SELECT * FROM assets WHERE asset_id=?"
        params: list[Any] = [asset_id]
        if owner_id is not None:
            sql += " AND owner_id=?"
            params.append(owner_id)
        with self._connect() as con:
            return self._decode(con.execute(sql, params).fetchone())

    def find_active_by_sha256(
        self,
        owner_id: str,
        sha256: str,
        *,
        kinds: Iterable[str] | None = None,
    ) -> Optional[dict[str, Any]]:
        clauses = ["owner_id=?", "sha256=?", "status='active'"]
        params: list[Any] = [owner_id, sha256]
        kind_values = tuple(str(kind) for kind in (kinds or ()))
        if kind_values:
            clauses.append(f"kind IN ({','.join('?' for _ in kind_values)})")
            params.extend(kind_values)
        sql = (
            f"SELECT * FROM assets WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC, asset_id DESC LIMIT 1"
        )
        with self._connect() as con:
            return self._decode(con.execute(sql, params).fetchone())

    def list(
        self,
        owner_id: str,
        *,
        kinds: Iterable[str] | None = None,
        include_trash: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["owner_id=?"]
        params: list[Any] = [owner_id]
        kind_values = tuple(str(kind) for kind in (kinds or ()))
        if kind_values:
            clauses.append(f"kind IN ({','.join('?' for _ in kind_values)})")
            params.extend(kind_values)
        if not include_trash:
            clauses.append("status='active'")
        sql = f"SELECT * FROM assets WHERE {' AND '.join(clauses)} ORDER BY created_at DESC, asset_id DESC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([max(1, int(limit)), max(0, int(offset))])
        with self._connect() as con:
            return [self._decode(row) for row in con.execute(sql, params).fetchall()]

    def count(self, owner_id: str, *, kinds: Iterable[str] | None = None, include_trash: bool = False) -> int:
        clauses = ["owner_id=?"]
        params: list[Any] = [owner_id]
        kind_values = tuple(str(kind) for kind in (kinds or ()))
        if kind_values:
            clauses.append(f"kind IN ({','.join('?' for _ in kind_values)})")
            params.extend(kind_values)
        if not include_trash:
            clauses.append("status='active'")
        with self._connect() as con:
            row = con.execute(f"SELECT COUNT(*) FROM assets WHERE {' AND '.join(clauses)}", params).fetchone()
        return int(row[0] if row else 0)

    def update_status(self, asset_id: str, owner_id: str, status: str, metadata: dict[str, Any]) -> bool:
        if status not in {"active", "trash"}:
            raise ValueError("Invalid asset status")
        now = time.time()
        deleted_at = now if status == "trash" else None
        with self._connect() as con:
            cur = con.execute(
                """
                UPDATE assets
                SET status=?, updated_at=?, deleted_at=?, metadata_json=json(?)
                WHERE asset_id=? AND owner_id=?
                """,
                (status, now, deleted_at, json.dumps(metadata, ensure_ascii=False), asset_id, owner_id),
            )
            return cur.rowcount == 1

    def delete(self, asset_id: str, owner_id: str) -> bool:
        with self._connect() as con:
            cur = con.execute("DELETE FROM assets WHERE asset_id=? AND owner_id=?", (asset_id, owner_id))
            return cur.rowcount == 1

    def stats(self) -> dict[str, int]:
        with self._connect() as con:
            rows = con.execute("SELECT kind, status, COUNT(*) AS count FROM assets GROUP BY kind, status").fetchall()
        return {f"{row['kind']}:{row['status']}": int(row["count"]) for row in rows}

    def asset_ids(self) -> set[str]:
        with self._connect() as con:
            return {str(row[0]) for row in con.execute("SELECT asset_id FROM assets").fetchall()}

    def upsert_group(self, group: dict[str, Any]) -> None:
        metadata = group.get("metadata") if isinstance(group.get("metadata"), dict) else {}
        now = float(group.get("updated_at") or time.time())
        with self._connect() as con:
            cursor = con.execute(
                """
                INSERT INTO asset_groups(
                    group_id, owner_id, kind, status, manifest_path,
                    archive_path, preview_path, created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, json(?))
                ON CONFLICT(group_id) DO UPDATE SET
                    kind=excluded.kind,
                    status=excluded.status,
                    manifest_path=excluded.manifest_path,
                    archive_path=excluded.archive_path,
                    preview_path=excluded.preview_path,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                WHERE asset_groups.owner_id=excluded.owner_id
                """,
                (
                    group["group_id"],
                    group["owner_id"],
                    group["kind"],
                    group.get("status") or "active",
                    group.get("manifest_path"),
                    group.get("archive_path"),
                    group.get("preview_path"),
                    float(group.get("created_at") or now),
                    now,
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            if cursor.rowcount != 1:
                raise sqlite3.IntegrityError("Asset group ID is already owned by another principal")

    def group_stats(self) -> dict[str, int]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT kind, status, COUNT(*) AS count FROM asset_groups GROUP BY kind, status"
            ).fetchall()
        return {f"{row['kind']}:{row['status']}": int(row["count"]) for row in rows}

    def migration_version(self, name: str) -> int:
        with self._connect() as con:
            row = con.execute("SELECT version FROM schema_migrations WHERE name=?", (name,)).fetchone()
        return int(row[0]) if row else 0

    def mark_migration(self, name: str, version: int) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO schema_migrations(name, version, applied_at)
                VALUES(?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET version=excluded.version, applied_at=excluded.applied_at
                """,
                (name, int(version), time.time()),
            )
