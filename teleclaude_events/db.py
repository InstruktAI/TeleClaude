"""Event DB — SQLite storage for notification projections."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

import aiosqlite

from teleclaude_events.catalog import EventSchema
from teleclaude_events.envelope import EventEnvelope


class NotificationRow(TypedDict):
    id: int
    event_type: str
    version: int
    source: str
    level: int
    domain: str
    visibility: str
    entity: str | None
    description: str
    payload: str
    idempotency_key: str | None
    human_status: str
    agent_status: str
    agent_id: str | None
    resolution: str | None
    created_at: str
    updated_at: str
    seen_at: str | None
    claimed_at: str | None
    resolved_at: str | None


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL,
    level INTEGER NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'local',
    entity TEXT,
    description TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT,
    human_status TEXT NOT NULL DEFAULT 'unseen',
    agent_status TEXT NOT NULL DEFAULT 'none',
    agent_id TEXT,
    resolution TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    seen_at TEXT,
    claimed_at TEXT,
    resolved_at TEXT,
    UNIQUE(idempotency_key)
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_notifications_event_type ON notifications (event_type);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_level ON notifications (level);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_domain ON notifications (domain);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_human_status ON notifications (human_status);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_agent_status ON notifications (agent_status);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_visibility ON notifications (visibility);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications (created_at DESC);",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: aiosqlite.Row) -> NotificationRow:
    return dict(row)  # type: ignore[return-value]


class EventDB:
    def __init__(self, db_path: str | Path = "~/.teleclaude/events.db") -> None:
        self._db_path = Path(db_path).expanduser()
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute(_CREATE_TABLE)
        for idx_sql in _CREATE_INDEXES:
            await self._conn.execute(idx_sql)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("EventDB not initialized. Call init() first.")
        return self._conn

    async def insert_notification(self, envelope: EventEnvelope, schema: EventSchema) -> int:
        now = _now_iso()
        cursor = await self._db().execute(
            """
            INSERT INTO notifications
              (event_type, version, source, level, domain, visibility, entity, description,
               payload, idempotency_key, human_status, agent_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unseen', 'none', ?, ?)
            """,
            (
                envelope.event,
                envelope.version,
                envelope.source,
                int(envelope.level),
                envelope.domain,
                envelope.visibility.value,
                envelope.entity,
                envelope.description,
                json.dumps(envelope.payload),
                envelope.idempotency_key,
                now,
                now,
            ),
        )
        await self._db().commit()
        return cursor.lastrowid or 0  # type: ignore[union-attr]

    async def get_notification(self, id: int) -> NotificationRow | None:
        cursor = await self._db().execute("SELECT * FROM notifications WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return _row_to_dict(row) if row else None

    async def idempotency_key_exists(self, key: str) -> bool:
        cursor = await self._db().execute("SELECT 1 FROM notifications WHERE idempotency_key = ?", (key,))
        return (await cursor.fetchone()) is not None

    async def list_notifications(
        self,
        *,
        level: int | None = None,
        domain: str | None = None,
        human_status: str | None = None,
        agent_status: str | None = None,
        visibility: str | None = None,
        since: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NotificationRow]:
        conditions: list[str] = []
        params: list[Any] = []

        if level is not None:
            conditions.append("level >= ?")
            params.append(level)
        if domain is not None:
            conditions.append("domain = ?")
            params.append(domain)
        if human_status is not None:
            conditions.append("human_status = ?")
            params.append(human_status)
        if agent_status is not None:
            conditions.append("agent_status = ?")
            params.append(agent_status)
        if visibility is not None:
            conditions.append("visibility = ?")
            params.append(visibility)
        if since is not None:
            conditions.append("created_at >= ?")
            params.append(since)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.extend([limit, offset])
        cursor = await self._db().execute(
            f"SELECT * FROM notifications {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    async def update_human_status(self, id: int, status: str) -> bool:
        now = _now_iso()
        seen_at = now if status == "seen" else None
        cursor = await self._db().execute(
            "UPDATE notifications SET human_status = ?, seen_at = ?, updated_at = ? WHERE id = ?",
            (status, seen_at, now, id),
        )
        await self._db().commit()
        return cursor.rowcount > 0  # type: ignore[union-attr]

    async def update_agent_status(self, id: int, status: str, agent_id: str) -> bool:
        now = _now_iso()
        if status == "claimed":
            cursor = await self._db().execute(
                "UPDATE notifications SET agent_status = ?, agent_id = ?, claimed_at = ?, updated_at = ? WHERE id = ?",
                (status, agent_id, now, now, id),
            )
        else:
            cursor = await self._db().execute(
                "UPDATE notifications SET agent_status = ?, agent_id = ?, updated_at = ? WHERE id = ?",
                (status, agent_id, now, id),
            )
        await self._db().commit()
        return cursor.rowcount > 0  # type: ignore[union-attr]

    async def resolve_notification(self, id: int, resolution: dict[str, Any]) -> bool:
        now = _now_iso()
        cursor = await self._db().execute(
            "UPDATE notifications SET agent_status = 'resolved', resolution = ?, resolved_at = ?, updated_at = ? WHERE id = ?",
            (json.dumps(resolution), now, now, id),
        )
        await self._db().commit()
        return cursor.rowcount > 0  # type: ignore[union-attr]

    async def upsert_by_idempotency_key(self, envelope: EventEnvelope, schema: EventSchema) -> tuple[int, bool]:
        """Insert or update notification. Returns (notification_id, was_created)."""
        now = _now_iso()
        if envelope.idempotency_key:
            cursor = await self._db().execute(
                "SELECT id FROM notifications WHERE idempotency_key = ?",
                (envelope.idempotency_key,),
            )
            existing = await cursor.fetchone()
            if existing:
                notification_id: int = existing[0]
                await self._db().execute(
                    "UPDATE notifications SET description = ?, payload = ?, updated_at = ? WHERE id = ?",
                    (envelope.description, json.dumps(envelope.payload), now, notification_id),
                )
                await self._db().commit()
                return notification_id, False

        notification_id = await self.insert_notification(envelope, schema)
        return notification_id, True

    async def find_by_group_key(self, group_key_field: str, group_key_value: str) -> NotificationRow | None:
        """Find most recent notification by a payload group key value."""
        cursor = await self._db().execute(
            "SELECT * FROM notifications WHERE json_extract(payload, ?) = ? ORDER BY created_at DESC LIMIT 1",
            (f"$.{group_key_field}", group_key_value),
        )
        row = await cursor.fetchone()
        return _row_to_dict(row) if row else None

    async def update_notification_fields(
        self,
        id: int,
        description: str,
        payload: dict[str, Any],
        reset_human_status: bool = False,
    ) -> bool:
        now = _now_iso()
        if reset_human_status:
            cursor = await self._db().execute(
                "UPDATE notifications SET description = ?, payload = ?, human_status = 'unseen', updated_at = ? WHERE id = ?",
                (description, json.dumps(payload), now, id),
            )
        else:
            cursor = await self._db().execute(
                "UPDATE notifications SET description = ?, payload = ?, updated_at = ? WHERE id = ?",
                (description, json.dumps(payload), now, id),
            )
        await self._db().commit()
        return cursor.rowcount > 0  # type: ignore[union-attr]
