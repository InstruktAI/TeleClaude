"""Signal database — CRUD for signal_items, signal_clusters, signal_syntheses."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

_CREATE_SIGNAL_ITEMS = """
CREATE TABLE IF NOT EXISTS signal_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT UNIQUE NOT NULL,
    source_id TEXT NOT NULL,
    item_url TEXT NOT NULL,
    raw_title TEXT,
    summary TEXT,
    tags TEXT,
    embedding TEXT,
    fetched_at TEXT NOT NULL,
    cluster_id INTEGER,
    FOREIGN KEY (cluster_id) REFERENCES signal_clusters(id)
);
"""

_CREATE_SIGNAL_CLUSTERS = """
CREATE TABLE IF NOT EXISTS signal_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_key TEXT UNIQUE NOT NULL,
    tags TEXT,
    is_burst INTEGER NOT NULL DEFAULT 0,
    is_novel INTEGER NOT NULL DEFAULT 0,
    summary TEXT,
    member_count INTEGER NOT NULL DEFAULT 0,
    formed_at TEXT NOT NULL
);
"""

_CREATE_SIGNAL_SYNTHESES = """
CREATE TABLE IF NOT EXISTS signal_syntheses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id INTEGER NOT NULL,
    artifact TEXT NOT NULL,
    produced_at TEXT NOT NULL,
    FOREIGN KEY (cluster_id) REFERENCES signal_clusters(id)
);
"""

_SIGNAL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_signal_items_idempotency ON signal_items (idempotency_key);",
    "CREATE INDEX IF NOT EXISTS idx_signal_items_cluster ON signal_items (cluster_id);",
    "CREATE INDEX IF NOT EXISTS idx_signal_items_fetched ON signal_items (fetched_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_signal_clusters_key ON signal_clusters (cluster_key);",
    "CREATE INDEX IF NOT EXISTS idx_signal_clusters_formed ON signal_clusters (formed_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_signal_syntheses_cluster ON signal_syntheses (cluster_id);",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SignalDB:
    """CRUD wrapper for signal tables. Expects an already-initialized aiosqlite connection."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def init(self) -> None:
        """Create signal tables if they don't exist."""
        await self._conn.execute(_CREATE_SIGNAL_CLUSTERS)
        await self._conn.execute(_CREATE_SIGNAL_ITEMS)
        await self._conn.execute(_CREATE_SIGNAL_SYNTHESES)
        for idx_sql in _SIGNAL_INDEXES:
            await self._conn.execute(idx_sql)
        await self._conn.commit()

    async def insert_signal_item(self, payload: dict[str, object]) -> int:
        cursor = await self._conn.execute(
            """
            INSERT OR IGNORE INTO signal_items
              (idempotency_key, source_id, item_url, raw_title, summary, tags, embedding, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(payload.get("idempotency_key", "")),
                str(payload.get("source_id", "")),
                str(payload.get("item_url", "")),
                str(payload.get("raw_title", "")) if payload.get("raw_title") else None,
                str(payload.get("summary", "")) if payload.get("summary") else None,
                ",".join(str(t) for t in payload.get("tags", [])) if payload.get("tags") else None,  # type: ignore[arg-type]
                json.dumps(payload["embedding"]) if payload.get("embedding") else None,
                str(payload.get("fetched_at", _now_iso())),
            ),
        )
        await self._conn.commit()
        return cursor.lastrowid or 0

    async def signal_item_exists(self, idempotency_key: str) -> bool:
        cursor = await self._conn.execute(
            "SELECT 1 FROM signal_items WHERE idempotency_key = ?", (idempotency_key,)
        )
        return (await cursor.fetchone()) is not None

    async def get_unclustered_items(self, since: datetime, limit: int = 500) -> list[dict[str, object]]:
        cursor = await self._conn.execute(
            """
            SELECT id, idempotency_key, source_id, item_url, raw_title, summary, tags, embedding, fetched_at
            FROM signal_items
            WHERE cluster_id IS NULL AND fetched_at >= ?
            ORDER BY fetched_at ASC
            LIMIT ?
            """,
            (since.isoformat(), limit),
        )
        rows = await cursor.fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            d = dict(row)
            if d.get("tags"):
                d["tags"] = [t.strip() for t in str(d["tags"]).split(",") if t.strip()]
            else:
                d["tags"] = []
            if d.get("embedding"):
                try:
                    d["embedding"] = json.loads(str(d["embedding"]))
                except (ValueError, TypeError):
                    d["embedding"] = None
            result.append(d)
        return result

    async def insert_cluster(
        self,
        cluster_key: str,
        tags: list[str],
        is_burst: bool,
        is_novel: bool,
        summary: str,
        member_ids: list[int],
    ) -> int:
        cursor = await self._conn.execute(
            """
            INSERT OR IGNORE INTO signal_clusters
              (cluster_key, tags, is_burst, is_novel, summary, member_count, formed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cluster_key,
                ",".join(tags),
                1 if is_burst else 0,
                1 if is_novel else 0,
                summary,
                len(member_ids),
                _now_iso(),
            ),
        )
        await self._conn.commit()
        return cursor.lastrowid or 0

    async def assign_items_to_cluster(self, item_ids: list[int], cluster_id: int) -> None:
        placeholders = ",".join("?" * len(item_ids))
        await self._conn.execute(
            f"UPDATE signal_items SET cluster_id = ? WHERE id IN ({placeholders})",
            [cluster_id, *item_ids],
        )
        await self._conn.commit()

    async def get_cluster(self, cluster_id: int) -> dict[str, object] | None:
        cursor = await self._conn.execute(
            "SELECT * FROM signal_clusters WHERE id = ?", (cluster_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def get_cluster_members(self, cluster_id: int, limit: int = 10) -> list[dict[str, object]]:
        cursor = await self._conn.execute(
            """
            SELECT id, idempotency_key, source_id, item_url, raw_title, summary, tags, fetched_at
            FROM signal_items WHERE cluster_id = ?
            ORDER BY fetched_at ASC LIMIT ?
            """,
            (cluster_id, limit),
        )
        rows = await cursor.fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            d = dict(row)
            if d.get("tags"):
                d["tags"] = [t.strip() for t in str(d["tags"]).split(",") if t.strip()]
            else:
                d["tags"] = []
            result.append(d)
        return result

    async def insert_synthesis(self, cluster_id: int, artifact: dict[str, object]) -> int:
        cursor = await self._conn.execute(
            "INSERT INTO signal_syntheses (cluster_id, artifact, produced_at) VALUES (?, ?, ?)",
            (cluster_id, json.dumps(artifact), _now_iso()),
        )
        await self._conn.commit()
        return cursor.lastrowid or 0

    async def get_recent_cluster_tags(self, hours: int = 24) -> list[str]:
        from datetime import timedelta

        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        cursor = await self._conn.execute(
            "SELECT tags FROM signal_clusters WHERE formed_at >= ? AND tags IS NOT NULL",
            (since,),
        )
        rows = await cursor.fetchall()
        all_tags: list[str] = []
        for row in rows:
            tags_str = row[0]
            if tags_str:
                all_tags.extend(t.strip() for t in str(tags_str).split(",") if t.strip())
        return all_tags

    async def get_signal_counts(self) -> dict[str, int]:
        items_cur = await self._conn.execute("SELECT COUNT(*) FROM signal_items")
        clusters_cur = await self._conn.execute("SELECT COUNT(*) FROM signal_clusters")
        synths_cur = await self._conn.execute("SELECT COUNT(*) FROM signal_syntheses")
        pending_cur = await self._conn.execute("SELECT COUNT(*) FROM signal_items WHERE cluster_id IS NULL")
        items_row = await items_cur.fetchone()
        clusters_row = await clusters_cur.fetchone()
        synths_row = await synths_cur.fetchone()
        pending_row = await pending_cur.fetchone()
        return {
            "items": int(items_row[0]) if items_row else 0,
            "clusters": int(clusters_row[0]) if clusters_row else 0,
            "syntheses": int(synths_row[0]) if synths_row else 0,
            "pending": int(pending_row[0]) if pending_row else 0,
        }

    async def get_last_ingest_time(self) -> str | None:
        cursor = await self._conn.execute(
            "SELECT MAX(fetched_at) FROM signal_items"
        )
        row = await cursor.fetchone()
        return str(row[0]) if row and row[0] else None
