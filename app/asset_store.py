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
                "CREATE INDEX IF NOT EXISTS idx_assets_owner_source_job "
                "ON assets(owner_id, source_job_id)"
            )
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

    def list_by_source_job(self, owner_id: str, source_job_id: str) -> list[dict[str, Any]]:
        """Return active output assets registered for one owner-scoped job."""

        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM assets "
                "WHERE owner_id=? AND source_job_id=? AND status='active' "
                "ORDER BY created_at, asset_id",
                (owner_id, source_job_id),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def list(
        self,
        owner_id: str,
        *,
        kinds: Iterable[str] | None = None,
        include_trash: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self.list_for_owners(
            (owner_id,),
            kinds=kinds,
            include_trash=include_trash,
            limit=limit,
            offset=offset,
        )

    def list_for_owners(
        self,
        owner_ids: Iterable[str],
        *,
        kinds: Iterable[str] | None = None,
        include_trash: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        owner_values = tuple(dict.fromkeys(str(owner_id) for owner_id in owner_ids))
        if not owner_values:
            return []
        clauses = [f"owner_id IN ({','.join('?' for _ in owner_values)})"]
        params: list[Any] = list(owner_values)
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

    def list_group_preserving_page(
        self,
        owner_id: str,
        *,
        kind: str,
        page: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        return self.list_group_preserving_page_for_owners(
            (owner_id,),
            kind=kind,
            page=page,
            size=size,
        )

    def list_group_preserving_page_for_owners(
        self,
        owner_ids: Iterable[str],
        *,
        kind: str,
        page: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Paginate active assets without splitting a catalog group.

        ``size`` is a target asset capacity, not a hard result limit. A group
        larger than the remaining capacity starts on the next page, and a
        single group larger than ``size`` occupies one page by itself. This is
        opt-in so existing offset-based API consumers keep their exact paging
        contract.
        """

        page = max(1, int(page))
        size = max(1, int(size))
        owner_values = tuple(dict.fromkeys(str(owner_id) for owner_id in owner_ids))
        if not owner_values:
            return [], {"page": page, "size": size, "total": 0, "total_pages": 0}
        owner_placeholders = ",".join("?" for _ in owner_values)
        with self._connect() as con:
            # Keep the block calculation and row fetch on one WAL snapshot if
            # a gallery delete/restore completes concurrently.
            con.execute("BEGIN")
            blocks = con.execute(
                """
                SELECT
                    owner_id || ':' || CASE
                        WHEN group_id IS NULL OR group_id = '' THEN 'asset:' || asset_id
                        ELSE 'group:' || group_id
                    END AS block_key,
                    MAX(CASE WHEN group_id IS NULL OR group_id = '' THEN asset_id END) AS asset_id,
                    MAX(CASE WHEN group_id IS NOT NULL AND group_id != '' THEN group_id END) AS group_id,
                    COUNT(*) AS weight,
                    MAX(created_at) AS sort_created_at,
                    MAX(asset_id) AS sort_asset_id
                FROM assets
                WHERE owner_id IN ({owner_placeholders}) AND kind=? AND status='active'
                GROUP BY block_key
                ORDER BY sort_created_at DESC, sort_asset_id DESC
                """.format(owner_placeholders=owner_placeholders),
                (*owner_values, kind),
            ).fetchall()

            pages: list[list[sqlite3.Row]] = []
            current: list[sqlite3.Row] = []
            current_weight = 0
            total = 0
            for block in blocks:
                weight = max(1, int(block["weight"] or 1))
                total += weight
                if current and current_weight + weight > size:
                    pages.append(current)
                    current = []
                    current_weight = 0
                current.append(block)
                current_weight += weight
            if current:
                pages.append(current)

            selected = pages[page - 1] if page <= len(pages) else []
            asset_ids = [str(block["asset_id"]) for block in selected if block["asset_id"]]
            group_ids = [str(block["group_id"]) for block in selected if block["group_id"]]
            clauses: list[str] = []
            query_params: list[Any] = [*owner_values, kind]
            if asset_ids:
                clauses.append(f"asset_id IN ({','.join('?' for _ in asset_ids)})")
                query_params.extend(asset_ids)
            if group_ids:
                clauses.append(f"group_id IN ({','.join('?' for _ in group_ids)})")
                query_params.extend(group_ids)

            rows: list[dict[str, Any]] = []
            if clauses:
                sql = (
                    f"SELECT * FROM assets WHERE owner_id IN ({owner_placeholders}) "
                    "AND kind=? AND status='active' AND ("
                    + " OR ".join(clauses)
                    + ") ORDER BY created_at DESC, asset_id DESC"
                )
                rows = [self._decode(row) for row in con.execute(sql, query_params).fetchall()]

        return rows, {
            "page": page,
            "size": size,
            "total": total,
            "total_pages": len(pages),
        }

    def count(self, owner_id: str, *, kinds: Iterable[str] | None = None, include_trash: bool = False) -> int:
        return self.count_for_owners((owner_id,), kinds=kinds, include_trash=include_trash)

    def count_for_owners(
        self,
        owner_ids: Iterable[str],
        *,
        kinds: Iterable[str] | None = None,
        include_trash: bool = False,
    ) -> int:
        owner_values = tuple(dict.fromkeys(str(owner_id) for owner_id in owner_ids))
        if not owner_values:
            return 0
        clauses = [f"owner_id IN ({','.join('?' for _ in owner_values)})"]
        params: list[Any] = list(owner_values)
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

    def get_group(self, group_id: str, owner_id: str | None = None) -> Optional[dict[str, Any]]:
        sql = "SELECT * FROM asset_groups WHERE group_id=?"
        params: list[Any] = [group_id]
        if owner_id is not None:
            sql += " AND owner_id=?"
            params.append(owner_id)
        with self._connect() as con:
            return self._decode(con.execute(sql, params).fetchone())

    def list_groups(self, owner_id: str, *, include_trash: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM asset_groups WHERE owner_id=?"
        params: list[Any] = [owner_id]
        if not include_trash:
            sql += " AND status='active'"
        sql += " ORDER BY created_at DESC, group_id DESC"
        with self._connect() as con:
            return [self._decode(row) for row in con.execute(sql, params).fetchall()]

    def list_group_assets(self, group_id: str, owner_id: str) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM assets WHERE group_id=? AND owner_id=? ORDER BY created_at, asset_id",
                (group_id, owner_id),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def update_group_bundle_status(
        self,
        group_id: str,
        owner_id: str,
        status: str,
        *,
        group_metadata: dict[str, Any],
        asset_metadata: dict[str, dict[str, Any]],
    ) -> int:
        """Atomically change one group and every child to the same lifecycle state."""

        if status not in {"active", "trash"}:
            raise ValueError("Invalid asset status")
        now = time.time()
        deleted_at = now if status == "trash" else None
        with self._connect() as con:
            group = con.execute(
                "SELECT group_id FROM asset_groups WHERE group_id=? AND owner_id=?",
                (group_id, owner_id),
            ).fetchone()
            if group is None:
                return 0
            rows = con.execute(
                "SELECT asset_id FROM assets WHERE group_id=? AND owner_id=? ORDER BY asset_id",
                (group_id, owner_id),
            ).fetchall()
            asset_ids = [str(row["asset_id"]) for row in rows]
            if not asset_ids:
                return 0
            if set(asset_ids) != set(asset_metadata):
                raise ValueError("Asset group metadata does not match its catalog children")
            for asset_id in asset_ids:
                con.execute(
                    """
                    UPDATE assets
                    SET status=?, updated_at=?, deleted_at=?, metadata_json=json(?)
                    WHERE asset_id=? AND owner_id=? AND group_id=?
                    """,
                    (
                        status,
                        now,
                        deleted_at,
                        json.dumps(asset_metadata[asset_id], ensure_ascii=False),
                        asset_id,
                        owner_id,
                        group_id,
                    ),
                )
            cursor = con.execute(
                """
                UPDATE asset_groups
                SET status=?, updated_at=?, metadata_json=json(?)
                WHERE group_id=? AND owner_id=?
                """,
                (
                    status,
                    now,
                    json.dumps(group_metadata, ensure_ascii=False),
                    group_id,
                    owner_id,
                ),
            )
            if cursor.rowcount != 1:
                raise sqlite3.IntegrityError("Asset group status update lost ownership")
        return len(asset_ids)

    def delete_group_bundle(self, group_id: str, owner_id: str) -> int:
        """Delete a catalog group and all of its children in one transaction."""

        with self._connect() as con:
            group = con.execute(
                "SELECT group_id FROM asset_groups WHERE group_id=? AND owner_id=?",
                (group_id, owner_id),
            ).fetchone()
            if group is None:
                return 0
            child_count = int(
                con.execute(
                    "SELECT COUNT(*) FROM assets WHERE group_id=? AND owner_id=?",
                    (group_id, owner_id),
                ).fetchone()[0]
            )
            con.execute(
                "DELETE FROM assets WHERE group_id=? AND owner_id=?",
                (group_id, owner_id),
            )
            cursor = con.execute(
                "DELETE FROM asset_groups WHERE group_id=? AND owner_id=?",
                (group_id, owner_id),
            )
            if cursor.rowcount != 1:
                raise sqlite3.IntegrityError("Asset group deletion lost ownership")
        return child_count

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

    @staticmethod
    def _upsert_group_on_connection(con: sqlite3.Connection, group: dict[str, Any]) -> None:
        metadata = group.get("metadata") if isinstance(group.get("metadata"), dict) else {}
        now = float(group.get("updated_at") or time.time())
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

    def upsert_group(self, group: dict[str, Any]) -> None:
        with self._connect() as con:
            self._upsert_group_on_connection(con, group)

    def upsert_asset_group_bundle(
        self,
        assets: Iterable[dict[str, Any]],
        group: dict[str, Any],
    ) -> int:
        """Atomically register all child assets and their owning group."""

        count = 0
        with self._connect() as con:
            for asset in assets:
                self._upsert_on_connection(con, asset)
                count += 1
            self._upsert_group_on_connection(con, group)
        return count

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
