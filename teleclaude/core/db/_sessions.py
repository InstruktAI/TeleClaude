"""Mixin: DbSessionsMixin."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from instrukt_ai_logging import get_logger

from teleclaude.core.event_bus import event_bus

from .. import db_models
from ..events import SessionLifecycleContext, SessionUpdatedContext, TeleClaudeEvents
from ..models import Session, SessionAdapterMetadata, SessionField, SessionMetadata

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class DbSessionsMixin:
    async def create_session(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # Database insert requires all session fields
        self,
        computer_name: str,
        tmux_session_name: str,
        last_input_origin: str,
        title: str,
        adapter_metadata: SessionAdapterMetadata | None = None,
        session_metadata: SessionMetadata | None = None,
        project_path: str | None = None,
        subdir: str | None = None,
        description: str | None = None,
        session_id: str | None = None,
        working_slug: str | None = None,
        initiator_session_id: str | None = None,
        human_email: str | None = None,
        human_role: str | None = None,
        principal: str | None = None,
        lifecycle_status: str = "active",
        active_agent: str | None = None,
        thinking_mode: str | None = None,
        emit_session_started: bool = True,
    ) -> Session:
        """Create a new session.

        All known fields must be provided at creation time so the row is
        complete before any event is emitted.

        Args:
            computer_name: Name of the computer
            tmux_session_name: Name of tmux session
            last_input_origin: Last input origin (InputOrigin.*.value)
            title: Optional session title
            adapter_metadata: Optional adapter-specific metadata
            session_metadata: Optional generic JSON metadata (e.g. job details)
            project_path: Base project path (no subdir)
            subdir: Optional subdirectory/worktree relative to project_path
            description: Optional description (for AI-to-AI sessions)
            session_id: Optional explicit session ID (for AI-to-AI cross-computer sessions)
            working_slug: Optional slug of work item this session is working on
            initiator_session_id: Session ID of the AI that created this session (for AI-to-AI nesting)
            human_email: Optional email of the human user
            human_role: Optional role of the human user
            active_agent: Agent name (claude, gemini, codex)
            thinking_mode: Thinking mode (fast, med, slow)
            emit_session_started: If False, caller is responsible for emitting SESSION_STARTED.

        Returns:
            Created Session object
        """
        session_id = session_id or str(uuid.uuid4())
        now = datetime.now(UTC)

        session = Session(
            session_id=session_id,
            computer_name=computer_name,
            tmux_session_name=tmux_session_name,
            last_input_origin=last_input_origin,
            title=title or f"[{computer_name}] Untitled",
            adapter_metadata=adapter_metadata or SessionAdapterMetadata(),
            session_metadata=session_metadata,
            created_at=now,
            last_activity=now,
            project_path=project_path,
            subdir=subdir,
            description=description,
            working_slug=working_slug,
            initiator_session_id=initiator_session_id,
            human_email=human_email,
            human_role=human_role,
            principal=principal,
            lifecycle_status=lifecycle_status,
            active_agent=active_agent,
            thinking_mode=thinking_mode,
        )

        db_row = db_models.Session(
            session_id=session.session_id,
            computer_name=session.computer_name,
            title=session.title,
            tmux_session_name=session.tmux_session_name,
            last_input_origin=session.last_input_origin,
            adapter_metadata=self._serialize_adapter_metadata(session.adapter_metadata),
            session_metadata=self._serialize_session_metadata(session.session_metadata),
            created_at=session.created_at,
            last_activity=session.last_activity,
            project_path=session.project_path,
            subdir=session.subdir,
            description=session.description,
            working_slug=session.working_slug,
            initiator_session_id=session.initiator_session_id,
            human_email=session.human_email,
            human_role=session.human_role,
            principal=session.principal,
            lifecycle_status=session.lifecycle_status,
            active_agent=session.active_agent,
            thinking_mode=session.thinking_mode,
        )
        async with self._session() as db_session:
            db_session.add(db_row)
            await db_session.commit()

        if emit_session_started:
            event_bus.emit(
                TeleClaudeEvents.SESSION_STARTED,
                SessionLifecycleContext(session_id=session_id),
            )

        return session

    async def create_headless_session(
        self,
        *,
        session_id: str,
        computer_name: str,
        last_input_origin: str,
        title: str,
        active_agent: str | None,
        native_session_id: str | None,
        native_log_file: str | None,
        project_path: str | None,
        subdir: str | None,
        human_role: str,
    ) -> Session:
        """Create a headless session (no tmux)."""
        now = datetime.now(UTC)
        tmux_session_name = ""

        session = Session(
            session_id=session_id,
            computer_name=computer_name,
            tmux_session_name=tmux_session_name,
            last_input_origin=last_input_origin,
            title=title,
            adapter_metadata=SessionAdapterMetadata(),
            created_at=now,
            last_activity=now,
            project_path=project_path,
            subdir=subdir,
            description=None,
            working_slug=None,
            initiator_session_id=None,
            human_role=human_role,
            lifecycle_status="headless",
            active_agent=active_agent,
            native_session_id=native_session_id,
            native_log_file=native_log_file,
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
            human_role=session.human_role,
            lifecycle_status=session.lifecycle_status,
            active_agent=session.active_agent,
            native_session_id=session.native_session_id,
            native_log_file=session.native_log_file,
        )
        async with self._session() as db_session:
            db_session.add(db_row)
            await db_session.commit()

        return session

    async def get_session(self, session_id: str) -> Session | None:
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

    async def get_session_field(self, session_id: str, field: str) -> object | None:
        """Get a single field from a session by ID.

        Args:
            session_id: Session ID
            field: Field name (column)

        Returns:
            Field value or None if session not found
        """
        column = getattr(db_models.Session, field, None)
        if column is None:
            return None
        async with self._session() as db_session:
            from sqlmodel import select

            result = await db_session.exec(select(column).where(db_models.Session.session_id == session_id))
            return result.first()

    async def get_session_by_field(
        self, field: str, value: object, *, include_initializing: bool = False
    ) -> Session | None:
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
        computer_name: str | None = None,
        last_input_origin: str | None = None,
        include_closed: bool = False,
        include_initializing: bool = False,
        include_headless: bool = False,
        initiator_session_id: str | None = None,
    ) -> list[Session]:
        """List sessions with optional filters.

        Args:
            computer_name: Filter by computer name
            last_input_origin: Filter by last input origin (InputOrigin.*.value)
            include_closed: Include closed sessions when True
            include_headless: Include headless sessions (standalone, no tmux) when True
            initiator_session_id: Filter to sessions spawned by this session

        Returns:
            List of Session objects
        """
        from sqlalchemy import or_
        from sqlmodel import select

        stmt = select(db_models.Session)
        if not include_closed:
            stmt = stmt.where(db_models.Session.closed_at.is_(None))
        # Lifecycle filter: by default only "active" sessions are returned.
        # include_initializing adds non-active statuses; include_headless adds "headless"
        # (standalone sessions with no tmux, used for TTS/summarization).
        # When include_closed is set, skip lifecycle filtering to allow closed sessions through.
        if not include_initializing and not include_closed:
            allowed = [db_models.Session.lifecycle_status == "active"]
            if include_headless:
                allowed.append(db_models.Session.lifecycle_status == "headless")
            stmt = stmt.where(or_(*allowed))
        elif not include_headless:
            stmt = stmt.where(db_models.Session.lifecycle_status != "headless")
        if computer_name:
            stmt = stmt.where(db_models.Session.computer_name == computer_name)
        if last_input_origin:
            stmt = stmt.where(db_models.Session.last_input_origin == last_input_origin)
        if initiator_session_id:
            stmt = stmt.where(db_models.Session.initiator_session_id == initiator_session_id)
        stmt = stmt.order_by(db_models.Session.last_activity.desc())

        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            rows = result.all()
            return [self._to_core_session(row) for row in rows]

    async def update_session(
        self,
        session_id: str,
        **fields: object,
    ) -> Session | None:
        """Update session fields and handle events.

        Args:
            session_id: Session ID
            **fields: Fields to update (title, status, tmux_size, etc.)
        """
        updates: dict[str, object] = {}  # guard: loose-dict - Dynamic update payload

        if fields:
            async with self._session() as db_session:
                row = await db_session.get(db_models.Session, session_id)
                if not row:
                    logger.warning("Attempted to update non-existent session: %s", session_id)
                    return

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

                    # Special handling for adapter_metadata: always update if provided
                    # to ensure nested flag changes (like output_suppressed) are persisted.
                    if attr_name == "adapter_metadata":
                        serialized = self._serialize_adapter_metadata(value)
                        updates[attr_name] = serialized
                        continue

                    if attr_name in {
                        "created_at",
                        "last_activity",
                        "closed_at",
                        "last_message_sent_at",
                        "last_output_at",
                        "last_tool_done_at",
                        "last_tool_use_at",
                        "last_checkpoint_at",
                    }:
                        if value is None:
                            if current_val is not None:
                                updates[attr_name] = None
                        else:
                            parsed = self._parse_iso_datetime(value)
                            if parsed and current_val != parsed:
                                updates[attr_name] = parsed
                        continue
                    if current_val != value:
                        updates[attr_name] = value

                if updates:
                    now = datetime.now(UTC)
                    if (
                        SessionField.LAST_MESSAGE_SENT.value in updates
                        and SessionField.LAST_MESSAGE_SENT_AT.value not in updates
                    ):
                        updates[SessionField.LAST_MESSAGE_SENT_AT.value] = now
                    if (
                        SessionField.LAST_OUTPUT_RAW.value in updates
                        and SessionField.LAST_OUTPUT_AT.value not in updates
                    ):
                        updates[SessionField.LAST_OUTPUT_AT.value] = now
                        summary_val = updates.get(SessionField.LAST_OUTPUT_RAW.value)
                        summary_len = len(str(summary_val)) if summary_val is not None else 0
                        logger.debug(
                            "Summary updated: session=%s len=%d",
                            session_id,
                            summary_len,
                        )

                    for key, value in updates.items():
                        setattr(row, key, value)
                    db_session.add(row)
                    await db_session.commit()

        # Digest updates are internal dedupe state for output routing and can occur
        # very frequently. Emitting SESSION_UPDATED for digest-only writes creates
        # unnecessary event fan-out and cache churn.
        if set(updates) == {"last_output_digest"}:
            logger.trace("Skipping SESSION_UPDATED emit for digest-only update: %s", session_id)
            return

        if not updates:
            logger.trace("Skipping redundant update for session %s", session_id)
            return

        # Emit SESSION_UPDATED event for state changes (title, status, etc.).
        # Activity events (user input, tool use, agent output) flow through AgentActivityEvent.
        event_bus.emit(
            TeleClaudeEvents.SESSION_UPDATED,
            SessionUpdatedContext(session_id=session_id, updated_fields=updates),
        )

    async def close_session(self, session_id: str) -> None:
        """Mark a session as closed without deleting it."""
        session = await self.get_session(session_id)
        if not session:
            logger.warning("Attempted to close non-existent session: %s", session_id)
            return
        if session.closed_at:
            return
        await self.update_session(
            session_id,
            closed_at=datetime.now(UTC),
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
        await self.update_session(session_id, last_activity=datetime.now(UTC))

    # State management functions (DB-backed via ux_state)

    async def get_output_message_id(self, session_id: str) -> str | None:
        """Get output message ID for session.

        Args:
            session_id: Session identifier

        Returns:
            Message ID of output message, or None if not set
        """
        session = await self.get_session(session_id)
        return session.output_message_id if session else None

    async def set_output_message_id(self, session_id: str, message_id: str | None) -> None:
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
                session_id,
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
        logger.debug("Deleted session %s from database", session_id)

        if session:
            event_bus.emit(
                TeleClaudeEvents.SESSION_CLOSED,
                SessionLifecycleContext(session_id=session_id),
            )

    async def count_sessions(self, computer_name: str | None = None) -> int:
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
        which adapter was the entry point. This enables any UI adapter to find
        sessions it has channels for regardless of the entry point.

        Args:
            adapter_type: Adapter type whose metadata to search
            metadata_key: JSON key to search in adapter_metadata
            metadata_value: Value to match

        Returns:
            List of matching sessions
        """
        from sqlalchemy import func, or_
        from sqlmodel import select

        # SQLite JSON path: $.{adapter_type}.{metadata_key}
        json_path = f"$.{adapter_type}.{metadata_key}"
        json_expr = func.json_extract(db_models.Session.adapter_metadata, json_path)

        # Handle int values that may be stored as strings in JSON
        if isinstance(metadata_value, int):
            condition = or_(json_expr == metadata_value, json_expr == str(metadata_value))
        else:
            condition = json_expr == metadata_value

        stmt = select(db_models.Session).where(condition)
        if not include_closed:
            stmt = stmt.where(db_models.Session.closed_at.is_(None))

        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            rows = result.all()
            return [self._to_core_session(row) for row in rows]

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
        # Exclude headless sessions (standalone TTS/summarization, no tmux).
        stmt = stmt.where(db_models.Session.lifecycle_status != "headless")
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
