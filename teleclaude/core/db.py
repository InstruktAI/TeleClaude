"""Database manager for TeleClaude - handles session persistence and retrieval."""

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional, TypedDict

import aiosqlite
from instrukt_ai_logging import get_logger
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.config import config
from teleclaude.constants import DB_IN_MEMORY
from teleclaude.core.event_bus import event_bus

from . import db_models
from .dates import ensure_utc, parse_iso_datetime
from .events import SessionLifecycleContext, SessionUpdatedContext, TeleClaudeEvents
from .models import Session, SessionAdapterMetadata, SessionField
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


class Db:
    """Database interface for tmux sessions and state management."""

    @staticmethod
    def _serialize_adapter_metadata(
        value: SessionAdapterMetadata
        | dict[str, object]  # guard: loose-dict - Adapter metadata JSON payload.
        | str
        | None,
    ) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return json.dumps(value)
        return value.to_json()

    @staticmethod
    def _coerce_datetime(value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return ensure_utc(value)
        return parse_iso_datetime(value)

    @staticmethod
    def _to_core_session(row: db_models.Session) -> Session:
        adapter_metadata = (
            SessionAdapterMetadata.from_json(row.adapter_metadata)
            if isinstance(row.adapter_metadata, str) and row.adapter_metadata
            else SessionAdapterMetadata()
        )
        return Session(
            session_id=row.session_id,
            computer_name=row.computer_name,
            tmux_session_name=row.tmux_session_name,
            last_input_origin=row.last_input_origin,
            title=row.title or "",
            adapter_metadata=adapter_metadata,
            created_at=Db._coerce_datetime(row.created_at),
            last_activity=Db._coerce_datetime(row.last_activity),
            closed_at=Db._coerce_datetime(row.closed_at),
            project_path=row.project_path,
            subdir=row.subdir,
            description=row.description,
            initiated_by_ai=bool(row.initiated_by_ai) if row.initiated_by_ai is not None else False,
            initiator_session_id=row.initiator_session_id,
            output_message_id=row.output_message_id,
            notification_sent=bool(row.notification_sent) if row.notification_sent is not None else False,
            native_session_id=row.native_session_id,
            native_log_file=row.native_log_file,
            active_agent=row.active_agent,
            thinking_mode=row.thinking_mode,
            tui_log_file=row.tui_log_file,
            tui_capture_started=bool(row.tui_capture_started) if row.tui_capture_started is not None else False,
            last_message_sent=row.last_message_sent,
            last_message_sent_at=Db._coerce_datetime(row.last_message_sent_at),
            last_feedback_received=row.last_feedback_received,
            last_feedback_received_at=Db._coerce_datetime(row.last_feedback_received_at),
            working_slug=row.working_slug,
            lifecycle_status=row.lifecycle_status or "active",
        )

    def __init__(self, db_path: str) -> None:
        """Initialize database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._engine: Optional[AsyncEngine] = None
        self._sessionmaker: Optional[object] = None
        self.conn: aiosqlite.Connection | None = None
        self._temp_db_path: str | None = None

    async def initialize(self) -> None:
        """Initialize database, create tables, and run migrations."""
        from teleclaude.core.migrations.runner import run_pending_migrations

        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        db_path = self.db_path
        use_uri = False
        if self.db_path == DB_IN_MEMORY:
            temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            self._temp_db_path = temp_file.name
            temp_file.close()
            db_path = self._temp_db_path

        # Ensure schema + migrations via aiosqlite (single-shot bootstrap)
        self.conn = await aiosqlite.connect(db_path, uri=use_uri)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode = WAL")
        await self.conn.execute("PRAGMA synchronous = NORMAL")
        await self.conn.execute("PRAGMA busy_timeout = 5000")

        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        await self.conn.executescript(schema_sql)
        await self.conn.commit()

        await run_pending_migrations(self.conn)

        # Async engine for runtime access
        db_url = f"sqlite+aiosqlite:///{db_path}"
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.orm import sessionmaker

        connect_args = {"uri": True} if use_uri else {}
        self._engine = create_async_engine(db_url, future=True, connect_args=connect_args)
        self._sessionmaker = sessionmaker(self._engine, expire_on_commit=False, class_=SqlAsyncSession)

        async with self._engine.begin() as conn:
            from sqlalchemy import text

            await conn.execute(text("PRAGMA journal_mode = WAL"))
            await conn.execute(text("PRAGMA synchronous = NORMAL"))
            await conn.execute(text("PRAGMA busy_timeout = 5000"))

        await self._normalize_adapter_metadata()

    async def _normalize_adapter_metadata(self) -> None:
        """Normalize adapter_metadata types (e.g., topic_id stored as string)."""
        from sqlalchemy.exc import OperationalError

        async with self._session() as session:
            from sqlmodel import select

            try:
                result = await session.exec(select(db_models.Session))
            except OperationalError:
                return
            rows = result.all()
            if not rows:
                return

            any_updated = False
            for row in rows:
                raw = row.adapter_metadata
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
                    row.adapter_metadata = json.dumps(parsed)
                    session.add(row)
                    any_updated = True

            if any_updated:
                await session.commit()

    def _session(self) -> SqlAsyncSession:
        if self._sessionmaker is None:
            raise RuntimeError("Database not initialized - call initialize() first")
        return self._sessionmaker()  # type: ignore[call-arg]

    def is_initialized(self) -> bool:
        return self._sessionmaker is not None

    def set_client(self, client: "AdapterClient") -> None:
        """Deprecated no-op: events are emitted via the global event bus."""
        _ = client

    async def close(self) -> None:
        """Close database connection."""
        if self._engine:
            await self._engine.dispose()
        if self.conn:
            await self.conn.close()
        if self._temp_db_path:
            try:
                os.remove(self._temp_db_path)
            except OSError:
                pass

    async def create_session(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # Database insert requires all session fields
        self,
        computer_name: str,
        tmux_session_name: str,
        last_input_origin: str,
        title: str,
        adapter_metadata: Optional[SessionAdapterMetadata] = None,
        project_path: Optional[str] = None,
        subdir: Optional[str] = None,
        description: Optional[str] = None,
        session_id: Optional[str] = None,
        working_slug: Optional[str] = None,
        initiator_session_id: Optional[str] = None,
        lifecycle_status: str = "active",
    ) -> Session:
        """Create a new session.

        Args:
            computer_name: Name of the computer
            tmux_session_name: Name of tmux session
            last_input_origin: Last input origin (e.g., "telegram", "cli")
            title: Optional session title
            adapter_metadata: Optional adapter-specific metadata
            project_path: Base project path (no subdir)
            subdir: Optional subdirectory/worktree relative to project_path
            description: Optional description (for AI-to-AI sessions)
            session_id: Optional explicit session ID (for AI-to-AI cross-computer sessions)
            working_slug: Optional slug of work item this session is working on
            initiator_session_id: Session ID of the AI that created this session (for AI-to-AI nesting)

        Returns:
            Created Session object
        """
        session_id = session_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        session = Session(
            session_id=session_id,
            computer_name=computer_name,
            tmux_session_name=tmux_session_name,
            last_input_origin=last_input_origin,
            title=title or f"[{computer_name}] Untitled",
            adapter_metadata=adapter_metadata or SessionAdapterMetadata(),
            created_at=now,
            last_activity=now,
            project_path=project_path,
            subdir=subdir,
            description=description,
            working_slug=working_slug,
            initiator_session_id=initiator_session_id,
            lifecycle_status=lifecycle_status,
        )

        db_row = db_models.Session(
            session_id=session.session_id,
            computer_name=session.computer_name,
            title=session.title,
            tmux_session_name=session.tmux_session_name,
            last_input_origin=session.last_input_origin,
            adapter_metadata=self._serialize_adapter_metadata(session.adapter_metadata),
            created_at=session.created_at,
            last_activity=session.last_activity,
            project_path=session.project_path,
            subdir=session.subdir,
            description=session.description,
            working_slug=session.working_slug,
            initiator_session_id=session.initiator_session_id,
            lifecycle_status=session.lifecycle_status,
        )
        async with self._session() as db_session:
            db_session.add(db_row)
            await db_session.commit()

        event_bus.emit(
            TeleClaudeEvents.SESSION_STARTED,
            SessionLifecycleContext(session_id=session_id),
        )

        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID.

        Args:
            session_id: Session ID

        Returns:
            Session object or None if not found
        """
        async with self._session() as db_session:
            row = await db_session.get(db_models.Session, session_id)
            if not row:
                return None
            return self._to_core_session(row)

    async def get_session_by_field(
        self, field: str, value: object, *, include_initializing: bool = False
    ) -> Optional[Session]:
        """Get session by field value.

        Args:
            field: Session field name (e.g., "native_session_id", "output_message_id")
            value: Value to match

        Returns:
            Session object or None if not found
        """
        column = getattr(db_models.Session, field, None)
        if column is None:
            return None
        async with self._session() as db_session:
            from sqlmodel import select

            conditions = [column == value, db_models.Session.closed_at.is_(None)]
            if not include_initializing:
                conditions.append(db_models.Session.lifecycle_status == "active")
            result = await db_session.exec(select(db_models.Session).where(*conditions))
            row = result.first()
            if not row:
                return None
            return self._to_core_session(row)

    async def list_sessions(
        self,
        computer_name: Optional[str] = None,
        last_input_origin: Optional[str] = None,
        include_closed: bool = False,
        include_initializing: bool = False,
    ) -> list[Session]:
        """List sessions with optional filters.

        Args:
            computer_name: Filter by computer name
            last_input_origin: Filter by last input origin (telegram, redis, cli)
            include_closed: Include closed sessions when True

        Returns:
            List of Session objects
        """
        from sqlmodel import select

        stmt = select(db_models.Session)
        if not include_closed:
            stmt = stmt.where(db_models.Session.closed_at.is_(None))
        if not include_initializing:
            stmt = stmt.where(db_models.Session.lifecycle_status == "active")
        if computer_name:
            stmt = stmt.where(db_models.Session.computer_name == computer_name)
        if last_input_origin:
            stmt = stmt.where(db_models.Session.last_input_origin == last_input_origin)
        stmt = stmt.order_by(db_models.Session.last_activity.desc())

        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            rows = result.all()
            return [self._to_core_session(row) for row in rows]

    async def update_session(self, session_id: str, **fields: object) -> None:
        """Update session fields and handle events.

        Args:
            session_id: Session ID
            **fields: Fields to update (title, status, tmux_size, etc.)
        """
        if not fields:
            return

        async with self._session() as db_session:
            row = await db_session.get(db_models.Session, session_id)
            if not row:
                logger.warning("Attempted to update non-existent session: %s", session_id[:8])
                return

            updates: dict[str, object] = {}  # guard: loose-dict - Dynamic update payload
            for key, value in fields.items():
                field = None
                if isinstance(key, SessionField):
                    field = key
                else:
                    try:
                        field = SessionField(str(key))
                    except ValueError:
                        field = None
                attr_name = field.value if field else str(key)
                if not hasattr(row, attr_name):
                    continue
                current_val = getattr(row, attr_name)
                if field == SessionField.ADAPTER_METADATA:
                    serialized = self._serialize_adapter_metadata(value)
                    if current_val != serialized:
                        updates[attr_name] = serialized
                    continue
                if isinstance(value, str) and attr_name in {
                    "created_at",
                    "last_activity",
                    "closed_at",
                    "last_message_sent_at",
                    "last_feedback_received_at",
                }:
                    parsed = self._parse_iso_datetime(value)
                    if parsed and current_val != parsed:
                        updates[attr_name] = parsed
                    continue
                if current_val != value:
                    updates[attr_name] = value

            if not updates:
                logger.trace("Skipping redundant update for session %s", session_id[:8])
                return

            now = datetime.now(timezone.utc)
            if (
                SessionField.LAST_MESSAGE_SENT.value in updates
                and SessionField.LAST_MESSAGE_SENT_AT.value not in updates
            ):
                updates[SessionField.LAST_MESSAGE_SENT_AT.value] = now
            if (
                SessionField.LAST_FEEDBACK_RECEIVED.value in updates
                and SessionField.LAST_FEEDBACK_RECEIVED_AT.value not in updates
            ):
                updates[SessionField.LAST_FEEDBACK_RECEIVED_AT.value] = now
                summary_val = updates.get(SessionField.LAST_FEEDBACK_RECEIVED.value)
                summary_len = len(str(summary_val)) if summary_val is not None else 0
                logger.debug(
                    "Summary updated: session=%s len=%d",
                    session_id[:8],
                    summary_len,
                )

            for key, value in updates.items():
                setattr(row, key, value)
            db_session.add(row)
            await db_session.commit()

        # Emit SESSION_UPDATED event (UI handlers will update channel titles)
        event_bus.emit(
            TeleClaudeEvents.SESSION_UPDATED,
            SessionUpdatedContext(session_id=session_id, updated_fields=updates),
        )

    async def close_session(self, session_id: str) -> None:
        """Mark a session as closed without deleting it."""
        session = await self.get_session(session_id)
        if not session:
            logger.warning("Attempted to close non-existent session: %s", session_id[:8])
            return
        if session.closed_at:
            return
        await self.update_session(
            session_id,
            closed_at=datetime.now(timezone.utc),
            lifecycle_status="closed",
        )
        event_bus.emit(
            TeleClaudeEvents.SESSION_CLOSED,
            SessionLifecycleContext(session_id=session_id),
        )

    async def update_last_activity(self, session_id: str) -> None:
        """Update last activity timestamp for session.

        Args:
            session_id: Session ID
        """
        await self.update_session(session_id, last_activity=datetime.now(timezone.utc))

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

    async def get_pending_deletions(
        self, session_id: str, deletion_type: Literal["user_input", "feedback"] = "user_input"
    ) -> list[str]:
        """Get list of pending deletion message IDs for session.

        Args:
            session_id: Session identifier
            deletion_type: Type of deletion - 'user_input' (cleaned on next user input)
                          or 'feedback' (cleaned when next feedback is sent)

        Returns:
            List of message IDs to delete (empty list if none)
        """
        from sqlmodel import select

        stmt = select(db_models.PendingMessageDeletion.message_id).where(
            db_models.PendingMessageDeletion.session_id == session_id,
            db_models.PendingMessageDeletion.deletion_type == deletion_type,
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            rows = result.all()
            return [str(row) for row in rows]

    async def add_pending_deletion(
        self, session_id: str, message_id: str, deletion_type: Literal["user_input", "feedback"] = "user_input"
    ) -> None:
        """Add message ID to pending deletions for session.

        Args:
            session_id: Session identifier
            message_id: Message ID to delete later
            deletion_type: Type of deletion - 'user_input' (cleaned on next user input)
                          or 'feedback' (cleaned when next feedback is sent)
        """
        try:
            async with self._session() as db_session:
                db_session.add(
                    db_models.PendingMessageDeletion(
                        session_id=session_id,
                        message_id=message_id,
                        deletion_type=deletion_type,
                    )
                )
                await db_session.commit()
        except Exception as exc:
            logger.error(
                "Failed to add pending deletion: session=%s message_id=%s deletion_type=%s error=%s",
                session_id[:8],
                message_id,
                deletion_type,
                exc,
            )

    async def clear_pending_deletions(
        self, session_id: str, deletion_type: Literal["user_input", "feedback"] = "user_input"
    ) -> None:
        """Clear all pending deletions for session.

        Args:
            session_id: Session identifier
            deletion_type: Type of deletion to clear
        """
        stmt = (
            db_models.PendingMessageDeletion.__table__.delete()
            .where(db_models.PendingMessageDeletion.session_id == session_id)
            .where(db_models.PendingMessageDeletion.deletion_type == deletion_type)
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)  # type: ignore[arg-type]
            await db_session.commit()

    async def delete_session(self, session_id: str) -> None:
        """Delete session and handle event.

        Args:
            session_id: Session ID
        """
        # Get session before deleting for event emission
        session = await self.get_session(session_id)

        async with self._session() as db_session:
            await db_session.exec(
                db_models.Session.__table__.delete().where(db_models.Session.session_id == session_id)
            )  # type: ignore[arg-type]
            await db_session.commit()
        logger.debug("Deleted session %s from database", session_id[:8])

        if session:
            event_bus.emit(
                TeleClaudeEvents.SESSION_CLOSED,
                SessionLifecycleContext(session_id=session_id),
            )

    async def count_sessions(self, computer_name: Optional[str] = None) -> int:
        """Count sessions with optional filters.

        Args:
            computer_name: Filter by computer name

        Returns:
            Number of sessions
        """
        from sqlalchemy import func
        from sqlmodel import select

        stmt = select(func.count()).select_from(db_models.Session)
        if computer_name:
            stmt = stmt.where(db_models.Session.computer_name == computer_name)

        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            count = result.one()
            return int(count)

    async def get_sessions_by_adapter_metadata(
        self,
        adapter_type: str,
        metadata_key: str,
        metadata_value: object,
        include_closed: bool = False,
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
        base_query = f"""
            SELECT * FROM sessions
            WHERE json_extract(adapter_metadata, '$.{adapter_type}.{metadata_key}') = :value
        """
        if not include_closed:
            base_query += " AND closed_at IS NULL"

        params: dict[str, object] = {"value": metadata_value}  # guard: loose-dict - SQL params.
        if isinstance(metadata_value, int):
            base_query = f"""
                SELECT * FROM sessions
                WHERE json_extract(adapter_metadata, '$.{adapter_type}.{metadata_key}') = :value
                   OR json_extract(adapter_metadata, '$.{adapter_type}.{metadata_key}') = :value_str
            """
            if not include_closed:
                base_query += " AND closed_at IS NULL"
            params["value_str"] = str(metadata_value)

        async with self._session() as db_session:
            from sqlalchemy import text

            stmt = text(base_query).bindparams(**params)
            result = await db_session.exec(stmt)
            rows = result.mappings().all()
            return [Session.from_dict(dict(row)) for row in rows]

    async def get_sessions_by_title_pattern(self, pattern: str, include_closed: bool = False) -> list[Session]:
        """Get sessions where title starts with the given pattern.

        Args:
            pattern: Title pattern to match (e.g., "$macbook > $")

        Returns:
            List of matching sessions
        """
        from sqlmodel import select

        stmt = select(db_models.Session).where(db_models.Session.title.like(f"{pattern}%"))
        if not include_closed:
            stmt = stmt.where(db_models.Session.closed_at.is_(None))
        stmt = stmt.order_by(db_models.Session.created_at.desc())
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            rows = result.all()
            return [self._to_core_session(row) for row in rows]

    async def get_all_sessions(self) -> list[Session]:
        """Get all sessions ordered by last activity."""
        from sqlmodel import select

        stmt = select(db_models.Session).order_by(db_models.Session.last_activity.desc())
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            rows = result.all()
            return [self._to_core_session(row) for row in rows]

    async def get_active_sessions(self) -> list[Session]:
        """Get all sessions ordered by last activity."""
        from sqlmodel import select

        stmt = (
            select(db_models.Session)
            .where(
                db_models.Session.closed_at.is_(None),
                db_models.Session.lifecycle_status == "active",
            )
            .order_by(db_models.Session.last_activity.desc())
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            rows = result.all()
            return [self._to_core_session(row) for row in rows]

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
        async with self._session() as db_session:
            row = await db_session.get(db_models.SystemSetting, key)
            return row.value if row else None

    async def set_system_setting(self, key: str, value: str) -> None:
        """Set system setting value (upsert).

        Args:
            key: Setting key
            value: Setting value
        """
        async with self._session() as db_session:
            row = await db_session.get(db_models.SystemSetting, key)
            if row is None:
                row = db_models.SystemSetting(key=key, value=value)
            else:
                row.value = value
            db_session.add(row)
            await db_session.commit()

    # Voice assignment methods

    async def assign_voice(self, voice_id: str, voice: VoiceConfig) -> None:
        """Assign a voice keyed by ID (either teleclaude_session_id or native_session_id).

        Args:
            voice_id: Either teleclaude session ID or Agent session ID
            voice: VoiceConfig to assign
        """
        async with self._session() as db_session:
            row = await db_session.get(db_models.VoiceAssignment, voice_id)
            if row is None:
                row = db_models.VoiceAssignment(
                    id=voice_id,
                    voice_name=voice.name,
                    elevenlabs_id=voice.elevenlabs_id,
                    macos_voice=voice.macos_voice,
                    openai_voice=voice.openai_voice,
                )
            else:
                row.voice_name = voice.name
                row.elevenlabs_id = voice.elevenlabs_id
                row.macos_voice = voice.macos_voice
                row.openai_voice = voice.openai_voice
            db_session.add(row)
            await db_session.commit()
        logger.debug("Assigned voice '%s' to %s", voice.name, voice_id[:8])

    async def get_voice(self, voice_id: str) -> Optional[VoiceConfig]:
        """Get voice assignment by ID.

        Args:
            voice_id: Either teleclaude session ID or Agent session ID

        Returns:
            VoiceConfig or None if no voice assigned
        """
        async with self._session() as db_session:
            row = await db_session.get(db_models.VoiceAssignment, voice_id)
            if not row:
                return None
            return VoiceConfig(
                name=row.voice_name,
                elevenlabs_id=row.elevenlabs_id or "",
                macos_voice=row.macos_voice or "",
                openai_voice=row.openai_voice or "",
            )

    async def cleanup_stale_voice_assignments(self, max_age_days: int = 7) -> int:
        """Delete voice assignments older than max_age_days.

        Args:
            max_age_days: Maximum age in days before cleanup (default: 7)

        Returns:
            Number of records deleted
        """
        from sqlalchemy import text

        stmt = text("DELETE FROM voice_assignments WHERE assigned_at < datetime('now', :delta || ' days')").bindparams(
            delta=f"-{max_age_days}"
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            deleted = result.rowcount or 0
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
        async with self._session() as db_session:
            row = await db_session.get(db_models.AgentAvailability, agent)
            if not row:
                return None
            unavailable_until = row.unavailable_until
            if unavailable_until is not None:
                parsed_until = self._parse_iso_datetime(unavailable_until)
                if parsed_until and parsed_until < datetime.now(timezone.utc):
                    row.available = 1
                    row.unavailable_until = None
                    row.reason = None
                    db_session.add(row)
                    await db_session.commit()
                    return {
                        "available": True,
                        "unavailable_until": None,
                        "reason": None,
                    }
            return {
                "available": bool(row.available) if row.available is not None else False,
                "unavailable_until": unavailable_until,
                "reason": row.reason,
            }

    @staticmethod
    def _parse_iso_datetime(value: str) -> datetime | None:
        """Parse ISO datetime with support for trailing 'Z'."""
        parsed = parse_iso_datetime(value)
        if parsed is None:
            logger.warning("Failed to parse unavailable_until value: %s", value)
        return parsed

    async def mark_agent_unavailable(self, agent: str, unavailable_until: str, reason: str) -> None:
        """Mark an agent as unavailable until a specified time.

        Args:
            agent: Agent name (e.g., "claude", "gemini", "codex")
            unavailable_until: ISO timestamp when agent becomes available again
            reason: Reason for unavailability (e.g., "quota_exhausted", "rate_limited")
        """
        async with self._session() as db_session:
            row = await db_session.get(db_models.AgentAvailability, agent)
            if row is None:
                row = db_models.AgentAvailability(
                    agent=agent,
                    available=0,
                    unavailable_until=unavailable_until,
                    reason=reason,
                )
            else:
                row.available = 0
                row.unavailable_until = unavailable_until
                row.reason = reason
            db_session.add(row)
            await db_session.commit()
        logger.info("Marked agent %s unavailable until %s (%s)", agent, unavailable_until, reason)

    async def mark_agent_available(self, agent: str) -> None:
        """Mark an agent as available immediately.

        Args:
            agent: Agent name (e.g., "claude", "gemini", "codex")
        """
        async with self._session() as db_session:
            row = await db_session.get(db_models.AgentAvailability, agent)
            if row is None:
                row = db_models.AgentAvailability(agent=agent, available=1)
            else:
                row.available = 1
                row.unavailable_until = None
                row.reason = None
            db_session.add(row)
            await db_session.commit()
        logger.info("Marked agent %s available", agent)

    async def clear_expired_agent_availability(self) -> int:
        """Reset agents whose unavailable_until time has passed.

        Returns:
            Number of agents reset to available
        """
        now = datetime.now(timezone.utc).isoformat()
        from sqlalchemy import text

        stmt = text(
            "UPDATE agent_availability SET available = 1, unavailable_until = NULL, reason = NULL "
            "WHERE unavailable_until IS NOT NULL AND unavailable_until < :now"
        ).bindparams(now=now)
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            cleared = result.rowcount or 0
        if cleared > 0:
            logger.info("Cleared availability for %d agents (TTL expired)", cleared)
        return cleared

    async def enqueue_hook_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
    ) -> int:
        """Persist a hook event in the outbox for durable delivery."""
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload)
        async with self._session() as db_session:
            row = db_models.HookOutbox(
                session_id=session_id,
                event_type=event_type,
                payload=payload_json,
                created_at=now,
                next_attempt_at=now,
                attempt_count=0,
            )
            db_session.add(row)
            await db_session.commit()
            await db_session.refresh(row)
            if row.id is None:
                raise RuntimeError("Failed to insert hook outbox row")
            return int(row.id)

    async def fetch_hook_outbox_batch(
        self,
        now_iso: str,
        limit: int,
        lock_cutoff_iso: str,
    ) -> list[HookOutboxRow]:
        """Fetch a batch of due hook events."""
        from sqlmodel import select

        stmt = (
            select(db_models.HookOutbox)
            .where(db_models.HookOutbox.delivered_at.is_(None))
            .where(db_models.HookOutbox.next_attempt_at <= now_iso)
            .where((db_models.HookOutbox.locked_at.is_(None)) | (db_models.HookOutbox.locked_at <= lock_cutoff_iso))
            .order_by(db_models.HookOutbox.created_at)
            .limit(limit)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            rows = result.all()
            return [
                HookOutboxRow(
                    id=row.id or 0,
                    session_id=row.session_id,
                    event_type=row.event_type,
                    payload=row.payload,
                    attempt_count=row.attempt_count or 0,
                )
                for row in rows
            ]

    async def claim_hook_outbox(self, row_id: int, now_iso: str, lock_cutoff_iso: str) -> bool:
        """Claim a hook outbox row for processing."""
        from sqlalchemy import text

        stmt = text(
            "UPDATE hook_outbox SET locked_at = :now "
            "WHERE id = :row_id AND delivered_at IS NULL "
            "AND (locked_at IS NULL OR locked_at <= :cutoff)"
        ).bindparams(now=now_iso, row_id=row_id, cutoff=lock_cutoff_iso)
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def mark_hook_outbox_delivered(self, row_id: int, error: str | None = None) -> None:
        """Mark a hook outbox row delivered (optionally capturing last error)."""
        now = datetime.now(timezone.utc).isoformat()
        from sqlalchemy import text

        stmt = text(
            "UPDATE hook_outbox SET delivered_at = :now, last_error = :error, locked_at = NULL WHERE id = :row_id"
        ).bindparams(now=now, error=error, row_id=row_id)
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def mark_hook_outbox_failed(
        self,
        row_id: int,
        attempt_count: int,
        next_attempt_at: str,
        error: str,
    ) -> None:
        """Record a hook outbox failure and schedule a retry."""
        from sqlalchemy import text

        stmt = text(
            "UPDATE hook_outbox SET attempt_count = :attempt, next_attempt_at = :next_attempt, "
            "last_error = :error, locked_at = NULL WHERE id = :row_id"
        ).bindparams(
            attempt=attempt_count,
            next_attempt=next_attempt_at,
            error=error,
            row_id=row_id,
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()


def _field_query(field: str) -> str:
    """Build query to find session by direct column value."""
    return (
        f"SELECT session_id FROM sessions WHERE {field} = :value "
        "AND closed_at IS NULL ORDER BY last_activity DESC LIMIT 1"
    )


def _fetch_session_id_sync(db_path: str, query: str, value: object) -> str | None:
    """Sync helper for raw session_id queries.

    guard: allow-string-compare
    """
    from sqlalchemy import create_engine, text
    from sqlmodel import Session as SqlSession

    engine = create_engine(f"sqlite:///{db_path}")
    with SqlSession(engine) as session:
        session.exec(text("PRAGMA journal_mode = WAL"))
        session.exec(text("PRAGMA busy_timeout = 5000"))
        try:
            result = session.exec(text(query), {"value": value})
        except Exception as exc:  # noqa: BLE001 - Boundary DB operation
            if "no such table" in str(exc).lower():
                return None
            raise
        row = result.first()
        if row is None:
            return None
        if isinstance(row, tuple):
            return str(row[0])
        return str(row)


def get_session_id_by_field_sync(db_path: str, field: str, value: object) -> str | None:
    """Sync helper for lookups in standalone scripts (hook receiver, telec)."""
    return _fetch_session_id_sync(db_path, _field_query(field), value)


def get_session_id_by_tmux_name_sync(db_path: str, tmux_name: str) -> str | None:
    """Sync helper to find session_id by tmux session name."""
    query = (
        "SELECT session_id FROM sessions WHERE tmux_session_name = :value "
        "AND closed_at IS NULL ORDER BY last_activity DESC LIMIT 1"
    )
    return _fetch_session_id_sync(db_path, query, tmux_name)


# Module-level singleton instance (initialized on first import)
db = Db(config.database.path)
