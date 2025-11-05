"""Session manager for TeleClaude - handles session persistence and retrieval."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from .models import Session
from . import ux_state


class SessionManager:
    """Manages terminal sessions in SQLite database."""

    def __init__(self, db_path: str) -> None:
        """Initialize session manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Initialize database and create tables."""
        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Connect to database
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        # Load and execute schema
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        await self._db.executescript(schema_sql)
        await self._db.commit()

        # Migration: Add output_message_id column if it doesn't exist
        try:
            await self._db.execute("ALTER TABLE sessions ADD COLUMN output_message_id TEXT")
            await self._db.commit()
        except aiosqlite.OperationalError:
            # Column already exists
            pass

        # Migration: Add idle_notification_message_id column if it doesn't exist
        try:
            await self._db.execute("ALTER TABLE sessions ADD COLUMN idle_notification_message_id TEXT")
            await self._db.commit()
        except aiosqlite.OperationalError:
            # Column already exists
            pass

        # Migration: Add description column if it doesn't exist (for AI-to-AI sessions)
        try:
            await self._db.execute("ALTER TABLE sessions ADD COLUMN description TEXT")
            await self._db.commit()
        except aiosqlite.OperationalError:
            # Column already exists
            pass

        # Migration: Add ux_state column if it doesn't exist (generic UX state JSON blob)
        try:
            await self._db.execute("ALTER TABLE sessions ADD COLUMN ux_state TEXT")
            await self._db.commit()
        except aiosqlite.OperationalError:
            # Column already exists
            pass

        # Migration: Convert status TEXT to closed BOOLEAN
        try:
            # Add closed column
            await self._db.execute("ALTER TABLE sessions ADD COLUMN closed BOOLEAN DEFAULT 0")
            await self._db.commit()

            # Migrate data: set closed=1 where status='closed'
            await self._db.execute("UPDATE sessions SET closed = 1 WHERE status = 'closed'")
            await self._db.commit()

            # Drop old status column (SQLite doesn't support DROP COLUMN before 3.35.0, so we recreate the table)
            # Check if status column still exists
            cursor = await self._db.execute("PRAGMA table_info(sessions)")
            columns = await cursor.fetchall()
            has_status = any(col[1] == "status" for col in columns)

            if has_status:
                # Recreate table without status column
                await self._db.execute(
                    """
                    CREATE TABLE sessions_new (
                        session_id TEXT PRIMARY KEY,
                        computer_name TEXT NOT NULL,
                        title TEXT,
                        tmux_session_name TEXT NOT NULL,
                        adapter_type TEXT NOT NULL DEFAULT 'telegram',
                        adapter_metadata TEXT,
                        closed BOOLEAN DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        terminal_size TEXT DEFAULT '80x24',
                        working_directory TEXT DEFAULT '~',
                        command_count INTEGER DEFAULT 0,
                        output_message_id TEXT,
                        idle_notification_message_id TEXT,
                        UNIQUE(computer_name, tmux_session_name)
                    )
                """
                )

                # Copy data
                await self._db.execute(
                    """
                    INSERT INTO sessions_new
                    SELECT session_id, computer_name, title, tmux_session_name, adapter_type,
                           adapter_metadata, closed, created_at, last_activity, terminal_size,
                           working_directory, command_count, output_message_id, idle_notification_message_id
                    FROM sessions
                """
                )

                # Drop old table and rename new one
                await self._db.execute("DROP TABLE sessions")
                await self._db.execute("ALTER TABLE sessions_new RENAME TO sessions")

                # Recreate indexes
                await self._db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_closed ON sessions(closed)")
                await self._db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_computer ON sessions(computer_name)")
                await self._db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_adapter ON sessions(adapter_type)")
                await self._db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sessions_last_activity ON sessions(last_activity)"
                )

                await self._db.commit()
        except aiosqlite.OperationalError:
            # Migration already done or column already exists
            pass

        # Ensure indexes exist (for both fresh installs and migrated databases)
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_closed ON sessions(closed)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_computer ON sessions(computer_name)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_adapter ON sessions(adapter_type)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_last_activity ON sessions(last_activity)")
        await self._db.commit()

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()

    async def create_session(
        self,
        computer_name: str,
        tmux_session_name: str,
        adapter_type: str,
        title: Optional[str] = None,
        adapter_metadata: Optional[Dict[str, Any]] = None,
        terminal_size: str = "80x24",
        working_directory: str = "~",
        description: Optional[str] = None,
    ) -> Session:
        """Create a new session.

        Args:
            computer_name: Name of the computer
            tmux_session_name: Name of tmux session
            adapter_type: Type of adapter (telegram, rest, etc.)
            title: Optional session title
            adapter_metadata: Optional adapter-specific metadata
            terminal_size: Terminal dimensions (e.g., '80x24')
            working_directory: Initial working directory
            description: Optional description (for AI-to-AI sessions)

        Returns:
            Created Session object
        """
        session_id = str(uuid.uuid4())
        now = datetime.now()

        session = Session(
            session_id=session_id,
            computer_name=computer_name,
            tmux_session_name=tmux_session_name,
            adapter_type=adapter_type,
            title=title or f"[{computer_name}] New session",
            adapter_metadata=adapter_metadata,
            closed=False,
            created_at=now,
            last_activity=now,
            terminal_size=terminal_size,
            working_directory=working_directory,
            command_count=0,
            description=description,
        )

        data = session.to_dict()
        await self._db.execute(
            """
            INSERT INTO sessions (
                session_id, computer_name, title, tmux_session_name,
                adapter_type, adapter_metadata, closed, created_at,
                last_activity, terminal_size, working_directory, command_count, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["session_id"],
                data["computer_name"],
                data["title"],
                data["tmux_session_name"],
                data["adapter_type"],
                data["adapter_metadata"],
                data["closed"],
                data["created_at"],
                data["last_activity"],
                data["terminal_size"],
                data["working_directory"],
                data["command_count"],
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

    async def list_sessions(
        self, computer_name: Optional[str] = None, closed: Optional[bool] = None, adapter_type: Optional[str] = None
    ) -> List[Session]:
        """List sessions with optional filters.

        Args:
            computer_name: Filter by computer name
            closed: Filter by closed status (False = active, True = closed, None = all)
            adapter_type: Filter by adapter type

        Returns:
            List of Session objects
        """
        query = "SELECT * FROM sessions WHERE 1=1"
        params: List[Any] = []

        if computer_name:
            query += " AND computer_name = ?"
            params.append(computer_name)
        if closed is not None:
            query += " AND closed = ?"
            params.append(1 if closed else 0)
        if adapter_type:
            query += " AND adapter_type = ?"
            params.append(adapter_type)

        query += " ORDER BY last_activity DESC"

        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()

        return [Session.from_dict(dict(row)) for row in rows]

    async def update_session(self, session_id: str, **fields: Any) -> None:
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
        from teleclaude.core import ux_state

        session_data = await self.get_ux_state(session_id)
        return session_data.get("polling_active", False)

    async def mark_polling(self, session_id: str) -> None:
        """Mark session as having active polling.

        Args:
            session_id: Session identifier
        """
        from teleclaude.core import ux_state

        await self.update_ux_state(session_id, {"polling_active": True})

    async def unmark_polling(self, session_id: str) -> None:
        """Mark session as no longer polling.

        Args:
            session_id: Session identifier
        """
        from teleclaude.core import ux_state

        await self.update_ux_state(session_id, {"polling_active": False})

    async def has_idle_notification(self, session_id: str) -> bool:
        """Check if session has idle notification.

        Args:
            session_id: Session identifier

        Returns:
            True if idle notification exists for this session
        """
        from teleclaude.core import ux_state

        session_data = await self.get_ux_state(session_id)
        return session_data.get("idle_notification_message_id") is not None

    async def get_idle_notification(self, session_id: str) -> Optional[str]:
        """Get idle notification message ID for session.

        Args:
            session_id: Session identifier

        Returns:
            Message ID of idle notification, or None if not set
        """
        from teleclaude.core import ux_state

        session_data = await self.get_ux_state(session_id)
        return session_data.get("idle_notification_message_id")

    async def set_idle_notification(self, session_id: str, message_id: str) -> None:
        """Set idle notification message ID for session.

        Args:
            session_id: Session identifier
            message_id: Message ID of the idle notification
        """
        from teleclaude.core import ux_state

        await self.update_ux_state(session_id, {"idle_notification_message_id": message_id})

    async def remove_idle_notification(self, session_id: str) -> Optional[str]:
        """Remove and return idle notification message ID for session.

        Args:
            session_id: Session identifier

        Returns:
            Message ID that was removed, or None if not set
        """
        msg_id = await self.get_idle_notification(session_id)

        from teleclaude.core import ux_state

        await self.update_ux_state(session_id, {"idle_notification_message_id": None})

        return msg_id

    async def get_pending_deletions(self, session_id: str) -> List[str]:
        """Get list of pending deletion message IDs for session.

        Args:
            session_id: Session identifier

        Returns:
            List of message IDs to delete (empty list if none)
        """
        from teleclaude.core import ux_state

        session_data = await self.get_ux_state(session_id)
        return session_data.get("pending_deletions", [])

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

        from teleclaude.core import ux_state

        await self.update_ux_state(session_id, {"pending_deletions": current})

    async def clear_pending_deletions(self, session_id: str) -> None:
        """Clear all pending deletions for session.

        Should be called after deleting all pending messages, or when polling stops.

        Args:
            session_id: Session identifier
        """
        from teleclaude.core import ux_state

        await self.update_ux_state(session_id, {"pending_deletions": []})

    async def cleanup_messages_after_success(
        self,
        session_id: str,
        message_id: Optional[str],
        adapter: Any,
    ) -> None:
        """Clean up pending messages after successful terminal action.

        This helper is called by:
        - message_handler.py (after send_keys succeeds)
        - command_handlers.py (_execute_and_poll helper after any command succeeds)

        Deletes all tracked messages (feedback + previous commands + current message).
        Clears pending deletions list so new messages can be tracked.

        Args:
            session_id: Session identifier
            message_id: Message ID of current command/input (to be deleted)
            adapter: Chat adapter for deleting messages
        """
        import logging

        logger = logging.getLogger(__name__)

        # Get all pending deletions (feedback messages, previous commands, etc.)
        pending_deletions = await self.get_pending_deletions(session_id)

        # Add current message to deletions
        pending_deletions.append(message_id)

        # Delete ALL messages underneath the output (feedback + user messages)
        # Sequential deletion to avoid rate limiting
        for msg_id in pending_deletions:
            try:
                await adapter.delete_message(session_id, msg_id)
                logger.debug("Deleted message %s for session %s (cleanup)", msg_id, session_id[:8])
            except Exception as e:
                # Resilient to already-deleted messages (user manually deleted, etc.)
                logger.warning("Failed to delete message %s for session %s: %s", msg_id, session_id[:8], e)

        # Clear pending deletions after cleanup
        await self.clear_pending_deletions(session_id)

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
        params: List[Any] = []

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
        self, adapter_type: str, metadata_key: str, metadata_value: Any
    ) -> List[Session]:
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
            WHERE adapter_type = ?
            AND json_extract(adapter_metadata, '$.{metadata_key}') = ?
            """,
            (adapter_type, metadata_value),
        )
        rows = await cursor.fetchall()
        return [Session.from_dict(dict(row)) for row in rows]

    async def get_sessions_by_title_pattern(self, pattern: str) -> List[Session]:
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

    async def get_ux_state(self, session_id: str) -> dict:
        """Get UX state for session.

        Args:
            session_id: Session ID

        Returns:
            Dict with UX state (empty dict if not found)
        """
        return await ux_state.get_ux_state(self._db, ux_state.UXStateContext.SESSION, session_id)

    async def update_ux_state(self, session_id: str, updates: dict) -> None:
        """Update UX state for session (merges with existing).

        Args:
            session_id: Session ID
            updates: Dict with properties to update
        """
        await ux_state.update_ux_state(self._db, ux_state.UXStateContext.SESSION, updates, session_id)
