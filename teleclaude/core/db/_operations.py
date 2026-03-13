"""Mixin: DbOperationsMixin."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from .. import db_models

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class DbOperationsMixin:
    async def create_operation(
        self,
        *,
        operation_id: str,
        kind: str,
        caller_session_id: str,
        client_request_id: str | None,
        cwd: str,
        slug: str | None,
        payload_json: str,
        state: str,
    ) -> db_models.Operation:
        """Insert a durable operation row."""
        now = datetime.now(UTC).isoformat()
        row = db_models.Operation(
            operation_id=operation_id,
            kind=kind,
            caller_session_id=caller_session_id,
            client_request_id=client_request_id,
            cwd=cwd,
            slug=slug,
            payload_json=payload_json,
            state=state,
            created_at=now,
            updated_at=now,
            heartbeat_at=now,
            attempt_count=0,
        )
        async with self._session() as db_session:
            db_session.add(row)
            await db_session.commit()
            await db_session.refresh(row)
            return row

    async def get_operation(self, operation_id: str) -> db_models.Operation | None:
        """Fetch an operation by id."""
        async with self._session() as db_session:
            return await db_session.get(db_models.Operation, operation_id)

    async def get_operation_by_request(
        self,
        *,
        kind: str,
        caller_session_id: str,
        client_request_id: str,
    ) -> db_models.Operation | None:
        """Fetch a prior submit by client_request_id."""
        from sqlmodel import select

        stmt = (
            select(db_models.Operation)
            .where(db_models.Operation.kind == kind)
            .where(db_models.Operation.caller_session_id == caller_session_id)
            .where(db_models.Operation.client_request_id == client_request_id)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return result.first()

    async def find_matching_nonterminal_operation(
        self,
        *,
        kind: str,
        caller_session_id: str,
        cwd: str,
        slug: str | None,
    ) -> db_models.Operation | None:
        """Find the most recent matching queued/running operation for reattachment."""
        from sqlmodel import select

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
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return result.first()

    async def claim_operation(self, operation_id: str, now_iso: str) -> bool:
        """Transition a queued operation to running."""
        from sqlalchemy import update

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
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def touch_operation(self, operation_id: str, now_iso: str) -> None:
        """Refresh operation heartbeat without changing progress."""
        from sqlalchemy import update

        stmt = (
            update(db_models.Operation)
            .where(db_models.Operation.operation_id == operation_id)
            .where(db_models.Operation.state == "running")
            .values(updated_at=now_iso, heartbeat_at=now_iso)
        )
        async with self._session() as db_session:
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
        from sqlalchemy import update

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
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def complete_operation(self, operation_id: str, result_text: str, now_iso: str) -> None:
        """Mark an operation as completed."""
        from sqlalchemy import update

        stmt = (
            update(db_models.Operation)
            .where(db_models.Operation.operation_id == operation_id)
            .values(
                state="completed",
                result_text=result_text,
                error_text=None,
                updated_at=now_iso,
                heartbeat_at=now_iso,
                completed_at=now_iso,
            )
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def fail_operation(self, operation_id: str, error_text: str, now_iso: str, *, state: str = "failed") -> None:
        """Mark an operation as terminal failure."""
        from sqlalchemy import update

        stmt = (
            update(db_models.Operation)
            .where(db_models.Operation.operation_id == operation_id)
            .values(
                state=state,
                error_text=error_text,
                updated_at=now_iso,
                heartbeat_at=now_iso,
                completed_at=now_iso,
            )
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def mark_nonterminal_operations_stale(self, *, error_text: str) -> int:
        """Mark queued/running operations stale, typically after daemon restart."""
        from sqlalchemy import update

        now_iso = datetime.now(UTC).isoformat()
        stmt = (
            update(db_models.Operation)
            .where(db_models.Operation.state.in_(["queued", "running"]))
            .values(
                state="stale",
                error_text=error_text,
                updated_at=now_iso,
                heartbeat_at=now_iso,
                completed_at=now_iso,
            )
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0

    async def expire_stale_operations(self, older_than_iso: str, *, error_text: str) -> int:
        """Mark long-silent running operations stale."""
        from sqlalchemy import or_, update

        now_iso = datetime.now(UTC).isoformat()
        stmt = (
            update(db_models.Operation)
            .where(db_models.Operation.state == "running")
            .where(
                or_(
                    db_models.Operation.heartbeat_at.is_(None),
                    db_models.Operation.heartbeat_at < older_than_iso,
                )
            )
            .values(
                state="stale",
                error_text=error_text,
                updated_at=now_iso,
                completed_at=now_iso,
            )
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0

    # ── Webhook contracts CRUD ──────────────────────────────────────────
