"""Event DB — SQLite storage for notification projections and signal pipeline data."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, cast

import aiosqlite

from teleclaude.core.models import JsonDict
from teleclaude.events.envelope import EventEnvelope

if TYPE_CHECKING:
    from teleclaude.events.signal.db import SignalDB


class NotificationRow(TypedDict):
    """Stored notification projection row returned from SQLite."""

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


class QuarantinedEventRow(TypedDict):
    """Stored quarantined-event row returned from SQLite."""

    id: int
    event_type: str
    source: str
    received_at: str
    envelope_json: str
    trust_flags: str
    reviewed: int


class NotificationListFilters(TypedDict, total=False):
    """Supported notification filters for list queries."""

    level: int | None
    domain: str | None
    human_status: str | None
    agent_status: str | None
    visibility: str | None
    since: str | None


_NOTIFICATION_LIST_FILTERS: dict[str, str] = {
    "level": "level >= ?",
    "domain": "domain = ?",
    "human_status": "human_status = ?",
    "agent_status": "agent_status = ?",
    "visibility": "visibility = ?",
    "since": "created_at >= ?",
}


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

_CREATE_QUARANTINED_TABLE = """
CREATE TABLE IF NOT EXISTS quarantined_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    received_at TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    trust_flags TEXT NOT NULL DEFAULT '[]',
    reviewed INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_CORRELATION_TABLE = """
CREATE TABLE IF NOT EXISTS correlation_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    entity TEXT,
    window_start TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1
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
    "CREATE INDEX IF NOT EXISTS idx_quarantined_reviewed ON quarantined_events (reviewed, received_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_correlation_windows ON correlation_windows (event_type, entity, window_start);",
]


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()


def _row_to_dict(row: aiosqlite.Row) -> NotificationRow:
    """Convert an aiosqlite row into the typed notification row mapping."""
    return dict(row)  # type: ignore[return-value]


def _signal_db_class() -> type[SignalDB]:
    """Load the signal DB wrapper lazily to avoid import cycles."""
    return import_module("teleclaude.events.signal.db").SignalDB


class EventDB:
    """SQLite-backed storage for event notifications and correlation state."""

    def __init__(self, db_path: str | Path = "~/.teleclaude/events.db") -> None:
        self._db_path = Path(db_path).expanduser()
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Initialize the SQLite database and all event-related tables."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute(_CREATE_TABLE)
        await self._conn.execute(_CREATE_QUARANTINED_TABLE)
        await self._conn.execute(_CREATE_CORRELATION_TABLE)
        for idx_sql in _CREATE_INDEXES:
            await self._conn.execute(idx_sql)
        await self._conn.commit()
        # Initialize signal pipeline tables (same DB, WAL already active)
        await _signal_db_class()(self._conn).init()

    @property
    def signal(self) -> SignalDB:
        """Return a signal-pipeline DB wrapper sharing the same SQLite connection."""
        if self._conn is None:
            raise RuntimeError("EventDB not initialized. Call init() first.")
        return _signal_db_class()(self._conn)

    async def close(self) -> None:
        """Close the underlying SQLite connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    def _db(self) -> aiosqlite.Connection:
        """Return the initialized SQLite connection."""
        if self._conn is None:
            raise RuntimeError("EventDB not initialized. Call init() first.")
        return self._conn

    async def insert_notification(self, envelope: EventEnvelope) -> int:
        """Insert a new notification projection row and return its database id."""
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
        return cursor.lastrowid or 0

    async def get_notification(self, notification_id: int) -> NotificationRow | None:
        """Return a notification row by database id."""
        cursor = await self._db().execute("SELECT * FROM notifications WHERE id = ?", (notification_id,))
        row = await cursor.fetchone()
        return _row_to_dict(row) if row else None

    async def idempotency_key_exists(self, key: str) -> bool:
        """Return whether the given idempotency key already exists."""
        cursor = await self._db().execute("SELECT 1 FROM notifications WHERE idempotency_key = ?", (key,))
        return (await cursor.fetchone()) is not None

    async def list_notifications(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> list[NotificationRow]:
        """List notification rows matching optional filters."""
        conditions: list[str] = []
        params: list[Any] = []
        unexpected_filters = sorted(set(filters) - set(_NOTIFICATION_LIST_FILTERS))
        if unexpected_filters:
            unexpected = ", ".join(unexpected_filters)
            raise TypeError(f"Unsupported notification filters: {unexpected}")
        for key, sql in _NOTIFICATION_LIST_FILTERS.items():
            value = filters.get(key)
            if value is not None:
                conditions.append(sql)
                params.append(value)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.extend([limit, offset])
        cursor = await self._db().execute(
            f"SELECT * FROM notifications {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    async def update_human_status(self, notification_id: int, status: str) -> bool:
        """Update the human workflow status for a notification."""
        now = _now_iso()
        seen_at = now if status == "seen" else None
        cursor = await self._db().execute(
            "UPDATE notifications SET human_status = ?, seen_at = ?, updated_at = ? WHERE id = ?",
            (status, seen_at, now, notification_id),
        )
        await self._db().commit()
        return cursor.rowcount > 0

    async def update_agent_status(self, notification_id: int, status: str, agent_id: str) -> bool:
        """Update the agent workflow status for a notification."""
        now = _now_iso()
        if status == "claimed":
            cursor = await self._db().execute(
                "UPDATE notifications SET agent_status = ?, agent_id = ?, claimed_at = ?, updated_at = ? WHERE id = ?",
                (status, agent_id, now, now, notification_id),
            )
        else:
            cursor = await self._db().execute(
                "UPDATE notifications SET agent_status = ?, agent_id = ?, updated_at = ? WHERE id = ?",
                (status, agent_id, now, notification_id),
            )
        await self._db().commit()
        return cursor.rowcount > 0

    async def resolve_notification(self, notification_id: int, resolution: JsonDict) -> bool:
        """Mark a notification as resolved and store its resolution payload."""
        now = _now_iso()
        cursor = await self._db().execute(
            (
                "UPDATE notifications SET agent_status = 'resolved', resolution = ?, "
                "resolved_at = ?, updated_at = ? WHERE id = ?"
            ),
            (json.dumps(resolution), now, now, notification_id),
        )
        await self._db().commit()
        return cursor.rowcount > 0

    async def upsert_by_idempotency_key(self, envelope: EventEnvelope) -> tuple[int, bool]:
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

        notification_id = await self.insert_notification(envelope)
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
        notification_id: int,
        description: str,
        payload: JsonDict,
        reset_human_status: bool = False,
    ) -> bool:
        """Update the projected description and payload for an existing notification."""
        now = _now_iso()
        if reset_human_status:
            cursor = await self._db().execute(
                (
                    "UPDATE notifications SET description = ?, payload = ?, "
                    "human_status = 'unseen', updated_at = ? WHERE id = ?"
                ),
                (description, json.dumps(payload), now, notification_id),
            )
        else:
            cursor = await self._db().execute(
                "UPDATE notifications SET description = ?, payload = ?, updated_at = ? WHERE id = ?",
                (description, json.dumps(payload), now, notification_id),
            )
        await self._db().commit()
        return cursor.rowcount > 0

    # --- Quarantine methods ---

    async def quarantine_event(self, envelope: EventEnvelope, flags: list[str]) -> int:
        """Persist an event in the quarantine table and return its row id."""
        cursor = await self._db().execute(
            """
            INSERT INTO quarantined_events (event_type, source, received_at, envelope_json, trust_flags, reviewed)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                envelope.event,
                envelope.source,
                envelope.timestamp.isoformat(),
                envelope.model_dump_json(),
                json.dumps(flags),
            ),
        )
        await self._db().commit()
        return cursor.lastrowid or 0

    async def list_quarantined(self, reviewed: bool | None = None, limit: int = 50) -> list[QuarantinedEventRow]:
        """List quarantined events, optionally filtered by review state."""
        params: list[Any] = []
        where = ""
        if reviewed is not None:
            where = "WHERE reviewed = ?"
            params.append(1 if reviewed else 0)
        params.append(limit)
        cursor = await self._db().execute(
            f"SELECT * FROM quarantined_events {where} ORDER BY received_at DESC LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        return [cast(QuarantinedEventRow, dict(r)) for r in rows]

    # --- Enrichment query helpers ---

    async def count_events_by_entity(
        self,
        entity: str,
        event_type: str,
        since: datetime | None = None,
        payload_filter: JsonDict | None = None,
    ) -> int:
        """Count notification events for an entity, with optional time and payload filters."""
        params: list[Any] = [entity, event_type]
        where = "entity = ? AND event_type = ?"
        if since is not None:
            where += " AND created_at >= ?"
            params.append(since.isoformat())
        if payload_filter:
            for key, value in payload_filter.items():
                where += f" AND json_extract(payload, '$.{key}') = ?"
                params.append(value)
        cursor = await self._db().execute(
            f"SELECT COUNT(*) FROM notifications WHERE {where}",
            params,
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def get_latest_event_payload(self, entity: str, event_type: str) -> JsonDict | None:
        """Return the latest stored payload for an entity and event type."""
        cursor = await self._db().execute(
            "SELECT payload FROM notifications WHERE entity = ? AND event_type = ? ORDER BY created_at DESC LIMIT 1",
            (entity, event_type),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return cast(JsonDict, json.loads(row[0]))

    # --- Correlation window methods ---

    async def increment_correlation_window(self, event_type: str, entity: str | None, ts: datetime) -> None:
        """Insert one correlation-window bucket entry for an event occurrence."""
        await self._db().execute(
            "INSERT INTO correlation_windows (event_type, entity, window_start, count) VALUES (?, ?, ?, 1)",
            (event_type, entity, ts.isoformat()),
        )
        await self._db().commit()

    async def get_correlation_count(self, event_type: str, entity: str | None, since: datetime) -> int:
        """Return the total correlation count for an event since the given time."""
        if entity is None:
            cursor = await self._db().execute(
                "SELECT COALESCE(SUM(count), 0) FROM correlation_windows WHERE event_type = ? AND window_start >= ?",
                (event_type, since.isoformat()),
            )
        else:
            cursor = await self._db().execute(
                (
                    "SELECT COALESCE(SUM(count), 0) FROM correlation_windows "
                    "WHERE event_type = ? AND entity = ? AND window_start >= ?"
                ),
                (event_type, entity, since.isoformat()),
            )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def prune_correlation_windows(self, older_than: datetime) -> None:
        """Delete correlation-window rows older than the given timestamp."""
        await self._db().execute(
            "DELETE FROM correlation_windows WHERE window_start < ?",
            (older_than.isoformat(),),
        )
        await self._db().commit()
