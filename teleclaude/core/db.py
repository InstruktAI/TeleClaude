"""Database manager for TeleClaude - handles session persistence and retrieval."""

import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional, TypedDict, cast

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.config import config

from .events import TeleClaudeEvents
from .models import MessageMetadata, Session, SessionAdapterMetadata
from .terminal_events import TerminalOutboxMetadata, TerminalOutboxPayload
from .voice_assignment import VoiceConfig

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


class HookOutboxRow(TypedDict):
    id: int
    session_id: str
    event_type: str
    payload: str
    attempt_count: int


class TerminalOutboxRow(TypedDict):
    id: int
    request_id: str
    event_type: str
    payload: str
    metadata: str
    attempt_count: int


class Db:
    """Database interface for terminal sessions and state management."""

    def __init__(self, db_path: str) -> None:
        """Initialize database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
        self._client: Optional["AdapterClient"] = None

    async def initialize(self) -> None:
        """Initialize database, create tables, and run migrations."""
        from teleclaude.core.migrations.runner import run_pending_migrations

        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Connect to database
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        # Load and execute base schema (CREATE TABLE IF NOT EXISTS - safe for existing DBs)
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        await self._db.executescript(schema_sql)
        await self._db.commit()

        # Run pending migrations (adds columns, migrates data)
        await run_pending_migrations(self._db)

        await self._normalize_adapter_metadata()

    async def _normalize_adapter_metadata(self) -> None:
        """Normalize adapter_metadata types (e.g., topic_id stored as string)."""
        cursor = await self.conn.execute("SELECT session_id, adapter_metadata FROM sessions")
        rows = await cursor.fetchall()
        if not rows:
            return

        any_updated = False
        for row in rows:
            raw = cast(object, row["adapter_metadata"])
            if not isinstance(raw, str) or not raw:
                continue
            try:
                parsed: object = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            tg = parsed.get("telegram")
            row_updated = False
            if isinstance(tg, dict):
                topic_id = tg.get("topic_id")
                if isinstance(topic_id, str) and topic_id.isdigit():
                    tg["topic_id"] = int(topic_id)
                    row_updated = True
            if row_updated:
                session_id = cast(str, row["session_id"])
                await self.conn.execute(
                    "UPDATE sessions SET adapter_metadata = ? WHERE session_id = ?",
                    (json.dumps(parsed), session_id),
                )
                any_updated = True

        if any_updated:
            await self.conn.commit()

    @property
    def conn(self) -> aiosqlite.Connection:
        """Get database connection, asserting it's initialized.

        Returns:
            Active database connection

        Raises:
            RuntimeError: If database not initialized
        """
        if self._db is None:
            raise RuntimeError("Database not initialized - call initialize() first")
        return self._db

    def set_client(self, client: "AdapterClient") -> None:
        """Wire database to AdapterClient for event emission.

        Args:
            client: AdapterClient instance to handle events through
        """
        self._client = client

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()

    async def create_session(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # Database insert requires all session fields
        self,
        computer_name: str,
        tmux_session_name: str,
        origin_adapter: str,
        title: str,
        adapter_metadata: Optional[SessionAdapterMetadata] = None,
        terminal_size: str = "160x80",
        working_directory: str = "~",
        description: Optional[str] = None,
        session_id: Optional[str] = None,
        working_slug: Optional[str] = None,
    ) -> Session:
        """Create a new session.

        Args:
            computer_name: Name of the computer
            tmux_session_name: Name of tmux session
            origin_adapter: Origin adapter type (e.g., "telegram", "redis")
            title: Optional session title
            adapter_metadata: Optional adapter-specific metadata
            terminal_size: Terminal dimensions (e.g., '80x24')
            working_directory: Initial working directory
            description: Optional description (for AI-to-AI sessions)
            session_id: Optional explicit session ID (for AI-to-AI cross-computer sessions)
            working_slug: Optional slug of work item this session is working on

        Returns:
            Created Session object
        """
        session_id = session_id or str(uuid.uuid4())
        now = datetime.now()

        session = Session(
            session_id=session_id,
            computer_name=computer_name,
            tmux_session_name=tmux_session_name,
            origin_adapter=origin_adapter,
            title=title or f"[{computer_name}] New session",
            adapter_metadata=adapter_metadata or SessionAdapterMetadata(),
            created_at=now,
            last_activity=now,
            terminal_size=terminal_size,
            working_directory=working_directory,
            description=description,
            working_slug=working_slug,
        )

        data = session.to_dict()
        await self.conn.execute(
            """
            INSERT INTO sessions (
                session_id, computer_name, title, tmux_session_name,
                origin_adapter, adapter_metadata, created_at,
                last_activity, terminal_size, working_directory, description,
                working_slug
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["session_id"],
                data["computer_name"],
                data["title"],
                data["tmux_session_name"],
                data["origin_adapter"],
                data["adapter_metadata"],
                data["created_at"],
                data["last_activity"],
                data["terminal_size"],
                data["working_directory"],
                data["description"],
                data["working_slug"],
            ),
        )
        await self.conn.commit()

        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID.

        Args:
            session_id: Session ID

        Returns:
            Session object or None if not found
        """
        cursor = await self.conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        row = await cursor.fetchone()

        if not row:
            return None

        return Session.from_dict(dict(row))

    async def get_session_by_field(self, field: str, value: object) -> Optional[Session]:
        """Get session by field value.

        Args:
            field: Session field name (e.g., "native_session_id", "output_message_id")
            value: Value to match

        Returns:
            Session object or None if not found
        """
        cursor = await self.conn.execute(_field_query(field), (value,))
        row = await cursor.fetchone()

        if not row:
            return None

        return Session.from_dict(dict(row))

    async def list_sessions(
        self,
        computer_name: Optional[str] = None,
        origin_adapter: Optional[str] = None,
    ) -> list[Session]:
        """List sessions with optional filters.

        Args:
            computer_name: Filter by computer name
            origin_adapter: Filter by origin adapter (telegram, redis, etc.)

        Returns:
            List of Session objects
        """
        query = "SELECT * FROM sessions WHERE 1=1"
        params: list[object] = []

        if computer_name:
            query += " AND computer_name = ?"
            params.append(computer_name)
        if origin_adapter:
            query += " AND origin_adapter = ?"
            params.append(origin_adapter)

        query += " ORDER BY last_activity DESC"

        cursor = await self.conn.execute(query, params)
        rows = await cursor.fetchall()

        return [Session.from_dict(dict(row)) for row in rows]

    async def update_session(self, session_id: str, **fields: object) -> None:
        """Update session fields and handle events.

        Args:
            session_id: Session ID
            **fields: Fields to update (title, status, terminal_size, etc.)
        """
        if not fields:
            return

        # Serialize adapter_metadata if it's a dict or dataclass
        if "adapter_metadata" in fields:
            metadata = fields["adapter_metadata"]
            if isinstance(metadata, dict):
                fields["adapter_metadata"] = json.dumps(metadata)
            elif hasattr(metadata, "__dataclass_fields__"):  # Check if it's a dataclass
                fields["adapter_metadata"] = json.dumps(asdict(metadata))  # type: ignore[call-overload,misc]  # Runtime checked for dataclass, asdict returns Any
            # else: assume it's already JSON string

        set_clause = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [session_id]

        await self.conn.execute(f"UPDATE sessions SET {set_clause} WHERE session_id = ?", values)
        await self.conn.commit()

        # Emit SESSION_UPDATED event (UI handlers will update channel titles)
        # Only handle if client is set (tests and standalone tools don't set client)
        if self._client:
            # Trust contract: session exists (we just updated it in db)
            session = await self.get_session(session_id)
            if session:  # Guard against race condition
                await self._client.handle_event(
                    TeleClaudeEvents.SESSION_UPDATED,
                    {"session_id": session_id, "updated_fields": fields},
                    MessageMetadata(adapter_type=session.origin_adapter),
                )

    async def update_last_activity(self, session_id: str) -> None:
        """Update last activity timestamp for session.

        Args:
            session_id: Session ID
        """
        await self.conn.execute(
            "UPDATE sessions SET last_activity = ? WHERE session_id = ?",
            (datetime.now().isoformat(), session_id),
        )
        await self.conn.commit()

    # State management functions (DB-backed via ux_state)

    async def get_output_message_id(self, session_id: str) -> Optional[str]:
        """Get output message ID for session.

        Args:
            session_id: Session identifier

        Returns:
            Message ID of output message, or None if not set
        """
        session = await self.get_session(session_id)
        return session.output_message_id if session else None

    async def set_output_message_id(self, session_id: str, message_id: Optional[str]) -> None:
        """Set output message ID for session.

        Args:
            session_id: Session identifier
            message_id: Message ID of the output message (or None to clear)
        """
        await self.update_session(session_id, output_message_id=message_id)

    async def get_pending_deletions(self, session_id: str) -> list[str]:
        """Get list of pending deletion message IDs for session.

        Args:
            session_id: Session identifier

        Returns:
            List of message IDs to delete (empty list if none)
        """
        cursor = await self.conn.execute(
            "SELECT message_id FROM pending_message_deletions WHERE session_id = ? AND deletion_type = 'user_input'",
            (session_id,),
        )
        rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]  # type: ignore[misc]  # sqlite rows are untyped

    async def add_pending_deletion(self, session_id: str, message_id: str) -> None:
        """Add message ID to pending deletions for session.

        When a process is running and messages are sent (user commands, feedback messages),
        these message IDs are tracked for deletion when the next accepted input is sent.

        Args:
            session_id: Session identifier
            message_id: Message ID to delete later
        """
        await self.conn.execute(
            "INSERT OR IGNORE INTO pending_message_deletions (session_id, message_id, deletion_type) VALUES (?, ?, 'user_input')",
            (session_id, message_id),
        )
        await self.conn.commit()

    async def clear_pending_deletions(self, session_id: str) -> None:
        """Clear all pending deletions for session.

        Should be called after deleting all pending messages, or when polling stops.

        Args:
            session_id: Session identifier
        """
        await self.conn.execute(
            "DELETE FROM pending_message_deletions WHERE session_id = ? AND deletion_type = 'user_input'",
            (session_id,),
        )
        await self.conn.commit()

    async def get_pending_feedback_deletions(self, session_id: str) -> list[str]:
        """Get list of pending feedback deletion message IDs for session.

        Args:
            session_id: Session identifier

        Returns:
            List of feedback message IDs to delete (empty list if none)
        """
        cursor = await self.conn.execute(
            "SELECT message_id FROM pending_message_deletions WHERE session_id = ? AND deletion_type = 'feedback'",
            (session_id,),
        )
        rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]  # type: ignore[misc]  # sqlite rows are untyped

    async def add_pending_feedback_deletion(self, session_id: str, message_id: str) -> None:
        """Add message ID to pending feedback deletions for session.

        Feedback messages are tracked separately from user input messages.
        They are cleaned up before sending new feedback.

        Args:
            session_id: Session identifier
            message_id: Feedback message ID to delete later
        """
        await self.conn.execute(
            "INSERT OR IGNORE INTO pending_message_deletions (session_id, message_id, deletion_type) VALUES (?, ?, 'feedback')",
            (session_id, message_id),
        )
        await self.conn.commit()

    async def clear_pending_feedback_deletions(self, session_id: str) -> None:
        """Clear all pending feedback deletions for session.

        Should be called after deleting all pending feedback messages.

        Args:
            session_id: Session identifier
        """
        await self.conn.execute(
            "DELETE FROM pending_message_deletions WHERE session_id = ? AND deletion_type = 'feedback'",
            (session_id,),
        )
        await self.conn.commit()

    async def delete_session(self, session_id: str) -> None:
        """Delete session and handle event.

        Args:
            session_id: Session ID
        """
        # Get session before deleting for event emission
        _ = await self.get_session(session_id)

        await self.conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        await self.conn.commit()
        logger.debug("Deleted session %s from database", session_id[:8])

    async def count_sessions(self, computer_name: Optional[str] = None) -> int:
        """Count sessions with optional filters.

        Args:
            computer_name: Filter by computer name

        Returns:
            Number of sessions
        """
        query = "SELECT COUNT(*) as count FROM sessions WHERE 1=1"
        params: list[object] = []

        if computer_name:
            query += " AND computer_name = ?"
            params.append(computer_name)

        cursor = await self.conn.execute(query, params)
        row = await cursor.fetchone()
        count: int = int(row["count"]) if row else 0  # type: ignore[misc]  # Row access is Any from aiosqlite
        return count

    async def get_sessions_by_adapter_metadata(
        self, adapter_type: str, metadata_key: str, metadata_value: object
    ) -> list[Session]:
        """Get sessions by adapter metadata field.

        Finds sessions that HAVE the specified adapter metadata, regardless of
        which adapter was the origin. This enables observer adapters to find
        sessions they're observing even when another adapter was the initiator.

        Args:
            adapter_type: Adapter type whose metadata to search
            metadata_key: JSON key to search in adapter_metadata
            metadata_value: Value to match

        Returns:
            List of matching sessions
        """
        # SQLite JSON functions - adapter_metadata is nested: {adapter_type: {metadata_key: value}}
        # NOTE: We do NOT filter by origin_adapter - observer adapters need to find
        # sessions where they have metadata even if they weren't the initiator
        query = f"""
            SELECT * FROM sessions
            WHERE json_extract(adapter_metadata, '$.{adapter_type}.{metadata_key}') = ?
            """
        params: list[object] = [metadata_value]
        if isinstance(metadata_value, int):
            query = f"""
                SELECT * FROM sessions
                WHERE json_extract(adapter_metadata, '$.{adapter_type}.{metadata_key}') = ?
                   OR json_extract(adapter_metadata, '$.{adapter_type}.{metadata_key}') = ?
                """
            params.append(str(metadata_value))

        cursor = await self.conn.execute(query, params)
        rows = await cursor.fetchall()
        return [Session.from_dict(dict(row)) for row in rows]

    async def get_sessions_by_title_pattern(self, pattern: str) -> list[Session]:
        """Get sessions where title starts with the given pattern.

        Args:
            pattern: Title pattern to match (e.g., "$macbook > $")

        Returns:
            List of matching sessions
        """
        cursor = await self.conn.execute(
            """
            SELECT * FROM sessions
            WHERE title LIKE ?
            ORDER BY created_at DESC
            """,
            (f"{pattern}%",),
        )
        rows = await cursor.fetchall()
        return [Session.from_dict(dict(row)) for row in rows]

    async def get_all_sessions(self) -> list[Session]:
        """Get all sessions ordered by last activity."""
        cursor = await self.conn.execute("SELECT * FROM sessions ORDER BY last_activity DESC")
        rows = await cursor.fetchall()
        return [Session.from_dict(dict(row)) for row in rows]

    async def get_active_sessions(self) -> list[Session]:
        """Get all sessions ordered by last activity."""
        cursor = await self.conn.execute("SELECT * FROM sessions ORDER BY last_activity DESC")
        rows = await cursor.fetchall()
        all_sessions = [Session.from_dict(dict(row)) for row in rows]

        return all_sessions

    async def set_notification_flag(self, session_id: str, value: bool) -> None:
        """Set notification_sent flag in UX state.

        Used by Agent notification hook to signal that notification was sent.

        Args:
            session_id: Session ID
            value: Flag value (True = notification sent, False = cleared)
        """
        await self.update_session(session_id, notification_sent=1 if value else 0)

    async def clear_notification_flag(self, session_id: str) -> None:
        """Clear notification_sent flag in UX state.

        Called by polling coordinator when output resumes to re-enable notifications.

        Args:
            session_id: Session ID
        """
        await self.update_session(session_id, notification_sent=0)

    async def get_notification_flag(self, session_id: str) -> bool:
        """Get notification_sent flag from UX state.

        Args:
            session_id: Session ID

        Returns:
            True if notification was sent, False otherwise
        """
        session = await self.get_session(session_id)
        return bool(session.notification_sent) if session else False

    async def get_system_setting(self, key: str) -> Optional[str]:
        """Get system setting value by key.

        Args:
            key: Setting key

        Returns:
            Setting value or None if not found
        """
        cursor = await self.conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        value: str = str(row[0]) if row else ""  # type: ignore[misc]  # Row access is Any from aiosqlite
        return value if row else None

    async def set_system_setting(self, key: str, value: str) -> None:
        """Set system setting value (upsert).

        Args:
            key: Setting key
            value: Setting value
        """
        await self.conn.execute(
            """
            INSERT INTO system_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )
        await self.conn.commit()

    # Voice assignment methods

    async def assign_voice(self, voice_id: str, voice: VoiceConfig) -> None:
        """Assign a voice keyed by ID (either teleclaude_session_id or native_session_id).

        Args:
            voice_id: Either teleclaude session ID or Agent session ID
            voice: VoiceConfig to assign
        """
        await self.conn.execute(
            """
            INSERT INTO voice_assignments (id, voice_name, elevenlabs_id, macos_voice, openai_voice)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                voice_name = excluded.voice_name,
                elevenlabs_id = excluded.elevenlabs_id,
                macos_voice = excluded.macos_voice,
                openai_voice = excluded.openai_voice,
                assigned_at = CURRENT_TIMESTAMP
            """,
            (
                voice_id,
                voice.name,
                voice.elevenlabs_id,
                voice.macos_voice,
                voice.openai_voice,
            ),
        )
        await self.conn.commit()
        logger.debug("Assigned voice '%s' to %s", voice.name, voice_id[:8])

    async def get_voice(self, voice_id: str) -> Optional[VoiceConfig]:
        """Get voice assignment by ID.

        Args:
            voice_id: Either teleclaude session ID or Agent session ID

        Returns:
            VoiceConfig or None if no voice assigned
        """
        cursor = await self.conn.execute(
            "SELECT voice_name, elevenlabs_id, macos_voice, openai_voice FROM voice_assignments WHERE id = ?",
            (voice_id,),
        )
        row = await cursor.fetchone()

        if not row:
            return None

        return VoiceConfig(
            name=row["voice_name"],  # type: ignore[misc]  # Row access is Any from aiosqlite
            elevenlabs_id=row["elevenlabs_id"] or "",  # type: ignore[misc]  # Row access is Any from aiosqlite
            macos_voice=row["macos_voice"] or "",  # type: ignore[misc]  # Row access is Any from aiosqlite
            openai_voice=row["openai_voice"] or "",  # type: ignore[misc]  # Row access is Any from aiosqlite
        )

    async def cleanup_stale_voice_assignments(self, max_age_days: int = 7) -> int:
        """Delete voice assignments older than max_age_days.

        Args:
            max_age_days: Maximum age in days before cleanup (default: 7)

        Returns:
            Number of records deleted
        """
        cursor = await self.conn.execute(
            """DELETE FROM voice_assignments
            WHERE assigned_at < datetime('now', ? || ' days')""",
            (f"-{max_age_days}",),
        )
        await self.conn.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info(
                "Cleaned up %d stale voice assignments (older than %d days)",
                deleted,
                max_age_days,
            )
        return deleted

    # Agent availability methods (for next-machine workflow)

    async def get_agent_availability(self, agent: str) -> dict[str, bool | str | None] | None:
        """Get agent availability status.

        Args:
            agent: Agent name (e.g., "claude", "gemini", "codex")

        Returns:
            Dict with 'available', 'unavailable_until', 'reason' or None if not found
        """
        cursor = await self.conn.execute(
            "SELECT available, unavailable_until, reason FROM agent_availability WHERE agent = ?",
            (agent,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "available": bool(row["available"]),  # type: ignore[misc]  # Row access is Any from aiosqlite
            "unavailable_until": row["unavailable_until"],  # type: ignore[misc]
            "reason": row["reason"],  # type: ignore[misc]
        }

    async def mark_agent_unavailable(self, agent: str, unavailable_until: str, reason: str) -> None:
        """Mark an agent as unavailable until a specified time.

        Args:
            agent: Agent name (e.g., "claude", "gemini", "codex")
            unavailable_until: ISO timestamp when agent becomes available again
            reason: Reason for unavailability (e.g., "quota_exhausted", "rate_limited")
        """
        await self.conn.execute(
            """INSERT INTO agent_availability (agent, available, unavailable_until, reason)
               VALUES (?, 0, ?, ?)
               ON CONFLICT(agent) DO UPDATE SET
                 available = 0, unavailable_until = excluded.unavailable_until, reason = excluded.reason""",
            (agent, unavailable_until, reason),
        )
        await self.conn.commit()
        logger.info("Marked agent %s unavailable until %s (%s)", agent, unavailable_until, reason)

    async def clear_expired_agent_availability(self) -> int:
        """Reset agents whose unavailable_until time has passed.

        Returns:
            Number of agents reset to available
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self.conn.execute(
            """UPDATE agent_availability
               SET available = 1, unavailable_until = NULL, reason = NULL
               WHERE unavailable_until IS NOT NULL AND unavailable_until < ?""",
            (now,),
        )
        await self.conn.commit()
        cleared = cursor.rowcount
        if cleared > 0:
            logger.info("Cleared availability for %d agents (TTL expired)", cleared)
        return cleared

    async def enqueue_hook_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, object],  # noqa: loose-dict - Hook payload is dynamic JSON
    ) -> int:
        """Persist a hook event in the outbox for durable delivery."""
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload)
        cursor = await self.conn.execute(
            """
            INSERT INTO hook_outbox (
                session_id, event_type, payload, created_at, next_attempt_at, attempt_count
            ) VALUES (?, ?, ?, ?, ?, 0)
            """,
            (session_id, event_type, payload_json, now, now),
        )
        await self.conn.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("Failed to insert hook outbox row")
        return int(row_id)

    async def fetch_hook_outbox_batch(
        self,
        now_iso: str,
        limit: int,
        lock_cutoff_iso: str,
    ) -> list[HookOutboxRow]:
        """Fetch a batch of due hook events."""
        cursor = await self.conn.execute(
            """
            SELECT id, session_id, event_type, payload, attempt_count
            FROM hook_outbox
            WHERE delivered_at IS NULL
              AND next_attempt_at <= ?
              AND (locked_at IS NULL OR locked_at <= ?)
            ORDER BY created_at
            LIMIT ?
            """,
            (now_iso, lock_cutoff_iso, limit),
        )
        rows = await cursor.fetchall()
        typed_rows: list[HookOutboxRow] = []
        for row in rows:
            row_id = cast(int, row["id"])
            session_id = cast(str, row["session_id"])
            event_type = cast(str, row["event_type"])
            payload = cast(str, row["payload"])
            attempt_count = cast(int, row["attempt_count"])
            typed_rows.append(
                HookOutboxRow(
                    id=row_id,
                    session_id=session_id,
                    event_type=event_type,
                    payload=payload,
                    attempt_count=attempt_count,
                )
            )
        return typed_rows

    async def claim_hook_outbox(self, row_id: int, now_iso: str, lock_cutoff_iso: str) -> bool:
        """Claim a hook outbox row for processing."""
        cursor = await self.conn.execute(
            """
            UPDATE hook_outbox
            SET locked_at = ?
            WHERE id = ?
              AND delivered_at IS NULL
              AND (locked_at IS NULL OR locked_at <= ?)
            """,
            (now_iso, row_id, lock_cutoff_iso),
        )
        await self.conn.commit()
        return cursor.rowcount == 1

    async def mark_hook_outbox_delivered(self, row_id: int, error: str | None = None) -> None:
        """Mark a hook outbox row delivered (optionally capturing last error)."""
        now = datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            UPDATE hook_outbox
            SET delivered_at = ?, last_error = ?, locked_at = NULL
            WHERE id = ?
            """,
            (now, error, row_id),
        )
        await self.conn.commit()

    async def mark_hook_outbox_failed(
        self,
        row_id: int,
        attempt_count: int,
        next_attempt_at: str,
        error: str,
    ) -> None:
        """Record a hook outbox failure and schedule a retry."""
        await self.conn.execute(
            """
            UPDATE hook_outbox
            SET attempt_count = ?, next_attempt_at = ?, last_error = ?, locked_at = NULL
            WHERE id = ?
            """,
            (attempt_count, next_attempt_at, error, row_id),
        )
        await self.conn.commit()

    async def enqueue_terminal_event(
        self,
        request_id: str,
        event_type: str,
        payload: TerminalOutboxPayload,
        metadata: TerminalOutboxMetadata,
    ) -> int:
        """Persist a terminal-origin event in the outbox for durable delivery."""
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload)
        metadata_json = json.dumps(metadata)
        cursor = await self.conn.execute(
            """
            INSERT INTO terminal_outbox (
                request_id, event_type, payload, metadata, created_at, next_attempt_at, attempt_count
            ) VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (request_id, event_type, payload_json, metadata_json, now, now),
        )
        await self.conn.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("Failed to insert terminal outbox row")
        return int(row_id)

    async def fetch_terminal_outbox_batch(
        self,
        now_iso: str,
        limit: int,
        lock_cutoff_iso: str,
    ) -> list[TerminalOutboxRow]:
        """Fetch a batch of due terminal outbox events."""
        cursor = await self.conn.execute(
            """
            SELECT id, request_id, event_type, payload, metadata, attempt_count
            FROM terminal_outbox
            WHERE delivered_at IS NULL
              AND next_attempt_at <= ?
              AND (locked_at IS NULL OR locked_at <= ?)
            ORDER BY created_at
            LIMIT ?
            """,
            (now_iso, lock_cutoff_iso, limit),
        )
        rows = await cursor.fetchall()
        typed_rows: list[TerminalOutboxRow] = []
        for row in rows:
            row_id = cast(int, row["id"])
            request_id = cast(str, row["request_id"])
            event_type = cast(str, row["event_type"])
            payload = cast(str, row["payload"])
            metadata = cast(str, row["metadata"])
            attempt_count = cast(int, row["attempt_count"])
            typed_rows.append(
                TerminalOutboxRow(
                    id=row_id,
                    request_id=request_id,
                    event_type=event_type,
                    payload=payload,
                    metadata=metadata,
                    attempt_count=attempt_count,
                )
            )
        return typed_rows

    async def claim_terminal_outbox(self, row_id: int, now_iso: str, lock_cutoff_iso: str) -> bool:
        """Claim a terminal outbox row for processing."""
        cursor = await self.conn.execute(
            """
            UPDATE terminal_outbox
            SET locked_at = ?
            WHERE id = ?
              AND delivered_at IS NULL
              AND (locked_at IS NULL OR locked_at <= ?)
            """,
            (now_iso, row_id, lock_cutoff_iso),
        )
        await self.conn.commit()
        return cursor.rowcount == 1

    async def mark_terminal_outbox_delivered(
        self,
        row_id: int,
        response_json: str,
        error: str | None = None,
    ) -> None:
        """Mark a terminal outbox row delivered with response payload."""
        now = datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            UPDATE terminal_outbox
            SET delivered_at = ?, last_error = ?, locked_at = NULL, response = ?
            WHERE id = ?
            """,
            (now, error, response_json, row_id),
        )
        await self.conn.commit()

    async def mark_terminal_outbox_failed(
        self,
        row_id: int,
        attempt_count: int,
        next_attempt_at: str,
        error: str,
    ) -> None:
        """Record a terminal outbox failure and schedule a retry."""
        await self.conn.execute(
            """
            UPDATE terminal_outbox
            SET attempt_count = ?, next_attempt_at = ?, last_error = ?, locked_at = NULL
            WHERE id = ?
            """,
            (attempt_count, next_attempt_at, error, row_id),
        )
        await self.conn.commit()


def _field_query(field: str) -> str:
    """Build query to find session by direct column value."""
    return f"SELECT session_id FROM sessions WHERE {field} = ? ORDER BY last_activity DESC LIMIT 1"


def _fetch_session_id_sync(db_path: str, query: str, value: object) -> str | None:
    conn = sqlite3.connect(db_path, timeout=1.0)
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
        try:
            cursor = conn.execute(query, (value,))
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        row = cast(tuple[object, ...] | None, cursor.fetchone())
        return str(row[0]) if row else None
    finally:
        conn.close()


def get_session_id_by_field_sync(db_path: str, field: str, value: object) -> str | None:
    """Sync helper for lookups in standalone scripts (hook receiver, telec)."""
    return _fetch_session_id_sync(db_path, _field_query(field), value)


def get_session_id_by_tmux_name_sync(db_path: str, tmux_name: str) -> str | None:
    """Sync helper to find session_id by tmux session name."""
    query = "SELECT session_id FROM sessions WHERE tmux_session_name = ? ORDER BY last_activity DESC LIMIT 1"
    return _fetch_session_id_sync(db_path, query, tmux_name)


# Module-level singleton instance (initialized on first import)
db = Db(config.database.path)
