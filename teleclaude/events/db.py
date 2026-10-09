"""Event DB — SQLite storage for incident records, correlation state, handled-event records and signal pipeline data."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

from teleclaude.core.db.connection_factory import create_sync_db_engine
from teleclaude.events.catalog import StateStanding
from teleclaude.events.db_migrations import HANDLED_EVENTS_TABLE, INHERITED_WINDOW_COLUMN, migrate_forward
from teleclaude.paths import EVENTS_DB_PATH

if TYPE_CHECKING:
    from teleclaude.events.signal.db import SignalDB


_CREATE_CORRELATION_TABLE = f"""
CREATE TABLE IF NOT EXISTS correlation_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    home TEXT NOT NULL,
    subject TEXT,
    window_start TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    {INHERITED_WINDOW_COLUMN} INTEGER NOT NULL DEFAULT 0
);
"""
_CREATE_EPISODE_TABLE = """
CREATE TABLE IF NOT EXISTS correlation_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detection TEXT NOT NULL,
    subject TEXT NOT NULL,
    home TEXT NOT NULL,
    started_at TEXT NOT NULL,
    failing_types TEXT NOT NULL DEFAULT '[]',
    UNIQUE(detection, subject, home)
);
"""
_CREATE_INCIDENTS_TABLE = """
CREATE TABLE IF NOT EXISTS incidents (
    family TEXT NOT NULL,
    subject TEXT NOT NULL,
    home TEXT NOT NULL,
    standing TEXT NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    broken_since TEXT NOT NULL,
    PRIMARY KEY (family, subject, home)
) WITHOUT ROWID;
"""
_CREATE_INCIDENT_RECIPIENTS_TABLE = """
CREATE TABLE IF NOT EXISTS incident_recipients (
    family TEXT NOT NULL,
    subject TEXT NOT NULL,
    home TEXT NOT NULL,
    recipient TEXT NOT NULL,
    told_standing TEXT,
    PRIMARY KEY (family, subject, home, recipient)
) WITHOUT ROWID;
"""
_SELECT_INCIDENT_SQL = (
    "SELECT standing, event_type, occurred_at, broken_since FROM incidents "
    "WHERE family = ? AND subject = ? AND home = ?"
)
_SELECT_INCIDENT_RECIPIENTS_SQL = (
    "SELECT recipient, told_standing FROM incident_recipients WHERE family = ? AND subject = ? AND home = ?"
)
_INSERT_INCIDENT_SQL = (
    "INSERT OR IGNORE INTO incidents (family, subject, home, standing, event_type, occurred_at, broken_since) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)
_UPDATE_INCIDENT_SQL = (
    "UPDATE incidents SET standing = ?, event_type = ?, occurred_at = ?, broken_since = ? "
    "WHERE family = ? AND subject = ? AND home = ?"
)
_UPSERT_INCIDENT_RECIPIENT_SQL = (
    "INSERT INTO incident_recipients (family, subject, home, recipient, told_standing) VALUES (?, ?, ?, ?, ?) "
    "ON CONFLICT (family, subject, home, recipient) DO UPDATE SET told_standing = excluded.told_standing"
)
_INSERT_INCIDENT_RECIPIENT_SQL = (
    "INSERT OR IGNORE INTO incident_recipients (family, subject, home, recipient, told_standing) "
    "VALUES (?, ?, ?, ?, NULL)"
)
_DELETE_INCIDENT_SQL = "DELETE FROM incidents WHERE family = ? AND subject = ? AND home = ?"
_DELETE_INCIDENT_RECIPIENTS_SQL = "DELETE FROM incident_recipients WHERE family = ? AND subject = ? AND home = ?"
_CREATE_HANDLED_EVENTS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {HANDLED_EVENTS_TABLE} (
    consumer TEXT NOT NULL,
    event_id TEXT NOT NULL,
    handled_at TEXT NOT NULL,
    PRIMARY KEY (consumer, event_id)
) WITHOUT ROWID;
"""
_CREATE_HANDLED_EVENTS_INDEX = (
    f"CREATE INDEX IF NOT EXISTS idx_handled_events_handled_at ON {HANDLED_EVENTS_TABLE} (handled_at);"
)
_SELECT_HANDLED_EVENT_SQL = f"SELECT 1 FROM {HANDLED_EVENTS_TABLE} WHERE consumer = ? AND event_id = ?"
_INSERT_HANDLED_EVENT_SQL = (
    f"INSERT OR IGNORE INTO {HANDLED_EVENTS_TABLE} (consumer, event_id, handled_at) VALUES (?, ?, ?)"
)
_DELETE_HANDLED_EVENTS_SQL = f"DELETE FROM {HANDLED_EVENTS_TABLE} WHERE handled_at < ?"
_INSERT_CORRELATION_WINDOW_SQL = (
    "INSERT INTO correlation_windows (event_type, home, subject, window_start, count) VALUES (?, ?, ?, ?, 1)"
)
_SELECT_CORRELATION_COUNT_SQL = (
    "SELECT COALESCE(SUM(count), 0) FROM correlation_windows WHERE event_type = ? AND window_start >= ?"
)
_CORRELATION_ADMITTED_ONLY_FILTER_SQL = f" AND {INHERITED_WINDOW_COLUMN} = 0"
_CORRELATION_HOME_FILTER_SQL = " AND home = ?"
_CORRELATION_SUBJECT_FILTER_SQL = " AND subject = ?"
_INSERT_EPISODE_SQL = (
    "INSERT OR IGNORE INTO correlation_episodes (detection, subject, home, started_at, failing_types) "
    "VALUES (?, ?, ?, ?, ?)"
)
_SELECT_EPISODES_SQL = (
    "SELECT id, detection, subject, home, started_at, failing_types FROM correlation_episodes ORDER BY id"
)
_SELECT_EPISODE_SQL = (
    "SELECT id, detection, subject, home, started_at, failing_types FROM correlation_episodes "
    "WHERE detection = ? AND subject = ? AND home = ?"
)
_UPDATE_EPISODE_FAILING_TYPES_SQL = "UPDATE correlation_episodes SET failing_types = ? WHERE id = ?"
_DELETE_EPISODE_SQL = "DELETE FROM correlation_episodes WHERE id = ?"


