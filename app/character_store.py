import os
import sqlite3
from contextlib import contextmanager
import time
import uuid
from typing import Any, Dict, List, Optional


REQUIRED_CHARACTER_REFERENCE_IMAGE_COUNT = 6


def _json_dumps_safe(obj: Any) -> str:
    try:
        import json

        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "[]"


def _json_loads_list_safe(s: Optional[str]) -> List[str]:
    if not s:
        return []
    try:
        import json

        v = json.loads(s)
        if isinstance(v, list):
            out: List[str] = []
            for x in v:
                try:
                    t = str(x or "").strip()
                except Exception:
                    t = ""
                if t:
                    out.append(t)
            return out
        return []
    except Exception:
        return []


class CharacterStore:
    """
    Per-user character registry for NanoBanana reference workflows.

    Storage: SQLite (db/app_data.db) with best-effort migrations (like JobStore/FeedStore).
    Key: (owner_id, name) unique.
    """

    def __init__(self, db_path: str = "db/app_data.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=30.0)
        con.execute("PRAGMA busy_timeout=5000")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _init_db(self):
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS character_registry (
                    character_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    reference_image_ids TEXT NOT NULL,
                    thumbnail_image_id TEXT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            con.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_character_owner_name ON character_registry(owner_id, name)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_character_owner_status_updated ON character_registry(owner_id, status, updated_at DESC)"
            )
            # Best-effort migrations: add columns if missing
            for stmt in [
                "ALTER TABLE character_registry ADD COLUMN thumbnail_image_id TEXT NULL",
                "ALTER TABLE character_registry ADD COLUMN updated_at REAL NOT NULL DEFAULT 0",
                "ALTER TABLE character_registry ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
            ]:
                try:
                    con.execute(stmt)
                except Exception:
                    pass

    def list_characters(self, owner_id: str, status: str = "active") -> List[Dict[str, Any]]:
        oid = str(owner_id or "")
        if not oid:
            return []
        st = str(status or "active").strip().lower()
        if st not in ("active", "archived", "deleted", "all"):
            st = "active"

        out: List[Dict[str, Any]] = []
        with self._connect() as con:
            if st == "all":
                cur = con.execute(
                    """
                    SELECT character_id, owner_id, name, reference_image_ids, thumbnail_image_id, created_at, updated_at, status
                    FROM character_registry
                    WHERE owner_id = ?
                    ORDER BY updated_at DESC, created_at DESC
                    """,
                    (oid,),
                )
            else:
                cur = con.execute(
                    """
                    SELECT character_id, owner_id, name, reference_image_ids, thumbnail_image_id, created_at, updated_at, status
                    FROM character_registry
                    WHERE owner_id = ? AND status = ?
                    ORDER BY updated_at DESC, created_at DESC
                    """,
                    (oid, st),
                )
            rows = cur.fetchall() or []

            for r in rows:
                refs = _json_loads_list_safe(r[3])
                refs = self._maybe_migrate_reference_count(con, oid, str(r[2] or ""), refs)
                out.append(
                    {
                        "character_id": r[0],
                        "owner_id": r[1],
                        "name": r[2],
                        "reference_image_ids": refs,
                        "thumbnail_image_id": r[4],
                        "created_at": float(r[5] or 0),
                        "updated_at": float(r[6] or 0),
                        "status": r[7],
                    }
                )
        return out

    def get_by_name(self, owner_id: str, name: str) -> Optional[Dict[str, Any]]:
        oid = str(owner_id or "")
        nm = str(name or "").strip()
        if not oid or not nm:
            return None
        with self._connect() as con:
            row = con.execute(
                """
                SELECT character_id, owner_id, name, reference_image_ids, thumbnail_image_id, created_at, updated_at, status
                FROM character_registry
                WHERE owner_id = ? AND name = ?
                LIMIT 1
                """,
                (oid, nm),
            ).fetchone()
            if not row:
                return None

            refs = _json_loads_list_safe(row[3])
            refs = self._maybe_migrate_reference_count(con, oid, nm, refs)

            return {
                "character_id": row[0],
                "owner_id": row[1],
                "name": row[2],
                "reference_image_ids": refs,
                "thumbnail_image_id": row[4],
                "created_at": float(row[5] or 0),
                "updated_at": float(row[6] or 0),
                "status": row[7],
            }

    def _maybe_migrate_reference_count(
        self, con: sqlite3.Connection, owner_id: str, name: str, refs: List[str]
    ) -> List[str]:
        """
        Legacy migration:
        - 이전 버전(레퍼런스 5장) 데이터를 발견하면, 첫 번째 이미지를 1장 복제해서 6장으로 보정합니다.
        - DB에도 best-effort로 반영해, 다음부터는 항상 6장으로 동작하게 합니다.
        """
        try:
            refs2 = [str(x or "").strip() for x in (refs or [])]
            refs2 = [x for x in refs2 if x]
        except Exception:
            refs2 = []

        if len(refs2) == REQUIRED_CHARACTER_REFERENCE_IMAGE_COUNT:
            return refs2

        # Legacy: 5 -> 6 자동 보정
        if len(refs2) == 5:
            try:
                refs2.append(refs2[0])
            except Exception:
                return refs2
            try:
                now = float(time.time())
                con.execute(
                    """
                    UPDATE character_registry
                    SET reference_image_ids = ?, updated_at = ?
                    WHERE owner_id = ? AND name = ?
                    """,
                    (_json_dumps_safe(refs2), now, str(owner_id or ""), str(name or "").strip()),
                )
            except Exception:
                pass
            return refs2

        return refs2

    def upsert_character(
        self,
        owner_id: str,
        *,
        name: str,
        reference_image_ids: List[str],
        thumbnail_image_id: Optional[str] = None,
        status: str = "active",
    ) -> Dict[str, Any]:
        oid = str(owner_id or "")
        nm = str(name or "").strip()
        if not oid or not nm:
            raise ValueError("missing_owner_or_name")
        refs = [str(x or "").strip() for x in (reference_image_ids or [])]
        refs = [x for x in refs if x]
        if not refs:
            raise ValueError("missing_reference_images")
        if len(refs) != REQUIRED_CHARACTER_REFERENCE_IMAGE_COUNT:
            raise ValueError("invalid_reference_image_count")
        st = str(status or "active").strip().lower()
        if st not in ("active", "archived", "deleted"):
            st = "active"

        now = float(time.time())
        existing = self.get_by_name(oid, nm)
        if existing and existing.get("character_id"):
            cid = str(existing["character_id"])
            with self._connect() as con:
                con.execute(
                    """
                    UPDATE character_registry
                    SET reference_image_ids = ?, thumbnail_image_id = ?, updated_at = ?, status = ?
                    WHERE owner_id = ? AND name = ?
                    """,
                    (_json_dumps_safe(refs), thumbnail_image_id, now, st, oid, nm),
                )
            out = dict(existing)
            out["reference_image_ids"] = refs
            out["thumbnail_image_id"] = thumbnail_image_id
            out["updated_at"] = now
            out["status"] = st
            return out

        cid = uuid.uuid4().hex
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO character_registry (
                    character_id, owner_id, name, reference_image_ids, thumbnail_image_id, created_at, updated_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cid, oid, nm, _json_dumps_safe(refs), thumbnail_image_id, now, now, st),
            )
        return {
            "character_id": cid,
            "owner_id": oid,
            "name": nm,
            "reference_image_ids": refs,
            "thumbnail_image_id": thumbnail_image_id,
            "created_at": now,
            "updated_at": now,
            "status": st,
        }

    def soft_delete(self, owner_id: str, name: str) -> bool:
        oid = str(owner_id or "")
        nm = str(name or "").strip()
        if not oid or not nm:
            return False
        now = float(time.time())
        with self._connect() as con:
            cur = con.execute(
                """
                UPDATE character_registry
                SET status = 'deleted', updated_at = ?
                WHERE owner_id = ? AND name = ?
                """,
                (now, oid, nm),
            )
            return cur.rowcount > 0

