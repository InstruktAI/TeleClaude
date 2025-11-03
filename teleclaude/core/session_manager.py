"""Session manager for TeleClaude - handles session persistence and retrieval."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from .models import Session


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
            status="active",
            created_at=now,
            last_activity=now,
            terminal_size=terminal_size,
            working_directory=working_directory,
            command_count=0,
        )

        data = session.to_dict()
        await self._db.execute(
            """
            INSERT INTO sessions (
                session_id, computer_name, title, tmux_session_name,
                adapter_type, adapter_metadata, status, created_at,
                last_activity, terminal_size, working_directory, command_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["session_id"],
                data["computer_name"],
                data["title"],
                data["tmux_session_name"],
                data["adapter_type"],
                data["adapter_metadata"],
                data["status"],
                data["created_at"],
                data["last_activity"],
                data["terminal_size"],
                data["working_directory"],
                data["command_count"],
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
        self, computer_name: Optional[str] = None, status: Optional[str] = None, adapter_type: Optional[str] = None
    ) -> List[Session]:
        """List sessions with optional filters.

        Args:
            computer_name: Filter by computer name
            status: Filter by status
            adapter_type: Filter by adapter type

        Returns:
            List of Session objects
        """
        query = "SELECT * FROM sessions WHERE 1=1"
        params = []

        if computer_name:
            query += " AND computer_name = ?"
            params.append(computer_name)
        if status:
            query += " AND status = ?"
            params.append(status)
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

    async def increment_command_count(self, session_id: str) -> int:
        """Increment command count and return new value.

        Args:
            session_id: Session ID

        Returns:
            New command count
        """
        await self._db.execute(
            "UPDATE sessions SET command_count = command_count + 1 WHERE session_id = ?", (session_id,)
        )
        await self._db.commit()

        cursor = await self._db.execute("SELECT command_count FROM sessions WHERE session_id = ?", (session_id,))
        row = await cursor.fetchone()
        return row["command_count"] if row else 0

    async def set_output_message_id(self, session_id: str, message_id: Optional[str]) -> None:
        """Set output message ID for session.

        Args:
            session_id: Session ID
            message_id: Message ID to persist (None to clear)
        """
        await self._db.execute(
            "UPDATE sessions SET output_message_id = ? WHERE session_id = ?", (message_id, session_id)
        )
        await self._db.commit()

    async def get_output_message_id(self, session_id: str) -> Optional[str]:
        """Get output message ID for session.

        Args:
            session_id: Session ID

        Returns:
            Message ID or None
        """
        cursor = await self._db.execute("SELECT output_message_id FROM sessions WHERE session_id = ?", (session_id,))
        row = await cursor.fetchone()
        return row["output_message_id"] if row else None

    async def set_idle_notification_message_id(self, session_id: str, message_id: Optional[str]) -> None:
        """Set idle notification message ID for session.

        Args:
            session_id: Session ID
            message_id: Message ID to persist (None to clear)
        """
        await self._db.execute(
            "UPDATE sessions SET idle_notification_message_id = ? WHERE session_id = ?", (message_id, session_id)
        )
        await self._db.commit()

    async def get_idle_notification_message_id(self, session_id: str) -> Optional[str]:
        """Get idle notification message ID for session.

        Args:
            session_id: Session ID

        Returns:
            Message ID or None
        """
        cursor = await self._db.execute(
            "SELECT idle_notification_message_id FROM sessions WHERE session_id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        return row["idle_notification_message_id"] if row else None

    async def delete_session(self, session_id: str) -> None:
        """Delete session.

        Args:
            session_id: Session ID
        """
        await self._db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        await self._db.commit()

    async def count_sessions(self, computer_name: Optional[str] = None, status: Optional[str] = None) -> int:
        """Count sessions with optional filters.

        Args:
            computer_name: Filter by computer name
            status: Filter by status

        Returns:
            Number of sessions
        """
        query = "SELECT COUNT(*) as count FROM sessions WHERE 1=1"
        params = []

        if computer_name:
            query += " AND computer_name = ?"
            params.append(computer_name)
        if status:
            query += " AND status = ?"
            params.append(status)

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