_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_correlation_windows_home ON correlation_windows (event_type, home, window_start);",
    "CREATE INDEX IF NOT EXISTS idx_correlation_windows_home_subject ON correlation_windows (event_type, home, subject, window_start);",
]


class EpisodeDetection(StrEnum):
    """The correlation detections whose episodes are kept open until they are reported over."""

    BURST = "burst"
    FAILURE_CASCADE = "failure_cascade"
    ENTITY_DEGRADATION = "entity_degradation"


@dataclass(frozen=True)
class CorrelationEpisode:
    """One open correlation episode: what was detected, about which subject and home, and since when."""

    id: int
    detection: EpisodeDetection
    subject: str
    home: str
    started_at: datetime
    failing_types: tuple[str, ...]


def _episode_from_row(row: aiosqlite.Row) -> CorrelationEpisode:
    """Convert a stored episode row into its typed record."""
    return CorrelationEpisode(
        id=row[0],
        detection=EpisodeDetection(row[1]),
        subject=row[2],
        home=row[3],
        started_at=datetime.fromisoformat(row[4]),
        failing_types=tuple(json.loads(row[5])),
    )


@dataclass(frozen=True)
class IncidentKey:
    """The identity of a matter: a lifecycle family's state of one thing, the subject within its origin."""

    family: str
    subject: str
    home: str


@dataclass(frozen=True)
class IncidentRecord:
    """An open matter: its current standing with the type and time of the event that brought it there.

    `broken_since` is when the thing became broken. `told` holds the recipients of the current episode — the
    administrators selected when the matter opened, failed again or recovered — each with the standing last
    told, or none while they await their first message.
    """

    key: IncidentKey
    standing: StateStanding
    event_type: str
    occurred_at: datetime
    broken_since: datetime
    told: Mapping[str, StateStanding | None]


def _signal_db_class() -> type[SignalDB]:
    """Load the signal DB wrapper lazily to avoid import cycles."""
    cls: type[SignalDB] = import_module("teleclaude.events.signal.db").SignalDB
    return cls


