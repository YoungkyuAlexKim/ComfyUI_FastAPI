"""Persistent, reversible browser-to-MCP workspace links."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import sqlite3
import time
from typing import Any, Iterator

from .auth.user_management import require_principal_id


class PrincipalLinkConflict(ValueError):
    """Raised when an MCP workspace already belongs to another browser principal."""


class PrincipalLinkStore:
    """Store explicit links without transferring asset ownership.

    One MCP IP workspace can be linked to only one browser principal.  A
    browser principal may retain more than one historical MCP workspace so an
    infrastructure-approved IP change does not orphan earlier results.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS principal_links (
                    mcp_principal_id TEXT PRIMARY KEY,
                    web_principal_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_verified_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_principal_links_web "
                "ON principal_links(web_principal_id, created_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS principal_link_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    web_principal_id TEXT NOT NULL,
                    mcp_principal_id TEXT NOT NULL,
                    client_ip TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_principal_link_events_created "
                "ON principal_link_events(created_at DESC)"
            )

    @staticmethod
    def _validated_pair(web_principal_id: str, mcp_principal_id: str) -> tuple[str, str]:
        web_id = require_principal_id(web_principal_id)
        mcp_id = require_principal_id(mcp_principal_id)
        if not web_id.startswith("anon-"):
            raise ValueError("A browser principal is required")
        if not mcp_id.startswith("mcp-ip-"):
            raise ValueError("An MCP IP principal is required")
        return web_id, mcp_id

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        *,
        event_type: str,
        web_principal_id: str,
        mcp_principal_id: str,
        client_ip: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO principal_link_events(
                created_at, event_type, web_principal_id, mcp_principal_id,
                client_ip, details_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                event_type,
                web_principal_id,
                mcp_principal_id,
                str(client_ip or "").strip() or None,
                json.dumps(dict(details or {}), ensure_ascii=False),
            ),
        )

    def link(
        self,
        web_principal_id: str,
        mcp_principal_id: str,
        *,
        client_ip: str | None = None,
    ) -> dict[str, Any]:
        web_id, mcp_id = self._validated_pair(web_principal_id, mcp_principal_id)
        now = time.time()
        conflict = False
        created_at = now
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM principal_links WHERE mcp_principal_id=?",
                (mcp_id,),
            ).fetchone()
            if existing is not None and str(existing["web_principal_id"]) != web_id:
                self._event(
                    connection,
                    event_type="link_conflict",
                    web_principal_id=web_id,
                    mcp_principal_id=mcp_id,
                    client_ip=client_ip,
                )
                conflict = True
            elif existing is None:
                connection.execute(
                    """
                    INSERT INTO principal_links(
                        mcp_principal_id, web_principal_id, created_at, last_verified_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (mcp_id, web_id, now, now),
                )
                event_type = "linked"
            else:
                connection.execute(
                    "UPDATE principal_links SET last_verified_at=? WHERE mcp_principal_id=?",
                    (now, mcp_id),
                )
                event_type = "link_verified"
                created_at = float(existing["created_at"])
            if not conflict:
                self._event(
                    connection,
                    event_type=event_type,
                    web_principal_id=web_id,
                    mcp_principal_id=mcp_id,
                    client_ip=client_ip,
                )
        if conflict:
            raise PrincipalLinkConflict("This MCP workspace is already linked")
        return {
            "web_principal_id": web_id,
            "mcp_principal_id": mcp_id,
            "created_at": created_at,
            "last_verified_at": now,
        }

    def unlink(
        self,
        web_principal_id: str,
        mcp_principal_id: str,
        *,
        client_ip: str | None = None,
    ) -> bool:
        web_id, mcp_id = self._validated_pair(web_principal_id, mcp_principal_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            deleted = connection.execute(
                "DELETE FROM principal_links WHERE mcp_principal_id=? AND web_principal_id=?",
                (mcp_id, web_id),
            ).rowcount
            if deleted:
                self._event(
                    connection,
                    event_type="unlinked",
                    web_principal_id=web_id,
                    mcp_principal_id=mcp_id,
                    client_ip=client_ip,
                )
        return bool(deleted)

    def web_principal_for_mcp(self, mcp_principal_id: str) -> str | None:
        mcp_id = require_principal_id(mcp_principal_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT web_principal_id FROM principal_links WHERE mcp_principal_id=?",
                (mcp_id,),
            ).fetchone()
        return str(row["web_principal_id"]) if row else None

    def mcp_principals_for_web(self, web_principal_id: str) -> list[str]:
        web_id = require_principal_id(web_principal_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT mcp_principal_id FROM principal_links
                WHERE web_principal_id=? ORDER BY created_at, mcp_principal_id
                """,
                (web_id,),
            ).fetchall()
        return [str(row["mcp_principal_id"]) for row in rows]

    def is_linked(self, web_principal_id: str, mcp_principal_id: str) -> bool:
        web_id, mcp_id = self._validated_pair(web_principal_id, mcp_principal_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM principal_links
                WHERE mcp_principal_id=? AND web_principal_id=?
                """,
                (mcp_id, web_id),
            ).fetchone()
        return row is not None

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(1000, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM principal_link_events ORDER BY created_at DESC, id DESC LIMIT ?",
                (bounded,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["details"] = json.loads(item.pop("details_json") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                item["details"] = {}
            events.append(item)
        return events
