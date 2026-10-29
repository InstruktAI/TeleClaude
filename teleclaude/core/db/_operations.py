"""Mixin: DbOperationsMixin."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from sqlalchemy import and_, delete, or_, update
from sqlmodel import select

from teleclaude.config.subject_resolution import SubjectResolutionError, resolve_config_subject
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.events.envelope import EventHomeMarker
from teleclaude.events.home_owner import EventHomeOwnerMarker
from teleclaude.services.project_catalog.ownership import ProjectOwnershipIndex, load_project_ownership_index

from .. import db_models
from .stores import DaemonStore

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

_NONTERMINAL_STATES = ("queued", "running")
_OPERATION_SUBJECT_BACKFILL_SETTING = "operation_subject_backfill_complete"
_OPERATION_SUBJECT_BACKFILL_COMPLETE = "true"
_OPERATION_SUBJECT_BACKFILL_FAILED = "operation_subject_backfill_failed"
_OPERATION_SUBJECT_BACKFILL_FINISHED = "operation_subject_backfill_finished"
_OPERATION_SUBJECT_BACKFILL_BATCH_SIZE = 500


def _operation_subject_facts(
    working_folder: str | None,
    ownership_index: ProjectOwnershipIndex | None = None,
) -> tuple[str, str]:
    """Resolve the subject and project owner recorded by one operation path."""
    if working_folder is None:
        return EventHomeMarker.NONE.value, EventHomeOwnerMarker.NONE.value
    path = Path(working_folder)
    try:
        subject = resolve_config_subject(path)
    except SubjectResolutionError:
        return EventHomeMarker.UNKNOWN.value, EventHomeOwnerMarker.UNRESOLVED.value
    if subject is None:
        return EventHomeMarker.NONE.value, EventHomeOwnerMarker.NONE.value
    if subject.kind is not ConfigSubjectKind.PROJECT:
        return subject.to_token(), EventHomeOwnerMarker.NONE.value

    ownership = (ownership_index or load_project_ownership_index()).for_path(path)
    if ownership is None:
        return subject.to_token(), EventHomeOwnerMarker.UNRESOLVED.value
    owner_identity = ownership.owner_identity()
    if owner_identity is None:
        owner = EventHomeOwnerMarker.OWNERLESS.value
    else:
        owner_kind, owner_slug = owner_identity
        owner = SubjectRef(ConfigSubjectKind(owner_kind.value), owner_slug).to_token()
    return subject.to_token(), owner


class DbOperationsMixin:
    """Durable operation persistence helpers."""

    async def create_operation(
        self,
        *,
        operation_id: str,
        kind: str,
        caller_session_id: str | None,
        client_request_id: str | None,
        cwd: str | None,
        session_project_path: str | None = None,
        slug: str | None,
        payload_json: str,
        state: str,
        caller_computer: str | None = None,
        caller_provenance_json: str | None = None,
    ) -> db_models.Operation:
        """Insert a durable operation row.

        ``caller_session_id``/``cwd`` are nullable: a command-backed operation
        with no recorded caller, or one with no todo checkout to root a ``cwd``
        in, is a submittable row — nothing is inferred to fill the gap.
        """
        now = datetime.now(UTC).isoformat()
        subject, subject_owner = _operation_subject_facts(cwd or session_project_path)
        row = db_models.Operation(
            operation_id=operation_id,
            kind=kind,
            caller_session_id=caller_session_id,
            caller_computer=caller_computer,
            caller_provenance_json=caller_provenance_json,
            client_request_id=client_request_id,
            cwd=cwd,
            session_project_path=session_project_path,
            subject=subject,
            subject_owner=subject_owner,
            slug=slug,
            payload_json=payload_json,
            state=state,
            created_at=now,
            updated_at=now,
            heartbeat_at=now,
            attempt_count=0,
        )
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            db_session.add(row)
            await db_session.commit()
            await db_session.refresh(row)
            return row

    async def list_operations_without_subject(self) -> list[tuple[str, str | None, str | None]]:
        """List operation paths whose visibility facts have not been recorded."""
        stmt = select(
            db_models.Operation.operation_id,
            db_models.Operation.cwd,
            db_models.Operation.session_project_path,
        ).where(db_models.Operation.subject.is_(None))
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            result = await db_session.exec(stmt)
            return list(result.all())

    async def set_operation_subject_facts_for_operations_if_unset(
        self,
        operation_ids: list[str],
        subject: str,
        subject_owner: str,
    ) -> int:
        """Record visibility facts for operations without overwriting newer data."""
        stmt = (
            update(db_models.Operation)
            .where(db_models.Operation.operation_id.in_(operation_ids))
            .where(db_models.Operation.subject.is_(None))
            .values(subject=subject, subject_owner=subject_owner)
        )
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0

    async def backfill_operation_subject_facts(self) -> None:
        """Backfill operation visibility facts once, retrying after store failures."""
        try:
            if await self.get_system_setting(_OPERATION_SUBJECT_BACKFILL_SETTING) is not None:
                return
            rows = await self.list_operations_without_subject()
            rows_by_path: dict[str | None, list[str]] = {}
            for operation_id, cwd, session_project_path in rows:
                working_folder = cwd or session_project_path
                if working_folder not in rows_by_path:
                    rows_by_path[working_folder] = []
                rows_by_path[working_folder].append(operation_id)

            ownership_index = load_project_ownership_index()
            rows_updated = 0
            for working_folder, operation_ids in rows_by_path.items():
                subject, subject_owner = _operation_subject_facts(working_folder, ownership_index)
                for offset in range(0, len(operation_ids), _OPERATION_SUBJECT_BACKFILL_BATCH_SIZE):
                    rows_updated += await self.set_operation_subject_facts_for_operations_if_unset(
                        operation_ids[offset : offset + _OPERATION_SUBJECT_BACKFILL_BATCH_SIZE],
                        subject,
                        subject_owner,
                    )
            await self.set_system_setting(
                _OPERATION_SUBJECT_BACKFILL_SETTING,
                _OPERATION_SUBJECT_BACKFILL_COMPLETE,
            )
        except Exception:
            logger.exception(_OPERATION_SUBJECT_BACKFILL_FAILED)
            raise
        logger.info(_OPERATION_SUBJECT_BACKFILL_FINISHED, session_rows=len(rows), rows_updated=rows_updated)

    async def get_operation(self, operation_id: str) -> db_models.Operation | None:
        """Fetch an operation by id."""
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            return await db_session.get(db_models.Operation, operation_id)

    async def get_operation_by_request(
        self,
        *,
        kind: str,
        caller_session_id: str | None,
        client_request_id: str,
    ) -> db_models.Operation | None:
        """Fetch a prior submit by client_request_id.

        ``client_request_id`` is the uniqueness anchor; ``caller_session_id``
        may be ``None`` for a command-backed, caller-less submission.
        """
        stmt = (
            select(db_models.Operation)
            .where(db_models.Operation.kind == kind)
            .where(db_models.Operation.caller_session_id == caller_session_id)
            .where(db_models.Operation.client_request_id == client_request_id)
        )
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            result = await db_session.exec(stmt)
            return result.first()

    async def find_matching_nonterminal_operation(
        self,
        *,
        kind: str,
        caller_session_id: str | None,
        cwd: str,
        slug: str | None,
        existing_match_ok: Callable[[db_models.Operation], bool] | None = None,
    ) -> db_models.Operation | None:
        """Find the newest matching operation accepted by the submitter's predicate."""
        stmt = (
            select(db_models.Operation)
            .where(db_models.Operation.kind == kind)
            .where(db_models.Operation.caller_session_id == caller_session_id)
            .where(db_models.Operation.cwd == cwd)
            .where(db_models.Operation.state.in_(["queued", "running"]))
            .order_by(db_models.Operation.created_at.desc())
        )
        if slug is None:
            stmt = stmt.where(db_models.Operation.slug.is_(None))
        else:
            stmt = stmt.where(db_models.Operation.slug == slug)
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            result = await db_session.exec(stmt)
            for operation in result.all():
                if existing_match_ok is None or existing_match_ok(operation):
                    return operation
            return None

    async def earlier_nonterminal_operation_ids(
        self,
        *,
        kind: str,
        cwd: str,
        created_at: str,
        operation_id: str,
    ) -> list[str]:
        """Ids of the queued or running operations of ``kind`` in ``cwd`` accepted before the given one."""
        stmt = (
            select(db_models.Operation.operation_id)
            .where(db_models.Operation.kind == kind)
            .where(db_models.Operation.cwd == cwd)
            .where(db_models.Operation.state.in_(_NONTERMINAL_STATES))
            .where(
                or_(
                    db_models.Operation.created_at < created_at,
                    and_(
                        db_models.Operation.created_at == created_at,
                        db_models.Operation.operation_id < operation_id,
                    ),
                )
            )
        )
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            result = await db_session.exec(stmt)
            return list(result.all())

    async def find_nonterminal_operations_bound_to_todo(
        self,
        *,
        old_slug: str,
        cwd: str,
        exclude_operation_id: str | None = None,
    ) -> list[db_models.Operation]:
        """Return queued/running operations that still bind the source todo."""
        stmt = (
            select(db_models.Operation)
            .where(db_models.Operation.state.in_(["queued", "running"]))
            .where(
                or_(
                    db_models.Operation.slug == old_slug,
                    and_(db_models.Operation.slug.is_(None), db_models.Operation.cwd == cwd),
                )
            )
            .order_by(db_models.Operation.created_at.desc())
        )
        if exclude_operation_id is not None:
            stmt = stmt.where(db_models.Operation.operation_id != exclude_operation_id)
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            result = await db_session.exec(stmt)
            return list(result.all())

    async def rewrite_operation_todo_refs(self, *, old_slug: str, new_slug: str) -> int:
        """Rewrite retained operation receipts from old slug to new slug."""
        now_iso = datetime.now(UTC).isoformat()
        stmt = (
            update(db_models.Operation)
            .where(db_models.Operation.slug == old_slug)
            .values(slug=new_slug, updated_at=now_iso)
        )
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0

    async def claim_operation(self, operation_id: str, now_iso: str) -> bool:
        """Transition a queued operation to running."""
        stmt = (
            update(db_models.Operation)
            .where(db_models.Operation.operation_id == operation_id)
            .where(db_models.Operation.state == "queued")
            .values(
                state="running",
                started_at=now_iso,
                updated_at=now_iso,
                heartbeat_at=now_iso,
                attempt_count=db_models.Operation.attempt_count + 1,
            )
        )
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def touch_operation(self, operation_id: str, now_iso: str) -> None:
        """Refresh operation heartbeat without changing progress."""
        stmt = (
            update(db_models.Operation)
            .where(db_models.Operation.operation_id == operation_id)
            .where(db_models.Operation.state == "running")
            .values(updated_at=now_iso, heartbeat_at=now_iso)
        )
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def update_operation_progress(
        self,
        operation_id: str,
        *,
        phase: str,
        decision: str,
        reason: str,
        now_iso: str,
    ) -> None:
        """Persist operation progress and heartbeat."""
        stmt = (
            update(db_models.Operation)
            .where(db_models.Operation.operation_id == operation_id)
            .where(db_models.Operation.state == "running")
            .values(
                progress_phase=phase,
                progress_decision=decision,
                progress_reason=reason,
                updated_at=now_iso,
                heartbeat_at=now_iso,
            )
        )
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def complete_operation(
        self,
        operation_id: str,
        result_text: str,
        now_iso: str,
        *,
        work_feedback: str | None = None,
    ) -> bool:
        """Mark a non-terminal operation as completed; report whether this call made the transition."""
        stmt = (
            update(db_models.Operation)
            .where(
                db_models.Operation.operation_id == operation_id,
                db_models.Operation.state.in_(_NONTERMINAL_STATES),
            )
            .values(
                state="completed",
                result_text=result_text,
                error_text=None,
                error_payload=None,
                work_feedback=work_feedback,
                updated_at=now_iso,
                heartbeat_at=now_iso,
                completed_at=now_iso,
            )
        )
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def fail_operation(
        self,
        operation_id: str,
        error_text: str,
        now_iso: str,
        *,
        state: str = "failed",
        error_payload_json: str | None = None,
        work_feedback: str | None = None,
    ) -> bool:
        """Mark a non-terminal operation as terminal failure; report whether this call made the transition."""
        stmt = (
            update(db_models.Operation)
            .where(
                db_models.Operation.operation_id == operation_id,
                db_models.Operation.state.in_(_NONTERMINAL_STATES),
            )
            .values(
                state=state,
                error_text=error_text,
                error_payload=error_payload_json,
                work_feedback=work_feedback,
                updated_at=now_iso,
                heartbeat_at=now_iso,
                completed_at=now_iso,
            )
        )
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def mark_nonterminal_operations_stale(self, *, error_text: str) -> list[db_models.Operation]:
        """Mark queued/running operations stale, typically after daemon restart.

        Returns the affected rows (post-transition) rather than a bare count —
        staleness is an outcome, and a caller cannot be named from a rowcount.
        """
        now_iso = datetime.now(UTC).isoformat()
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            id_stmt = select(db_models.Operation.operation_id).where(
                db_models.Operation.state.in_(["queued", "running"])
            )
            ids = list((await db_session.exec(id_stmt)).all())
            if not ids:
                return []
            stmt = (
                update(db_models.Operation)
                .where(db_models.Operation.operation_id.in_(ids))
                .values(
                    state="stale",
                    error_text=error_text,
                    error_payload=None,
                    work_feedback=None,
                    updated_at=now_iso,
                    heartbeat_at=now_iso,
                    completed_at=now_iso,
                )
            )
            await db_session.exec(stmt)
            await db_session.commit()
            refreshed = await db_session.exec(
                select(db_models.Operation).where(db_models.Operation.operation_id.in_(ids))
            )
            return list(refreshed.all())

    async def expire_stale_operations(self, older_than_iso: str, *, error_text: str) -> list[db_models.Operation]:
        """Mark long-silent running operations stale.

        Returns the affected rows (post-transition) rather than a bare count —
        staleness is an outcome, and a caller cannot be named from a rowcount.
        """
        now_iso = datetime.now(UTC).isoformat()
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            id_stmt = select(db_models.Operation.operation_id).where(
                and_(
                    db_models.Operation.state == "running",
                    or_(
                        db_models.Operation.heartbeat_at.is_(None),
                        db_models.Operation.heartbeat_at < older_than_iso,
                    ),
                )
            )
            ids = list((await db_session.exec(id_stmt)).all())
            if not ids:
                return []
            stmt = (
                update(db_models.Operation)
                .where(db_models.Operation.operation_id.in_(ids))
                .values(
                    state="stale",
                    error_text=error_text,
                    error_payload=None,
                    work_feedback=None,
                    updated_at=now_iso,
                    completed_at=now_iso,
                )
            )
            await db_session.exec(stmt)
            await db_session.commit()
            refreshed = await db_session.exec(
                select(db_models.Operation).where(db_models.Operation.operation_id.in_(ids))
            )
            return list(refreshed.all())

    async def cleanup_terminal_operations(self, older_than_iso: str) -> int:
        """Delete terminal operation receipts older than runtime retention."""
        stmt = (
            delete(db_models.Operation)
            .where(db_models.Operation.state.in_(["completed", "failed", "stale", "cancelled"]))
            .where(
                or_(
                    db_models.Operation.completed_at < older_than_iso,
                    and_(
                        db_models.Operation.completed_at.is_(None),
                        db_models.Operation.updated_at < older_than_iso,
                    ),
                )
            )
        )
        async with self._store_session(DaemonStore.OPERATIONS) as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0