class EventDB:
    """SQLite-backed storage for incident records, correlation state and handled-event records."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        # Resolve EVENTS_DB_PATH at call time, not import time, so test fixtures
        # that monkeypatch the module-level constant take effect.
        resolved = db_path if db_path is not None else EVENTS_DB_PATH
        self._db_path = Path(resolved).expanduser()
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initialize the SQLite database and all event-related tables."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        bootstrap_engine = create_sync_db_engine(self._db_path)
        bootstrap_engine.dispose()
        self._conn = await aiosqlite.connect(str(self._db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute(_CREATE_CORRELATION_TABLE)
        await self._conn.execute(_CREATE_EPISODE_TABLE)
        await self._conn.execute(_CREATE_INCIDENTS_TABLE)
        await self._conn.execute(_CREATE_INCIDENT_RECIPIENTS_TABLE)
        await migrate_forward(self._conn)
        await self._conn.execute(_CREATE_HANDLED_EVENTS_TABLE)
        await self._conn.execute(_CREATE_HANDLED_EVENTS_INDEX)
        for idx_sql in _CREATE_INDEXES:
            await self._conn.execute(idx_sql)
        await self._conn.commit()
        # Initialize signal pipeline tables after the shared engine bootstraps the DB file.
        await _signal_db_class()(self._conn).init()

    def is_initialized(self) -> bool:
        """Return whether the SQLite connection has been opened."""
        return self._conn is not None

    @property
    def signal(self) -> SignalDB:
        """Return a signal-pipeline DB wrapper sharing the same SQLite connection."""
        if self._conn is None:
            raise RuntimeError("EventDB not initialized. Call initialize() first.")
        return _signal_db_class()(self._conn)

    async def close(self) -> None:
        """Close the underlying SQLite connection and clear the factory cache."""
        global _event_db_instance
        if self._conn:
            await self._conn.close()
            self._conn = None
        if _event_db_instance is self:
            _event_db_instance = None

    def _db(self) -> aiosqlite.Connection:
        """Return the initialized SQLite connection."""
        if self._conn is None:
            raise RuntimeError("EventDB not initialized. Call initialize() first.")
        return self._conn

    # --- Handled-event records ---

    async def has_handled_event(self, consumer: str, event_id: str) -> bool:
        """Return whether the consumer has a record of handling the event id."""
        cursor = await self._db().execute(_SELECT_HANDLED_EVENT_SQL, (consumer, event_id))
        return (await cursor.fetchone()) is not None

    async def record_handled_event(self, consumer: str, event_id: str, handled_at: datetime) -> None:
        """Record that the consumer handled the event id; recording again changes nothing."""
        await self._db().execute(_INSERT_HANDLED_EVENT_SQL, (consumer, event_id, handled_at.isoformat()))
        await self._db().commit()

    async def prune_handled_events(self, *, older_than: datetime) -> int:
        """Delete handled-event records older than the cutoff and return how many were deleted."""
        cursor = await self._db().execute(_DELETE_HANDLED_EVENTS_SQL, (older_than.isoformat(),))
        await self._db().commit()
        return max(cursor.rowcount, 0)

    # --- Correlation window methods ---

    async def increment_correlation_window(self, event_type: str, home: str, subject: str | None, ts: datetime) -> None:
        """Insert one correlation-window bucket entry for an event occurrence."""
        await self._db().execute(
            _INSERT_CORRELATION_WINDOW_SQL,
            (event_type, home, subject, ts.isoformat()),
        )
        await self._db().commit()

    async def get_correlation_count(
        self,
        event_type: str,
        since: datetime,
        *,
        include_inherited: bool,
        home: str | None = None,
        subject: str | None = None,
    ) -> int:
        """Return the total correlation count for a type since the given time, narrowed to a home and a subject.

        Rows counted before correlation acted only on its own computer's events are inherited; a count
        that decides a detection leaves them out, and one that decides an episode is over keeps them.
        """
        sql = _SELECT_CORRELATION_COUNT_SQL
        if not include_inherited:
            sql += _CORRELATION_ADMITTED_ONLY_FILTER_SQL
        params: list[str] = [event_type, since.isoformat()]
        if home is not None:
            sql += _CORRELATION_HOME_FILTER_SQL
            params.append(home)
        if subject is not None:
            sql += _CORRELATION_SUBJECT_FILTER_SQL
            params.append(subject)
        cursor = await self._db().execute(sql, params)
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    # --- Correlation episode methods ---

    async def open_episode(
        self, detection: EpisodeDetection, subject: str, home: str, started_at: datetime, failing_types: list[str]
    ) -> bool:
        """Open the episode for a detection, subject and home; return whether it was newly opened."""
        cursor = await self._db().execute(
            _INSERT_EPISODE_SQL,
            (detection.value, subject, home, started_at.isoformat(), json.dumps(failing_types)),
        )
        await self._db().commit()
        return cursor.rowcount > 0

    async def get_episode(self, detection: EpisodeDetection, subject: str, home: str) -> CorrelationEpisode | None:
        """Return the open episode for a detection, subject and home, if one is open."""
        cursor = await self._db().execute(_SELECT_EPISODE_SQL, (detection.value, subject, home))
        row = await cursor.fetchone()
        return _episode_from_row(row) if row else None

    async def list_open_episodes(self) -> list[CorrelationEpisode]:
        """Return every open episode, oldest first."""
        cursor = await self._db().execute(_SELECT_EPISODES_SQL)
        return [_episode_from_row(row) for row in await cursor.fetchall()]

    async def set_episode_failing_types(self, episode_id: int, failing_types: list[str]) -> None:
        """Record the failing types that put a degradation episode over its threshold."""
        await self._db().execute(_UPDATE_EPISODE_FAILING_TYPES_SQL, (json.dumps(failing_types), episode_id))
        await self._db().commit()

    async def close_episode(self, episode_id: int) -> None:
        """Close an open episode."""
        await self._db().execute(_DELETE_EPISODE_SQL, (episode_id,))
        await self._db().commit()

    async def prune_correlation_windows(self, older_than: datetime) -> None:
        """Delete correlation-window rows older than the given timestamp."""
        await self._db().execute(
            "DELETE FROM correlation_windows WHERE window_start < ?",
            (older_than.isoformat(),),
        )
        await self._db().commit()

    # --- Incident methods ---

    async def get_incident(self, key: IncidentKey) -> IncidentRecord | None:
        """Return the open matter for a key with the standing each recipient was last told, if one is open."""
        params = (key.family, key.subject, key.home)
        cursor = await self._db().execute(_SELECT_INCIDENT_SQL, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        recipients_cursor = await self._db().execute(_SELECT_INCIDENT_RECIPIENTS_SQL, params)
        told = {
            recipient: StateStanding(standing) if standing is not None else None
            for recipient, standing in await recipients_cursor.fetchall()
        }
        return IncidentRecord(
            key=key,
            standing=StateStanding(row[0]),
            event_type=row[1],
            occurred_at=datetime.fromisoformat(row[2]),
            broken_since=datetime.fromisoformat(row[3]),
            told=told,
        )

    async def open_incident(
        self, key: IncidentKey, event_type: str, occurred_at: datetime, recipients: Sequence[str]
    ) -> None:
        """Open the matter as failing, broken since the event that reported it, with the recipients it will tell.

        Opening an open matter changes nothing.
        """
        await self._db().execute(
            _INSERT_INCIDENT_SQL,
            (
                key.family,
                key.subject,
                key.home,
                StateStanding.FAILING.value,
                event_type,
                occurred_at.isoformat(),
                occurred_at.isoformat(),
            ),
        )
        await self._register_incident_recipients(key, recipients)
        await self._db().commit()

    async def set_incident_standing(
        self,
        key: IncidentKey,
        standing: StateStanding,
        event_type: str,
        occurred_at: datetime,
        broken_since: datetime,
        recipients: Sequence[str] = (),
    ) -> None:
        """Record the matter's new standing with the type and time of the event that brought it there.

        A matter that fails again starts a new episode: what recipients were told before it belongs to
        the earlier episode, so their progress is cleared. The given recipients become recipients of the
        transition; a recipient already recorded keeps what it was told.
        """
        params = (key.family, key.subject, key.home)
        if standing is StateStanding.FAILING:
            await self._db().execute(_DELETE_INCIDENT_RECIPIENTS_SQL, params)
        await self._register_incident_recipients(key, recipients)
        await self._db().execute(
            _UPDATE_INCIDENT_SQL,
            (standing.value, event_type, occurred_at.isoformat(), broken_since.isoformat(), *params),
        )
        await self._db().commit()

    async def _register_incident_recipients(self, key: IncidentKey, recipients: Sequence[str]) -> None:
        """Make the recipients part of the matter's current episode, awaiting its first message."""
        for recipient in recipients:
            await self._db().execute(_INSERT_INCIDENT_RECIPIENT_SQL, (key.family, key.subject, key.home, recipient))

    async def mark_incident_recipient_told(self, key: IncidentKey, recipient: str, standing: StateStanding) -> None:
        """Record the standing a recipient was last told; marking again replaces it."""
        await self._db().execute(
            _UPSERT_INCIDENT_RECIPIENT_SQL, (key.family, key.subject, key.home, recipient, standing.value)
        )
        await self._db().commit()

    async def delete_incident(self, key: IncidentKey) -> None:
        """Remove the matter and what each recipient was last told."""
        params = (key.family, key.subject, key.home)
        await self._db().execute(_DELETE_INCIDENT_RECIPIENTS_SQL, params)
        await self._db().execute(_DELETE_INCIDENT_SQL, params)
        await self._db().commit()


_event_db_instance: EventDB | None = None
_event_db_lock = asyncio.Lock()


async def get_event_db() -> EventDB:
    """Return the process-wide initialized EventDB, creating it on first call.

    Daemon, API, and CLI consumers all reach the events DB through this factory.
    Memoized per process; safe under concurrent first-callers via the lock.
    A cached instance whose connection has been closed is replaced rather than
    handed out — ``EventDB.close`` clears this cache, but a defensive
    ``is_initialized()`` check covers external lifecycle paths.
    """
    global _event_db_instance
    cached = _event_db_instance
    if cached is None or not cached.is_initialized():
        async with _event_db_lock:
            cached = _event_db_instance
            if cached is None or not cached.is_initialized():
                inst = EventDB()
                await inst.initialize()
                _event_db_instance = inst
                return inst
    return cached
