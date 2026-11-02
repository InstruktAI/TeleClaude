"""Mixin: DbSessionsMixin."""

import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict

from instrukt_ai_logging import get_logger
from sqlalchemy import func, or_, text, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core.runtime_events import publish_session_source_change
from teleclaude.events.schemas.system import RuntimeSessionChange
from teleclaude.slug import replace_slug_token

from ...types.procedure_delivery import ProcedureSessionDeliveryInitialization
from .. import db_models
from ..models import JsonDict, OriginRevivalContext, RelayStatus, Session, SessionField, SessionLaunchIntent
from ..session_lifecycle import LifecycleTransition, LifecycleTransitionReason, transition_session
from ..session_startup import StartupHandoverState, encode_startup_intent
from ..session_status import SessionLifecycleStatus
from ._agent_status import (
    EMPTY_AGENT_STATUS_REASON,
    AgentStatusPersistenceMixin,
    encode_open_tool_calls,
)
from ._control_delivery import initialize_procedure_delivery_in_transaction
from ._pending_deletions import DbPendingDeletionsMixin
from ._session_retention import not_archive_record

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)
_RELAY_RECORD_FIELDS = frozenset({SessionField.RELAY_EXCHANGE.value})
_DIGEST_ONLY_UPDATES = ({"last_output_digest"}, {"last_projected_output_digest"})

_AGENT_STATUS_UPDATE_REFUSAL = "agent-status fields are owned by the agent-status transition seam"

_AGENT_STATUS_OWNED_FIELDS = frozenset(
    {
        "agent_status",
        "agent_status_reason",
        SessionField.AGENT_STATUS_SINCE.value,
        SessionField.RUNTIME_RUN_ID.value,
        SessionField.RUNTIME_TURN_ID.value,
        "runtime_activity_at",
        SessionField.OPEN_TOOL_CALLS.value,
        SessionField.AGENT_STATUS_VERSION.value,
        SessionField.TURN_NOTIFICATIONS_SENT.value,
    }
)


@dataclass(frozen=True)
class _AcceptanceBoundary:
    """What a session had recorded when one input was accepted: its input clock instant and turn identity."""

    input_at: datetime
    runtime_turn_id: str | None


def _is_unannounced_update(fields: set[str]) -> bool:
    """Whether an update is internal state the cluster is not told about.

    Output digests are routing dedupe state written very often; the relay
    exchange stays on the escalating computer.
    """
    return fields in _DIGEST_ONLY_UPDATES or fields <= _RELAY_RECORD_FIELDS


class _LifecycleTransitionFields(TypedDict):
    """Stored fields written together by the lifecycle persistence seam."""

    lifecycle_status: str
    lifecycle_transition_reason: str
    lifecycle_transitioned_at: datetime
    runtime_start_observed: NotRequired[bool]
    closed_at: NotRequired[datetime]


