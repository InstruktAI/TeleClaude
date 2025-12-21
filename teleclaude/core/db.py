"""Database manager for TeleClaude - handles session persistence and retrieval."""

import json
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.config import config

from . import ux_state
from .events import TeleClaudeEvents
from .models import MessageMetadata, Session, SessionAdapterMetadata
from .ux_state import SessionUXState, update_session_ux_state
from .voice_assignment import VoiceConfig

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


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
        """Initialize database and create tables (greenfield - no migrations)."""
        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Connect to database
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        # Load and execute clean schema (no migrations!)
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        await self._db.executescript(schema_sql)
        await self._db.commit()

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
        logger.info("Database wired to AdapterClient for event emission")

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
            closed=False,
            created_at=now,
            last_activity=now,
            terminal_size=terminal_size,
            working_directory=working_directory,
            description=description,
        )

        data = session.to_dict()
        await self.conn.execute(
            """
            INSERT INTO sessions (
                session_id, computer_name, title, tmux_session_name,
                origin_adapter, adapter_metadata, closed, created_at,
                last_activity, terminal_size, working_directory, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["session_id"],
                data["computer_name"],
                data["title"],
                data["tmux_session_name"],
                data["origin_adapter"],
                data["adapter_metadata"],
                data["closed"],
                data["created_at"],
                data["last_activity"],
                data["terminal_size"],
                data["working_directory"],
                data["description"],
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

    async def get_session_by_ux_state(self, field: str, value: object) -> Optional[Session]:
        """Get session by ux_state field value.

        Args:
            field: UX state field name (e.g., "native_session_id", "output_message_id")
            value: Value to match

        Returns:
            Session object or None if not found
        """
        cursor = await self.conn.execute(
            f"SELECT * FROM sessions WHERE json_extract(ux_state, '$.{field}') = ?",
            (value,),
        )
        row = await cursor.fetchone()

        if not row:
            return None

        return Session.from_dict(dict(row))

    async def list_sessions(
        self,
        computer_name: Optional[str] = None,
        closed: Optional[bool] = None,
        origin_adapter: Optional[str] = None,
    ) -> list[Session]:
        """List sessions with optional filters.

        Args:
            computer_name: Filter by computer name
            closed: Filter by closed status (False = active, True = closed, None = all)
            origin_adapter: Filter by origin adapter (telegram, redis, etc.)

        Returns:
            List of Session objects
        """
        query = "SELECT * FROM sessions WHERE 1=1"
        params: list[object] = []

        if computer_name:
            query += " AND computer_name = ?"
            params.append(computer_name)
        if closed is not None:
            query += " AND closed = ?"
            params.append(1 if closed else 0)
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
        ux_state = await self.get_ux_state(session_id)
        return ux_state.output_message_id

    async def set_output_message_id(self, session_id: str, message_id: Optional[str]) -> None:
        """Set output message ID for session.

        Args:
            session_id: Session identifier
            message_id: Message ID of the output message (or None to clear)
        """
        await self.update_ux_state(session_id, output_message_id=message_id)

    async def get_pending_deletions(self, session_id: str) -> list[str]:
        """Get list of pending deletion message IDs for session.

        Args:
            session_id: Session identifier

        Returns:
            List of message IDs to delete (empty list if none)
        """
        ux_state = await self.get_ux_state(session_id)
        return ux_state.pending_deletions

    async def add_pending_deletion(self, session_id: str, message_id: str) -> None:
        """Add message ID to pending deletions for session.

        When a process is running and messages are sent (user commands, feedback messages),
        these message IDs are tracked for deletion when the next accepted input is sent.

        Args:
            session_id: Session identifier
            message_id: Message ID to delete later
        """
        current = await self.get_pending_deletions(session_id)
        current.append(message_id)

        await self.update_ux_state(session_id, pending_deletions=current)

    async def clear_pending_deletions(self, session_id: str) -> None:
        """Clear all pending deletions for session.

        Should be called after deleting all pending messages, or when polling stops.

        Args:
            session_id: Session identifier
        """

        await self.update_ux_state(session_id, pending_deletions=[])

    async def get_pending_feedback_deletions(self, session_id: str) -> list[str]:
        """Get list of pending feedback deletion message IDs for session.

        Args:
            session_id: Session identifier

        Returns:
            List of feedback message IDs to delete (empty list if none)
        """
        ux_state_data = await self.get_ux_state(session_id)
        return ux_state_data.pending_feedback_deletions

    async def add_pending_feedback_deletion(self, session_id: str, message_id: str) -> None:
        """Add message ID to pending feedback deletions for session.

        Feedback messages are tracked separately from user input messages.
        They are cleaned up before sending new feedback.

        Args:
            session_id: Session identifier
            message_id: Feedback message ID to delete later
        """
        current = await self.get_pending_feedback_deletions(session_id)
        current.append(message_id)

        await self.update_ux_state(session_id, pending_feedback_deletions=current)

    async def clear_pending_feedback_deletions(self, session_id: str) -> None:
        """Clear all pending feedback deletions for session.

        Should be called after deleting all pending feedback messages.

        Args:
            session_id: Session identifier
        """

        await self.update_ux_state(session_id, pending_feedback_deletions=[])

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

    async def count_sessions(self, computer_name: Optional[str] = None, closed: Optional[bool] = None) -> int:
        """Count sessions with optional filters.

        Args:
            computer_name: Filter by computer name
            closed: Filter by closed status (False = active, True = closed, None = all)

        Returns:
            Number of sessions
        """
        query = "SELECT COUNT(*) as count FROM sessions WHERE 1=1"
        params: list[object] = []

        if computer_name:
            query += " AND computer_name = ?"
            params.append(computer_name)
        if closed is not None:
            query += " AND closed = ?"
            params.append(1 if closed else 0)

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
        cursor = await self.conn.execute(
            f"""
            SELECT * FROM sessions
            WHERE json_extract(adapter_metadata, '$.{adapter_type}.{metadata_key}') = ?
            """,
            (metadata_value,),
        )
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

    async def get_all_sessions(self, closed: Optional[bool] = None) -> list[Session]:
        """Get all sessions with optional closed filter.

        Args:
            closed: Filter by closed status (False = active, True = closed, None = all)

        Returns:
            List of sessions ordered by last activity
        """
        if closed is None:
            query = "SELECT * FROM sessions ORDER BY last_activity DESC"
            params: tuple[int, ...] = ()
        else:
            query = "SELECT * FROM sessions WHERE closed = ? ORDER BY last_activity DESC"
            params = (1 if closed else 0,)

        cursor = await self.conn.execute(query, params)
        rows = await cursor.fetchall()
        return [Session.from_dict(dict(row)) for row in rows]

    async def get_active_sessions(self) -> list[Session]:
        """Get all open sessions (closed=False).

        Returns:
            List of open sessions
        """
        cursor = await self.conn.execute(
            """
            SELECT * FROM sessions
            WHERE closed = 0
            ORDER BY last_activity DESC
            """
        )
        rows = await cursor.fetchall()
        all_sessions = [Session.from_dict(dict(row)) for row in rows]

        return all_sessions

    async def get_ux_state(self, session_id: str) -> SessionUXState:
        """Get UX state for session.

        Args:
            session_id: Session ID

        Returns:
            SessionUXState (with defaults if not found)
        """
        return await ux_state.get_session_ux_state(self.conn, session_id)

    async def update_ux_state(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # UX state has many optional fields
        self,
        session_id: str,
        *,
        output_message_id: Optional[str] | object = ux_state._UNSET,
        pending_deletions: list[str] | object = ux_state._UNSET,
        pending_feedback_deletions: list[str] | object = ux_state._UNSET,
        notification_sent: bool | object = ux_state._UNSET,
        native_session_id: Optional[str] | object = ux_state._UNSET,
        native_log_file: Optional[str] | object = ux_state._UNSET,
        active_agent: Optional[str] | object = ux_state._UNSET,
        thinking_mode: Optional[str] | object = ux_state._UNSET,
    ) -> None:
        """Update UX state for session (merges with existing).

        Args:
            session_id: Session ID
            output_message_id: Output message ID (optional)
        pending_deletions: List of user input message IDs pending deletion (optional)
        pending_feedback_deletions: List of feedback message IDs pending deletion (optional)
        notification_sent: Whether Agent notification was sent (optional)
            native_session_id: Native agent session ID (optional)
            native_log_file: Path to native agent log file (optional)
            active_agent: Name of the active agent (optional)
        """
        await update_session_ux_state(
            self.conn,
            session_id,
            output_message_id=output_message_id,
            pending_deletions=pending_deletions,
            pending_feedback_deletions=pending_feedback_deletions,
            notification_sent=notification_sent,
            native_session_id=native_session_id,
            native_log_file=native_log_file,
            active_agent=active_agent,
            thinking_mode=thinking_mode,
        )

    async def set_notification_flag(self, session_id: str, value: bool) -> None:
        """Set notification_sent flag in UX state.

        Used by Agent notification hook to signal that notification was sent.

        Args:
            session_id: Session ID
            value: Flag value (True = notification sent, False = cleared)
        """
        await self.update_ux_state(session_id, notification_sent=value)

    async def clear_notification_flag(self, session_id: str) -> None:
        """Clear notification_sent flag in UX state.

        Called by polling coordinator when output resumes to re-enable notifications.

        Args:
            session_id: Session ID
        """
        await self.update_ux_state(session_id, notification_sent=False)

    async def get_notification_flag(self, session_id: str) -> bool:
        """Get notification_sent flag from UX state.

        Args:
            session_id: Session ID

        Returns:
            True if notification was sent, False otherwise
        """
        ux_state_data = await self.get_ux_state(session_id)
        return ux_state_data.notification_sent

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


# Module-level singleton instance (initialized on first import)
db = Db(config.database.path)
