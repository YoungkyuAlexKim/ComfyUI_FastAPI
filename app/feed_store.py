import os
import sqlite3
import time
from typing import Any, Dict, Optional


class FeedStore:
    REACTION_TYPES = ("love", "like", "laugh", "wow", "fire")

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
                CREATE TABLE IF NOT EXISTS feed_posts (
                    post_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    author_name TEXT NULL,
                    prompt TEXT NOT NULL,
                    workflow_id TEXT NULL,
                    seed INTEGER NULL,
                    aspect_ratio TEXT NULL,
                    image_url TEXT NOT NULL,
                    thumb_url TEXT NULL,
                    input_image_url TEXT NULL,
                    input_thumb_url TEXT NULL,
                    source_image_id TEXT NULL,
                    input_source_image_id TEXT NULL,
                    published_at REAL NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS feed_likes (
                    post_id TEXT NOT NULL,
                    liker_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(post_id, liker_id)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS feed_reactions (
                    post_id TEXT NOT NULL,
                    reactor_id TEXT NOT NULL,
                    reaction TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(post_id, reactor_id)
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_feed_posts_published ON feed_posts(published_at DESC)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_feed_posts_status ON feed_posts(status)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_feed_posts_owner ON feed_posts(owner_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_feed_posts_source ON feed_posts(source_image_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_feed_likes_post ON feed_likes(post_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_feed_likes_liker ON feed_likes(liker_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_feed_reactions_post ON feed_reactions(post_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_feed_reactions_reactor ON feed_reactions(reactor_id)")

            # Best-effort migrations: add new columns if missing (SQLite will throw if exists)
            for stmt in [
                "ALTER TABLE feed_posts ADD COLUMN input_image_url TEXT NULL",
                "ALTER TABLE feed_posts ADD COLUMN input_thumb_url TEXT NULL",
                "ALTER TABLE feed_posts ADD COLUMN input_source_image_id TEXT NULL",
            ]:
                try:
                    con.execute(stmt)
                except Exception:
                    pass

    def create_post(self, post: Dict[str, Any]):
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO feed_posts (
                    post_id, owner_id, author_name, prompt, workflow_id, seed, aspect_ratio,
                    image_url, thumb_url, input_image_url, input_thumb_url,
                    source_image_id, input_source_image_id,
                    published_at, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    post.get("post_id"),
                    post.get("owner_id"),
                    post.get("author_name"),
                    post.get("prompt"),
                    post.get("workflow_id"),
                    post.get("seed"),
                    post.get("aspect_ratio"),
                    post.get("image_url"),
                    post.get("thumb_url"),
                    post.get("input_image_url"),
                    post.get("input_thumb_url"),
                    post.get("source_image_id"),
                    post.get("input_source_image_id"),
                    float(post.get("published_at") or time.time()),
                    post.get("status") or "active",
                ),
            )

    def get_post(self, post_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as con:
            cur = con.execute(
                """
                SELECT
                    post_id, owner_id, author_name, prompt, workflow_id, seed, aspect_ratio,
                    image_url, thumb_url, input_image_url, input_thumb_url,
                    source_image_id, input_source_image_id,
                    published_at, status
                FROM feed_posts
                WHERE post_id = ?
                """,
                (post_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "post_id": row[0],
                "owner_id": row[1],
                "author_name": row[2],
                "prompt": row[3],
                "workflow_id": row[4],
                "seed": row[5],
                "aspect_ratio": row[6],
                "image_url": row[7],
                "thumb_url": row[8],
                "input_image_url": row[9],
                "input_thumb_url": row[10],
                "source_image_id": row[11],
                "input_source_image_id": row[12],
                "published_at": row[13],
                "status": row[14],
            }

    def update_status(self, post_id: str, status: str) -> bool:
        with self._connect() as con:
            cur = con.execute("UPDATE feed_posts SET status = ? WHERE post_id = ?", (status, post_id))
            return cur.rowcount > 0

    def delete_post_and_likes(self, post_id: str) -> bool:
        with self._connect() as con:
            con.execute("DELETE FROM feed_likes WHERE post_id = ?", (post_id,))
            con.execute("DELETE FROM feed_reactions WHERE post_id = ?", (post_id,))
            cur = con.execute("DELETE FROM feed_posts WHERE post_id = ?", (post_id,))
            return cur.rowcount > 0

    def list_posts(self, include: str, page: int, size: int, sort: str = "newest") -> Dict[str, Any]:
        size_val = max(1, min(100, int(size or 24)))
        page_val = max(1, int(page or 1))
        offset = (page_val - 1) * size_val

        where = ""
        params = []
        inc = (include or "active").strip().lower()
        if inc == "active":
            where = "WHERE status = 'active'"
        elif inc == "trash":
            where = "WHERE status = 'trash'"
        elif inc == "all":
            where = ""
        else:
            where = "WHERE status = 'active'"

        sort_key = (sort or "newest").strip().lower()
        if sort_key not in ("newest", "oldest", "most_reactions"):
            sort_key = "newest"

        # Ordering
        if sort_key == "oldest":
            order_sql = "ORDER BY published_at ASC"
        elif sort_key == "most_reactions":
            # Total reactions = legacy likes + new reactions rows (1 reaction per user)
            # Tie-break: random within same counts (good for early stage when counts are equal/0)
            order_sql = """
            ORDER BY
              (
                (SELECT COUNT(*) FROM feed_likes WHERE post_id = feed_posts.post_id) +
                (SELECT COUNT(*) FROM feed_reactions WHERE post_id = feed_posts.post_id)
              ) DESC,
              RANDOM()
            """
        else:
            order_sql = "ORDER BY published_at DESC"

        with self._connect() as con:
            total = con.execute(f"SELECT COUNT(*) FROM feed_posts {where}", params).fetchone()[0]
            cur = con.execute(
                f"""
                SELECT
                    post_id, owner_id, author_name, prompt, workflow_id, seed, aspect_ratio,
                    image_url, thumb_url, input_image_url, input_thumb_url,
                    source_image_id, input_source_image_id,
                    published_at, status
                FROM feed_posts
                {where}
                {order_sql}
                LIMIT ? OFFSET ?
                """,
                (*params, size_val, offset),
            )
            rows = cur.fetchall()

        items = [
            {
                "post_id": r[0],
                "owner_id": r[1],
                "author_name": r[2],
                "prompt": r[3],
                "workflow_id": r[4],
                "seed": r[5],
                "aspect_ratio": r[6],
                "image_url": r[7],
                "thumb_url": r[8],
                "input_image_url": r[9],
                "input_thumb_url": r[10],
                "source_image_id": r[11],
                "input_source_image_id": r[12],
                "published_at": r[13],
                "status": r[14],
            }
            for r in rows
        ]

        total_pages = (total + size_val - 1) // size_val
        return {"items": items, "page": page_val, "size": size_val, "total": total, "total_pages": total_pages}

    def like_toggle(self, post_id: str, liker_id: str) -> Dict[str, Any]:
        now = time.time()
        with self._connect() as con:
            # Keep a single "reaction" per user: legacy likes and reactions should not coexist.
            try:
                con.execute("DELETE FROM feed_reactions WHERE post_id = ? AND reactor_id = ?", (post_id, liker_id))
            except Exception:
                pass
            cur = con.execute(
                "SELECT 1 FROM feed_likes WHERE post_id = ? AND liker_id = ?",
                (post_id, liker_id),
            )
            exists = bool(cur.fetchone())
            if exists:
                con.execute("DELETE FROM feed_likes WHERE post_id = ? AND liker_id = ?", (post_id, liker_id))
                liked = False
            else:
                con.execute(
                    "INSERT OR IGNORE INTO feed_likes (post_id, liker_id, created_at) VALUES (?, ?, ?)",
                    (post_id, liker_id, now),
                )
                liked = True

            count = con.execute("SELECT COUNT(*) FROM feed_likes WHERE post_id = ?", (post_id,)).fetchone()[0]
        return {"liked": liked, "like_count": int(count)}

    def get_like_info(self, post_id: str, liker_id: str) -> Dict[str, Any]:
        with self._connect() as con:
            count = con.execute("SELECT COUNT(*) FROM feed_likes WHERE post_id = ?", (post_id,)).fetchone()[0]
            liked = bool(
                con.execute(
                    "SELECT 1 FROM feed_likes WHERE post_id = ? AND liker_id = ?",
                    (post_id, liker_id),
                ).fetchone()
            )
        return {"like_count": int(count), "liked_by_me": liked}

    def get_reaction_info(self, post_id: str, reactor_id: str) -> Dict[str, Any]:
        """
        Returns:
          - reactions: {"love": int, "like": int, "laugh": int, "wow": int, "fire": int}
          - my_reaction: one of reaction types or None

        Backward compatibility:
          - Legacy feed_likes are treated as "love".
          - If the user has a legacy like and no explicit reaction, my_reaction becomes "love".
        """
        reactions = {k: 0 for k in self.REACTION_TYPES}
        my_reaction: Optional[str] = None
        with self._connect() as con:
            # New reactions
            try:
                cur = con.execute(
                    "SELECT reaction, COUNT(*) FROM feed_reactions WHERE post_id = ? GROUP BY reaction",
                    (post_id,),
                )
                for r, cnt in cur.fetchall() or []:
                    if isinstance(r, str) and r in reactions:
                        reactions[r] = int(cnt or 0)
            except Exception:
                pass

            try:
                row = con.execute(
                    "SELECT reaction FROM feed_reactions WHERE post_id = ? AND reactor_id = ? LIMIT 1",
                    (post_id, reactor_id),
                ).fetchone()
                if row and isinstance(row[0], str) and row[0] in reactions:
                    my_reaction = row[0]
            except Exception:
                my_reaction = None

            # Legacy likes => love
            try:
                legacy_count = con.execute("SELECT COUNT(*) FROM feed_likes WHERE post_id = ?", (post_id,)).fetchone()[0]
                reactions["love"] = int(reactions.get("love", 0)) + int(legacy_count or 0)
                if my_reaction is None:
                    legacy_me = con.execute(
                        "SELECT 1 FROM feed_likes WHERE post_id = ? AND liker_id = ?",
                        (post_id, reactor_id),
                    ).fetchone()
                    if legacy_me:
                        my_reaction = "love"
            except Exception:
                pass

        return {"reactions": reactions, "my_reaction": my_reaction}

    def reaction_set(self, post_id: str, reactor_id: str, reaction: str) -> Dict[str, Any]:
        now = time.time()
        r = (reaction or "").strip().lower()
        if r not in self.REACTION_TYPES:
            raise ValueError("invalid_reaction")

        with self._connect() as con:
            # Ensure legacy like doesn't coexist with reactions
            try:
                con.execute("DELETE FROM feed_likes WHERE post_id = ? AND liker_id = ?", (post_id, reactor_id))
            except Exception:
                pass

            row = con.execute(
                "SELECT reaction FROM feed_reactions WHERE post_id = ? AND reactor_id = ? LIMIT 1",
                (post_id, reactor_id),
            ).fetchone()
            cur_reaction = row[0] if row and isinstance(row[0], str) else None

            if cur_reaction == r:
                con.execute("DELETE FROM feed_reactions WHERE post_id = ? AND reactor_id = ?", (post_id, reactor_id))
                my_reaction = None
            else:
                # One reaction per user per post
                con.execute(
                    "INSERT OR REPLACE INTO feed_reactions (post_id, reactor_id, reaction, created_at) VALUES (?, ?, ?, ?)",
                    (post_id, reactor_id, r, now),
                )
                my_reaction = r

        info = self.get_reaction_info(post_id, reactor_id)
        # Ensure my_reaction matches the action we just took (or None)
        info["my_reaction"] = my_reaction
        return info