class DbSessionsMixin(AgentStatusPersistenceMixin, DbPendingDeletionsMixin):
    """Session persistence helpers and lifecycle state transitions."""

    async def create_session(
        self,
        computer_name: str,
        tmux_session_name: str,
        last_input_origin: str,
        title: str,
        role: str | None = None,
        job: str | None = None,
        company: str | None = None,
        project_path: str | None = None,
        subdir: str | None = None,
        config_subject: str | None = None,
        subject_owner: str | None = None,
        description: str | None = None,
        session_id: str | None = None,
        command: str | None = None,
        working_slug: str | None = None,
        initiator_session_id: str | None = None,
        initiator_computer: str | None = None,
        detached: bool = False,
        human_email: str | None = None,
        human_role: str | None = None,
        principal: str | None = None,
        lifecycle_status: str = "initializing",
        active_agent: str | None = None,
        thinking_mode: str | None = None,
        native_session_id: str | None = None,
        native_log_file: str | None = None,
        origin_metadata: JsonDict | None = None,
        startup_intent: SessionLaunchIntent | None = None,
        procedure_delivery: ProcedureSessionDeliveryInitialization | None = None,
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
            role: Optional catalog role the session carries (None for a human session)
            job: Optional instance identity (a scheduled job's name, an activation's procedure)
            company: Optional company slug this session operates the business of
            project_path: Base project path (no subdir)
            subdir: Optional subdirectory/worktree relative to project_path
            config_subject: Optional configuration declaration subject token
            description: Optional description (for AI-to-AI sessions)
            session_id: Optional explicit session ID (for AI-to-AI cross-computer sessions)
            working_slug: Optional slug of work item this session is working on
            initiator_session_id: Session ID of the AI that created this session (for AI-to-AI nesting)
            initiator_computer: Computer the initiator session lives on
            detached: Whether the session should render as a root node despite having an initiator
            human_email: Optional email of the human user
            human_role: Optional role of the human user
            active_agent: Agent name (claude, gemini, codex)
            thinking_mode: Thinking mode (fast, med, slow)
            native_session_id: Optional native agent session identifier
            native_log_file: Optional native transcript or log path
            origin_metadata: Optional root origin-metadata sections written with the row
            startup_intent: Optional launch intent recorded as the session's startup handover in the same write
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
            role=role,
            job=job,
            company=company,
            created_at=now,
            last_activity=now,
            project_path=project_path,
            subdir=subdir,
            config_subject=config_subject,
            subject_owner=subject_owner,
            description=description,
            command=command,
            working_slug=working_slug,
            initiator_session_id=initiator_session_id,
            initiator_computer=initiator_computer,
            detached=detached,
            human_email=human_email,
            human_role=human_role,
            principal=principal,
            lifecycle_status=lifecycle_status,
            active_agent=active_agent,
            thinking_mode=thinking_mode,
            native_session_id=native_session_id,
            native_log_file=native_log_file,
            origin_metadata=dict(origin_metadata) if origin_metadata else {},
        )

        # Serialize origin_metadata (accumulated platform sections, no "platform" key)
        origin_meta = dict(session.origin_metadata) if session.origin_metadata else {}

        db_row = db_models.Session(
            session_id=session.session_id,
            computer_name=session.computer_name,
            title=session.title,
            tmux_session_name=session.tmux_session_name,
            last_input_origin=session.last_input_origin,
            origin_metadata=json.dumps(origin_meta),
            role=session.role,
            job=session.job,
            company=session.company,
            created_at=session.created_at,
            last_activity=session.last_activity,
            project_path=session.project_path,
            subdir=session.subdir,
            config_subject=session.config_subject,
            subject_owner=session.subject_owner,
            description=session.description,
            command=session.command,
            working_slug=session.working_slug,
            initiator_session_id=session.initiator_session_id,
            initiator_computer=session.initiator_computer,
            detached=session.detached,
            human_email=session.human_email,
            human_role=session.human_role,
            principal=session.principal,
            lifecycle_status=session.lifecycle_status,
            runtime_start_observed=session.runtime_start_observed,
            runtime_activity_at=session.runtime_activity_at,
            agent_status=session.agent_status.value,
            agent_status_reason=(
                session.agent_status_reason.value if session.agent_status_reason else EMPTY_AGENT_STATUS_REASON
            ),
            agent_status_since=session.agent_status_since,
            open_tool_calls=encode_open_tool_calls(session.open_tool_calls),
            lifecycle_transitioned_at=session.created_at,
            lifecycle_transition_reason="created",
            active_agent=session.active_agent,
            thinking_mode=session.thinking_mode,
            native_session_id=session.native_session_id,
            native_log_file=session.native_log_file,
        )
        async with self._session() as db_session:
            db_session.add(db_row)
            if startup_intent is not None:
                # The handover references the session row, so the parent insert is
                # flushed first; both commit together or not at all.
                await db_session.flush()
                db_session.add(
                    db_models.SessionStartupHandover(
                        session_id=session.session_id,
                        launch_intent_json=encode_startup_intent(startup_intent),
                        state=StartupHandoverState.ACCEPTED.value,
                        updated_at=now.isoformat(),
                    )
                )
            if procedure_delivery is not None:
                await initialize_procedure_delivery_in_transaction(
                    db_session,
                    session_id=session.session_id,
                    initialized_at=now.isoformat(),
                    delivery=procedure_delivery,
                )
            await db_session.commit()

        if emit_session_started:
            await publish_session_source_change(session_id, RuntimeSessionChange.CREATED)

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
            conditions = [column == value, db_models.Session.closed_at.is_(None)]
            if not include_initializing:
                conditions.append(db_models.Session.lifecycle_status == "active")
            result = await db_session.exec(select(db_models.Session).where(*conditions))
            row = result.first()
            if not row:
                return None
            return self._to_core_session(row)

    async def get_origin_revival_context_for_native_session(
        self, native_session_id: str
    ) -> OriginRevivalContext | None:
        """Return the originating identity for a native session id.

        Selects the earliest-created session row bound to ``native_session_id``,
        including closed rows, so the recorded project and title survive session
        closure and resist pollution from later caller-cwd revive rows. Returns
        ``None`` when no row records the native id.
        """
        if not native_session_id:
            return None
        async with self._session() as db_session:
            result = await db_session.exec(
                select(db_models.Session)
                .where(db_models.Session.native_session_id == native_session_id)
                .order_by(db_models.Session.created_at.asc())
            )
            row = result.first()
            if row is None:
                return None
            return OriginRevivalContext(project_path=row.project_path, subdir=row.subdir, title=row.title)

    async def find_open_sessions_bound_to_todo(
        self, *, old_slug: str, cwd: str, exclude_session_id: str | None = None
    ) -> list[db_models.Session]:
        """Return open session rows that still point at the source todo."""
        worktree_subdir = f"trees/{old_slug}"
        stmt = (
            select(db_models.Session)
            .where(db_models.Session.closed_at.is_(None))
            .where(db_models.Session.lifecycle_status != "closed")
            .where(
                or_(
                    db_models.Session.working_slug == old_slug,
                    (db_models.Session.project_path == cwd) & (db_models.Session.subdir == worktree_subdir),
                )
            )
        )
        if exclude_session_id is not None:
            stmt = stmt.where(db_models.Session.session_id != exclude_session_id)
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return list(result.all())

    async def rewrite_session_todo_refs(self, *, old_slug: str, new_slug: str, cwd: str) -> int:
        """Rewrite retained session references from old slug to new slug.

        Also reconciles the `title` of every bound session so the old slug
        token does not survive as a stale fragment alongside the new slug.
        """
        worktree_subdir = f"trees/{old_slug}"
        new_worktree_subdir = f"trees/{new_slug}"
        async with self._session() as db_session:
            bound = await db_session.exec(
                select(db_models.Session.session_id, db_models.Session.title).where(
                    db_models.Session.working_slug == old_slug
                )
            )
            title_updates = [
                (session_id, replace_slug_token(title, old_slug, new_slug))
                for session_id, title in bound.all()
                if title
            ]
            first = await db_session.exec(
                update(db_models.Session)
                .where(db_models.Session.working_slug == old_slug)
                .values(working_slug=new_slug)
            )
            for session_id, new_title in title_updates:
                await db_session.exec(
                    update(db_models.Session).where(db_models.Session.session_id == session_id).values(title=new_title)
                )
            second = await db_session.exec(
                update(db_models.Session)
                .where(db_models.Session.project_path == cwd)
                .where(db_models.Session.subdir == worktree_subdir)
                .values(subdir=new_worktree_subdir)
            )
            await db_session.commit()
            return (first.rowcount or 0) + (second.rowcount or 0)

    async def list_sessions(
        self,
        computer_name: str | None = None,
        last_input_origin: str | None = None,
        include_closed: bool = False,
        include_initializing: bool = False,
        include_headless: bool = False,
        all_open: bool = False,
        initiator_session_id: str | None = None,
    ) -> list[Session]:
        """List sessions with optional filters.

        Args:
            computer_name: Filter by computer name
            last_input_origin: Filter by last input origin (InputOrigin.*.value)
            include_closed: Include closed sessions when True
            include_initializing: Include initializing sessions when True
            include_headless: Include headless sessions when True
            all_open: Include every session without a close timestamp
            initiator_session_id: Filter to sessions spawned by this session

        Returns:
            List of Session objects
        """
        if all_open and (include_closed or include_initializing or include_headless):
            raise ValueError("all_open cannot be combined with lifecycle inclusion flags")

        started_at = time.perf_counter()
        logger.trace(
            "[PERF] list_sessions start computer=%s origin=%s include_closed=%s "
            "include_initializing=%s include_headless=%s all_open=%s initiator=%s",
            computer_name,
            last_input_origin,
            include_closed,
            include_initializing,
            include_headless,
            all_open,
            initiator_session_id,
        )
        stmt = select(db_models.Session).where(db_models.Session.deleted_at.is_(None), not_archive_record())
        if not include_closed:
            stmt = stmt.where(db_models.Session.closed_at.is_(None))
        # ``all_open`` is the authoritative sessions projection. Other callers
        # retain the narrower lifecycle selection they explicitly requested.
        if not include_closed and not all_open:
            allowed = [db_models.Session.lifecycle_status == "active"]
            if include_initializing:
                allowed.append(db_models.Session.lifecycle_status == "initializing")
            if include_headless:
                allowed.append(db_models.Session.lifecycle_status == "headless")
            stmt = stmt.where(or_(*allowed))
        elif include_closed and not include_headless:
            stmt = stmt.where(db_models.Session.lifecycle_status != "headless")
        if computer_name:
            stmt = stmt.where(db_models.Session.computer_name == computer_name)
        if last_input_origin:
            stmt = stmt.where(db_models.Session.last_input_origin == last_input_origin)
        if initiator_session_id:
            stmt = stmt.where(db_models.Session.initiator_session_id == initiator_session_id)
        stmt = stmt.order_by(db_models.Session.last_activity.desc())
        stmt_built_dt = time.perf_counter() - started_at
        logger.trace(
            "[PERF] list_sessions stmt_built dt=%.3f computer=%s initiator=%s",
            stmt_built_dt,
            computer_name,
            initiator_session_id,
        )

        session_open_started_at = time.perf_counter()
        async with self._session() as db_session:
            session_open_dt = time.perf_counter() - session_open_started_at
            logger.trace(
                "[PERF] list_sessions db_session_open dt=%.3f computer=%s initiator=%s",
                session_open_dt,
                computer_name,
                initiator_session_id,
            )
            exec_started_at = time.perf_counter()
            result = await db_session.exec(stmt)
            exec_dt = time.perf_counter() - exec_started_at
            logger.trace(
                "[PERF] list_sessions exec dt=%.3f computer=%s initiator=%s",
                exec_dt,
                computer_name,
                initiator_session_id,
            )
            rows_started_at = time.perf_counter()
            rows = result.all()
            rows_dt = time.perf_counter() - rows_started_at
            logger.trace(
                "[PERF] list_sessions rows_materialized dt=%.3f count=%d computer=%s initiator=%s",
                rows_dt,
                len(rows),
                computer_name,
                initiator_session_id,
            )
            convert_started_at = time.perf_counter()
            sessions = [self._to_core_session(row) for row in rows]
            convert_dt = time.perf_counter() - convert_started_at
            total_dt = time.perf_counter() - started_at
            logger.trace(
                "[PERF] list_sessions convert dt=%.3f total=%.3f count=%d computer=%s initiator=%s",
                convert_dt,
                total_dt,
                len(sessions),
                computer_name,
                initiator_session_id,
            )
            if total_dt >= 5.0:
                logger.warning(
                    (
                        "list_sessions was slow: total=%.3fs stmt=%.3fs session_open=%.3fs exec=%.3fs "
                        "rows=%.3fs convert=%.3fs count=%d computer=%s include_headless=%s "
                        "include_closed=%s include_initializing=%s all_open=%s initiator=%s"
                    ),
                    total_dt,
                    stmt_built_dt,
                    session_open_dt,
                    exec_dt,
                    rows_dt,
                    convert_dt,
                    len(sessions),
                    computer_name,
                    include_headless,
                    include_closed,
                    include_initializing,
                    all_open,
                    initiator_session_id,
                )
            return sessions

    async def update_session(
        self,
        session_id: str,
        **fields: object,
    ) -> Session | None:
        """Update session fields through the ordinary source mutation path."""
        return await self._update_session(session_id, None, **fields)

    async def update_session_if_runtime_run(
        self,
        session_id: str,
        expected_runtime_run_id: str,
        **fields: object,
    ) -> Session | None:
        """Update session fields only while their managed launch still owns the row."""
        return await self._update_session(session_id, expected_runtime_run_id, **fields)

    async def update_session_if_acceptance_unchanged(
        self,
        session_id: str,
        *,
        accepted_input_at: datetime,
        accepted_runtime_turn_id: str | None,
        **fields: object,
    ) -> Session | None:
        """Update session fields only while nothing newer than one accepted input is recorded.

        The write applies when, at the write itself, the session's input clock is no later than
        ``accepted_input_at`` and its runtime turn identity is absent or still ``accepted_runtime_turn_id``.
        Newer accepted input advances the clock and a native turn mints a turn identity, so a match means
        neither happened since that acceptance. Returns ``None`` when the row did not match.
        """
        boundary = _AcceptanceBoundary(
            input_at=self._coerce_datetime(accepted_input_at) or accepted_input_at,
            runtime_turn_id=accepted_runtime_turn_id,
        )
        return await self._update_session(session_id, None, boundary, **fields)

    async def _update_session(
        self,
        session_id: str,
        expected_runtime_run_id: str | None,
        acceptance_boundary: _AcceptanceBoundary | None = None,
        **fields: object,
    ) -> Session | None:
        """Update session fields and handle events.

        A nonempty payload returns the resulting session or None for a missing
        row. An empty payload returns None without looking up the row.

        Args:
            session_id: Session ID
            **fields: Fields to update (title, status, tmux_size, etc.)
        """
        if "lifecycle_status" in fields:
            raise ValueError("lifecycle_status is owned by the lifecycle transition seam")
        if _AGENT_STATUS_OWNED_FIELDS & {str(key.value if isinstance(key, SessionField) else key) for key in fields}:
            raise ValueError(_AGENT_STATUS_UPDATE_REFUSAL)
        updates: dict[str, object] = {}  # guard: loose-dict - Dynamic update payload
        result: Session | None = None

        if fields:
            async with self._session() as db_session:
                row = await db_session.get(db_models.Session, session_id)
                if not row:
                    logger.warning("Attempted to update non-existent session: %s", session_id)
                    return None
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

                    if attr_name in {
                        "created_at",
                        "last_activity",
                        "lifecycle_transitioned_at",
                        "closed_at",
                        "deleted_at",
                        "last_message_sent_at",
                        "last_input_written_at",
                        "last_projected_at",
                        "last_output_stop_at",
                        "last_output_at",
                        "last_tool_done_at",
                        "last_tool_use_at",
                        "last_checkpoint_at",
                        "last_agent_stop_at",
                        "last_agent_idle_at",
                    }:
                        if value is None:
                            if current_val is not None:
                                updates[attr_name] = None
                        else:
                            parsed = self._coerce_datetime(value)
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

                    if not await self._persist_session_updates(
                        db_session,
                        row,
                        session_id,
                        updates,
                        expected_runtime_run_id,
                        acceptance_boundary,
                    ):
                        return None

                result = self._to_core_session(row)

        # Digest updates are internal dedupe state for output routing and can occur
        # very frequently. Emitting SESSION_UPDATED for digest-only writes creates
        # unnecessary event fan-out and cache churn.
        if updates and _is_unannounced_update(set(updates)):
            logger.trace("Skipping SESSION_UPDATED emit for internal-only update: %s", session_id)
            return result

        if not updates:
            logger.trace("Skipping redundant update for session %s", session_id)
            return result

        # Emit SESSION_UPDATED event for state changes (title, status, etc.).
        # Activity events (user input, tool use, agent output) flow through AgentActivityEvent.
        await publish_session_source_change(
            session_id,
            RuntimeSessionChange.UPDATED,
            changed_fields=tuple(updates),
        )
        return result

    async def _persist_session_updates(
        self,
        db_session: SqlAsyncSession,
        row: db_models.Session,
        session_id: str,
        updates: Mapping[str, object],
        expected_runtime_run_id: str | None,
        acceptance_boundary: _AcceptanceBoundary | None = None,
    ) -> bool:
        """Apply normalized session fields, conditional on the managed launch or acceptance boundary when supplied."""
        if expected_runtime_run_id is None and acceptance_boundary is None:
            for key, value in updates.items():
                setattr(row, key, value)
            db_session.add(row)
            await db_session.commit()
            return True

        conditions = [db_models.Session.session_id == session_id]
        if expected_runtime_run_id is not None:
            conditions.append(db_models.Session.runtime_run_id == expected_runtime_run_id)
        if acceptance_boundary is not None:
            conditions.append(
                or_(
                    db_models.Session.last_message_sent_at.is_(None),
                    db_models.Session.last_message_sent_at <= acceptance_boundary.input_at,
                )
            )
            conditions.append(
                or_(
                    db_models.Session.runtime_turn_id.is_(None),
                    db_models.Session.runtime_turn_id == acceptance_boundary.runtime_turn_id,
                )
            )
        statement = update(db_models.Session).where(*conditions).values(updates).returning(db_models.Session.session_id)
        conditional_result = await db_session.exec(statement)
        if not conditional_result.all():
            return False
        await db_session.commit()
        await db_session.refresh(row)
        return True

    async def persist_lifecycle_transition(
        self,
        session_id: str,
        *,
        target: str,
        reason: str,
        transitioned_at: datetime,
        runtime_start_observed: bool | None = None,
        closed_at: datetime | None = None,
        expected_runtime_run_id: str | None = None,
    ) -> bool:
        """Persist the lifecycle owner's complete transition record atomically."""
        updates: _LifecycleTransitionFields = {
            "lifecycle_status": target,
            "lifecycle_transition_reason": reason,
            "lifecycle_transitioned_at": transitioned_at,
        }
        if runtime_start_observed is not None:
            updates["runtime_start_observed"] = runtime_start_observed
        if closed_at is not None:
            updates["closed_at"] = closed_at
        async with self._session() as db_session:
            if expected_runtime_run_id is None:
                row = await db_session.get(db_models.Session, session_id)
                if row is None:
                    raise ValueError(f"Cannot transition missing session {session_id}")
                for key, value in updates.items():
                    setattr(row, key, value)
                db_session.add(row)
                await db_session.commit()
            else:
                statement = (
                    update(db_models.Session)
                    .where(
                        db_models.Session.session_id == session_id,
                        db_models.Session.runtime_run_id == expected_runtime_run_id,
                    )
                    .values(**updates)
                    .returning(db_models.Session.session_id)
                )
                result = await db_session.exec(statement)
                rows = result.all()
                if not rows:
                    return False
                await db_session.commit()
        logger.info(
            "session_lifecycle_transition_committed",
            session_id=session_id,
            lifecycle_status=target,
            lifecycle_transition_reason=reason,
        )
        await publish_session_source_change(
            session_id,
            RuntimeSessionChange.UPDATED,
            changed_fields=tuple(updates),
        )
        return True

    async def close_session(self, session_id: str) -> None:
        """Mark a session as closed without deleting it."""
        session = await self.get_session(session_id)
        if not session:
            logger.warning("Attempted to close non-existent session: %s", session_id)
            return
        if session.closed_at:
            return
        await transition_session(
            self,
            session_id,
            LifecycleTransition(
                SessionLifecycleStatus.CLOSED,
                LifecycleTransitionReason.CLOSED,
                closed_at=datetime.now(UTC),
            ),
        )
        await publish_session_source_change(session_id, RuntimeSessionChange.CLOSED)

    async def update_origin_metadata(
        self,
        session_id: str,
        platform: str,
        field_updates: dict[str, object] | None = None,  # guard: loose-dict - Per-platform field delta
    ) -> None:
        """Atomic merge-write of origin_metadata for a session.

        ``field_updates`` carries **field deltas only — never a materialized
        section snapshot.** The statement is atomic, but a caller that reads the
        section, mutates it, and submits the whole thing performs a
        read-modify-write around it: every unchanged key travels with a value
        from that snapshot, so a concurrent writer's change to any of them is
        silently reverted. Passing only the fields this call changes is what
        makes the atomicity mean anything.

        JSON Merge Patch semantics apply within the platform section:
        - absent keys: leave existing values untouched
        - non-None values: set/overwrite
        - None values: delete the key from the stored section
        """
        patch: dict[str, object] = {}  # guard: loose-dict - JSON merge patch
        if field_updates is not None:
            patch[platform] = field_updates

        async with self._session() as db_session:
            # '' || strips the JSON subtype so the column stays plain TEXT.
            stmt = text(  # guard: raw-sql - atomic json_patch eliminates race
                "UPDATE sessions SET origin_metadata = '' || json_patch("
                "  COALESCE(origin_metadata, '{}'),"
                "  json(:patch_json)"
                ") WHERE session_id = :session_id"
            ).bindparams(patch_json=json.dumps(patch), session_id=session_id)
            await db_session.exec(stmt)
            await db_session.commit()

    async def update_last_activity(self, session_id: str) -> None:
        """Update last activity timestamp for session.

        Args:
            session_id: Session ID
        """
        await self.update_session(session_id, last_activity=datetime.now(UTC))

    async def count_sessions(self, computer_name: str | None = None) -> int:
        """Count sessions with optional filters.

        Args:
            computer_name: Filter by computer name

        Returns:
            Number of sessions
        """
        stmt = select(func.count()).select_from(db_models.Session)
        if computer_name:
            stmt = stmt.where(db_models.Session.computer_name == computer_name)

        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            count = result.one()
            return int(count)

    async def get_sessions_by_origin_metadata(
        self,
        adapter_type: str,
        metadata_key: str,
        metadata_value: object,
        include_closed: bool = False,
    ) -> list[Session]:
        """Get sessions by origin_metadata field.

        Finds sessions that HAVE the specified platform metadata, regardless of
        which adapter was the entry point.

        Args:
            adapter_type: Platform key whose section to search
            metadata_key: JSON key within the platform section
            metadata_value: Value to match

        Returns:
            Matching sessions, most recently created first
        """
        # SQLite JSON path: $.{adapter_type}.{metadata_key}
        json_path = f"$.{adapter_type}.{metadata_key}"
        json_expr = func.json_extract(db_models.Session.origin_metadata, json_path)

        # Handle int values that may be stored as strings in JSON
        if isinstance(metadata_value, int):
            condition = or_(json_expr == metadata_value, json_expr == str(metadata_value))
        else:
            condition = json_expr == metadata_value

        stmt = select(db_models.Session).where(condition)
        if not include_closed:
            stmt = stmt.where(db_models.Session.closed_at.is_(None))
        # Newest first, so the first match is a conversation's latest session.
        stmt = stmt.order_by(db_models.Session.created_at.desc())

        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            rows = result.all()
            return [self._to_core_session(row) for row in rows]

    async def get_sessions_active_since(self, cutoff: datetime) -> list[Session]:
        """Return open sessions with last_activity at or after cutoff.

        Used by adapter cadence loops to find sessions needing output delivery.
        SQLAlchemy stores datetime as space-separated (no T), so we match
        that format for string comparison in SQLite.
        """
        # Strip timezone and use space-separated format to match SQLite storage.
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S.%f")
        stmt = (
            select(db_models.Session)
            .where(db_models.Session.closed_at.is_(None))
            .where(db_models.Session.last_activity >= cutoff_str)
        )
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
        stmt = select(db_models.Session).order_by(db_models.Session.last_activity.desc())
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            rows = result.all()
            return [self._to_core_session(row) for row in rows]

    async def list_relaying_sessions(self) -> list[Session]:
        """Open sessions whose escalation relay is active, in any lifecycle state."""
        stmt = select(db_models.Session).where(
            db_models.Session.closed_at.is_(None),
            db_models.Session.relay_status == RelayStatus.ACTIVE.value,
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return [self._to_core_session(row) for row in result.all()]
