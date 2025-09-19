import os
import sqlite3
from typing import Any, Dict, Optional


class JobStore:
    def __init__(self, db_path: str = "db/app_data.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL,
                    created_at REAL,
                    started_at REAL,
                    ended_at REAL,
                    error TEXT,
                    result_json TEXT,
                    artifact_available INTEGER
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_owner ON jobs(owner_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC)")
            # Migration: add artifact_available if missing
            try:
                con.execute("ALTER TABLE jobs ADD COLUMN artifact_available INTEGER")
            except Exception:
                pass

    def upsert_job(self, j: Dict[str, Any]):
        def _exec():
            with self._connect() as con:
                con.execute(
                    """
                    INSERT INTO jobs (id, owner_id, type, status, progress, created_at, started_at, ended_at, error, result_json, artifact_available)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, json(?), ?)
                    ON CONFLICT(id) DO UPDATE SET
                        owner_id=excluded.owner_id,
                        type=excluded.type,
                        status=excluded.status,
                        progress=excluded.progress,
                        created_at=excluded.created_at,
                        started_at=excluded.started_at,
                        ended_at=excluded.ended_at,
                        error=excluded.error,
                        result_json=excluded.result_json,
                        artifact_available=excluded.artifact_available
                    """,
                    (
                        j.get("id"),
                        j.get("owner_id"),
                        j.get("type"),
                        j.get("status"),
                        float(j.get("progress") or 0.0),
                        j.get("created_at"),
                        j.get("started_at"),
                        j.get("ended_at"),
                        j.get("error"),
                        json_dumps_safe(j.get("result") or {}),
                        1 if j.get("artifact_available") else 0,
                    ),
                )
        try:
            _exec()
        except Exception as e:
            # If table was removed with the DB file during runtime, re-init once and retry
            try:
                import sqlite3 as _sq
                if isinstance(e, _sq.OperationalError):
                    self._init_db()
                    _exec()
            except Exception:
                raise

    def fetch_recent(self, limit: int = 100) -> list[Dict[str, Any]]:
        def _query():
            with self._connect() as con:
                cur = con.execute(
                    "SELECT id, owner_id, type, status, progress, created_at, started_at, ended_at, error, result_json, COALESCE(artifact_available,0) FROM jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
                return cur.fetchall()
        try:
            rows = _query()
        except Exception as e:
            try:
                import sqlite3 as _sq
                if isinstance(e, _sq.OperationalError):
                    self._init_db()
                    rows = _query()
                else:
                    raise
            except Exception:
                return []
        items: list[Dict[str, Any]] = []
        for r in rows:
            items.append(
                {
                    "id": r[0],
                    "owner_id": r[1],
                    "type": r[2],
                    "status": r[3],
                    "progress": r[4],
                    "created_at": r[5],
                    "started_at": r[6],
                    "ended_at": r[7],
                    "error": r[8],
                    "result": json_loads_safe(r[9]) if r[9] is not None else {},
                    "artifact_available": bool(r[10])
                }
            )
        return items


def json_dumps_safe(obj: Any) -> str:
    try:
        import json

        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "{}"


def json_loads_safe(s: Optional[str]) -> Dict[str, Any]:
    if not s:
        return {}
    try:
        import json

        v = json.loads(s)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


