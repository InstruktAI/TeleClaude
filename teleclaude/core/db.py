"""Database manager for TeleClaude - handles session persistence and retrieval."""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import aiosqlite

from teleclaude.config import config

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

from . import ux_state
from .models import Session
from .ux_state import SessionUXState


class Db:
    """Database interface for terminal sessions and state management."""

    def __init__(self, db_path: str) -> None:
        """Initialize database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

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

        # NOTE: We do NOT reset polling_active flags here!
        # The daemon's restore_active_pollers() function handles this correctly by:
        # 1. Checking if tmux session still exists
        # 2. If yes: restart polling
        # 3. If no: mark as inactive
        # Resetting here would prevent automatic polling restoration.

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()

    async def create_session(
        self,
        computer_name: str,
        tmux_session_name: str,
        origin_adapter: str,
        title: Optional[str] = None,
        adapter_metadata: Optional[dict[str, object]] = None,
        terminal_size: str = "80x24",
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
            adapter_metadata=adapter_metadata,
            closed=False,
            created_at=now,
            last_activity=now,
            terminal_size=terminal_size,
            working_directory=working_directory,
            description=description,
        )

        data = session.to_dict()
        await self._db.execute(
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
        await self._db.commit()

        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID.

        Args:
            session_id: Session ID

        Returns:
            Session object or None if not found
        """
        cursor = await self._db.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        row = await cursor.fetchone()

        if not row:
            return None

        return Session.from_dict(dict(row))

    async def list_sessions(self, computer_name: Optional[str] = None, closed: Optional[bool] = None) -> list[Session]:
        """List sessions with optional filters.

        Args:
            computer_name: Filter by computer name
            closed: Filter by closed status (False = active, True = closed, None = all)

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

        query += " ORDER BY last_activity DESC"

        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()

        return [Session.from_dict(dict(row)) for row in rows]

    async def update_session(self, session_id: str, **fields: object) -> None:
        """Update session fields.

        Args:
            session_id: Session ID
            **fields: Fields to update (title, status, terminal_size, etc.)
        """
        if not fields:
            return

        # Serialize adapter_metadata if it's a dict
        if "adapter_metadata" in fields and isinstance(fields["adapter_metadata"], dict):
            fields["adapter_metadata"] = json.dumps(fields["adapter_metadata"])

        set_clause = ", ".join(f"{key} = ?" for key in fields.keys())
        values = list(fields.values()) + [session_id]

        await self._db.execute(f"UPDATE sessions SET {set_clause} WHERE session_id = ?", values)
        await self._db.commit()

    async def update_last_activity(self, session_id: str) -> None:
        """Update last activity timestamp for session.

        Args:
            session_id: Session ID
        """
        await self._db.execute(
            "UPDATE sessions SET last_activity = ? WHERE session_id = ?", (datetime.now().isoformat(), session_id)
        )
        await self._db.commit()

    # State management functions (DB-backed via ux_state)

    async def is_polling(self, session_id: str) -> bool:
        """Check if session has active polling.

        Args:
            session_id: Session identifier

        Returns:
            True if polling is active for this session
        """
        ux_state = await self.get_ux_state(session_id)
        return ux_state.polling_active

    async def mark_polling(self, session_id: str) -> None:
        """Mark session as having active polling.

        Args:
            session_id: Session identifier
        """

        await self.update_ux_state(session_id, polling_active=True)

    async def unmark_polling(self, session_id: str) -> None:
        """Mark session as no longer polling.

        Args:
            session_id: Session identifier
        """

        await self.update_ux_state(session_id, polling_active=False)

    async def has_idle_notification(self, session_id: str) -> bool:
        """Check if session has idle notification.

        Args:
            session_id: Session identifier

        Returns:
            True if idle notification exists for this session
        """
        ux_state = await self.get_ux_state(session_id)
        return ux_state.idle_notification_message_id is not None

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

    async def get_idle_notification(self, session_id: str) -> Optional[str]:
        """Get idle notification message ID for session.

        Args:
            session_id: Session identifier

        Returns:
            Message ID of idle notification, or None if not set
        """
        ux_state = await self.get_ux_state(session_id)
        return ux_state.idle_notification_message_id

    async def set_idle_notification(self, session_id: str, message_id: str) -> None:
        """Set idle notification message ID for session.

        Args:
            session_id: Session identifier
            message_id: Message ID of the idle notification
        """

        await self.update_ux_state(session_id, idle_notification_message_id=message_id)

    async def remove_idle_notification(self, session_id: str) -> Optional[str]:
        """Remove and return idle notification message ID for session.

        Args:
            session_id: Session identifier

        Returns:
            Message ID that was removed, or None if not set
        """
        msg_id = await self.get_idle_notification(session_id)

        await self.update_ux_state(session_id, idle_notification_message_id=None)

        return msg_id

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

    async def delete_session(self, session_id: str) -> None:
        """Delete session.

        Args:
            session_id: Session ID
        """
        await self._db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        await self._db.commit()

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

        cursor = await self._db.execute(query, params)
        row = await cursor.fetchone()
        return row["count"] if row else 0

    async def get_sessions_by_adapter_metadata(
        self, adapter_type: str, metadata_key: str, metadata_value: object
    ) -> list[Session]:
        """Get sessions by adapter metadata field.

        Args:
            adapter_type: Adapter type
            metadata_key: JSON key to search in adapter_metadata
            metadata_value: Value to match

        Returns:
            List of matching sessions
        """
        # SQLite JSON functions
        cursor = await self._db.execute(
            f"""
            SELECT * FROM sessions
            WHERE origin_adapter = ?
            AND json_extract(adapter_metadata, '$.{metadata_key}') = ?
            """,
            (adapter_type, metadata_value),
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
        cursor = await self._db.execute(
            """
            SELECT * FROM sessions
            WHERE title LIKE ?
            ORDER BY created_at DESC
            """,
            (f"{pattern}%",),
        )
        rows = await cursor.fetchall()
        return [Session.from_dict(dict(row)) for row in rows]

    async def get_active_sessions(self) -> list[Session]:
        """Get all sessions with active polling.

        Returns sessions where ux_state.polling_active=True and closed=False.
        Used during daemon startup to restore polling for interrupted sessions.

        Returns:
            List of sessions with active polling
        """
        cursor = await self._db.execute(
            """
            SELECT * FROM sessions
            WHERE closed = 0
            ORDER BY last_activity DESC
            """
        )
        rows = await cursor.fetchall()
        all_sessions = [Session.from_dict(dict(row)) for row in rows]

        # Filter by polling_active in ux_state
        active_sessions = []
        for session in all_sessions:
            ux_state_data = await self.get_ux_state(session.session_id)
            if ux_state_data.polling_active:
                active_sessions.append(session)

        return active_sessions

    async def set_polling_inactive(self, session_id: str) -> None:
        """Mark polling as inactive for a session.

        Used when tmux session no longer exists during restoration.

        Args:
            session_id: Session ID
        """
        await self.update_ux_state(session_id, polling_active=False)

    async def get_ux_state(self, session_id: str) -> SessionUXState:
        """Get UX state for session.

        Args:
            session_id: Session ID

        Returns:
            SessionUXState (with defaults if not found)
        """
        return await ux_state.get_session_ux_state(self._db, session_id)

    async def update_ux_state(
        self,
        session_id: str,
        *,
        output_message_id: Optional[str] | object = ux_state._UNSET,
        polling_active: bool | object = ux_state._UNSET,
        idle_notification_message_id: Optional[str] | object = ux_state._UNSET,
        pending_deletions: list[str] | object = ux_state._UNSET,
    ) -> None:
        """Update UX state for session (merges with existing).

        Args:
            session_id: Session ID
            output_message_id: Output message ID (optional)
            polling_active: Whether polling is active (optional)
            idle_notification_message_id: Idle notification message ID (optional)
            pending_deletions: List of message IDs pending deletion (optional)
        """
        await ux_state.update_session_ux_state(
            self._db,
            session_id,
            output_message_id=output_message_id,
            polling_active=polling_active,
            idle_notification_message_id=idle_notification_message_id,
            pending_deletions=pending_deletions,
        )


# Module-level singleton instance (initialized on first import)
db = Db(config.database.path)
