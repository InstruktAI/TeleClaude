"""Mixin: DbListenersMixin."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from sqlalchemy import and_, delete, func, or_, update
from sqlalchemy import select as sqlalchemy_select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from teleclaude.config.machine import config

from .. import db_models
from ..session_status import AgentStatusValue

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class DbListenersMixin:
    """Session listener registration and cleanup helpers."""

    async def register_listener(
        self,
        target_session_id: str,
        caller_session_id: str,
        caller_tmux_session: str,
        one_shot: bool = False,
        caller_computer: str | None = None,
    ) -> bool:
        """Upsert a listener row. Returns True if newly inserted, False if already existed."""
        now = datetime.now(UTC).isoformat()
        async with self._session() as db_session:
            # Check for existing
            stmt = select(db_models.SessionListenerRow).where(
                db_models.SessionListenerRow.target_session_id == target_session_id,
                db_models.SessionListenerRow.caller_session_id == caller_session_id,
            )
            existing = (await db_session.exec(stmt)).first()
            if existing:
                return False

            row = db_models.SessionListenerRow(
                target_session_id=target_session_id,
                caller_session_id=caller_session_id,
                caller_tmux_session=caller_tmux_session,
                registered_at=now,
                one_shot=one_shot,
                caller_computer=caller_computer,
            )
            db_session.add(row)
            try:
                await db_session.commit()
            except IntegrityError:
                return False
            return True

    async def establish_supervision(
        self,
        target_session_id: str,
        caller_session_id: str,
        caller_tmux_session: str,
        *,
        caller_computer: str,
        startup_run_id: str | None,
    ) -> None:
        """Explicitly establish or promote persistent supervision for one pair."""
        now = datetime.now(UTC).isoformat()
        statement = (
            sqlite_insert(db_models.SessionListenerRow)
            .values(
                target_session_id=target_session_id,
                caller_session_id=caller_session_id,
                caller_tmux_session=caller_tmux_session,
                registered_at=now,
                one_shot=False,
                caller_computer=caller_computer,
                startup_run_id=startup_run_id,
            )
            .on_conflict_do_update(
                index_elements=[
                    db_models.SessionListenerRow.target_session_id,
                    db_models.SessionListenerRow.caller_session_id,
                ],
                set_={
                    "caller_tmux_session": caller_tmux_session,
                    "registered_at": now,
                    "one_shot": False,
                    "caller_computer": caller_computer,
                    "startup_run_id": startup_run_id,
                },
            )
        )
        async with self._session() as db_session:
            await db_session.exec(statement)
            await db_session.commit()

    async def record_startup_work_accepted(
        self,
        target_session_id: str,
        caller_session_id: str,
        run_id: str,
    ) -> bool:
        """Bind accepted initial work to the current unknown run for a persistent caller."""
        current_run = select(db_models.Session.session_id).where(
            db_models.Session.session_id == target_session_id,
            db_models.Session.runtime_run_id == run_id,
            db_models.Session.agent_status == AgentStatusValue.UNKNOWN.value,
        )
        statement = (
            update(db_models.SessionListenerRow)
            .where(
                db_models.SessionListenerRow.target_session_id == target_session_id,
                db_models.SessionListenerRow.caller_session_id == caller_session_id,
                db_models.SessionListenerRow.one_shot.is_(False),
                db_models.SessionListenerRow.target_session_id.in_(current_run),
            )
            .values(startup_run_id=run_id)
            .returning(db_models.SessionListenerRow.caller_session_id)
        )
        async with self._session() as db_session:
            result = await db_session.exec(statement)
            rows = result.all()
            await db_session.commit()
            return bool(rows)

    async def unregister_listener(self, target_session_id: str, caller_session_id: str) -> bool:
        """Remove a specific listener. Returns True if removed."""
        stmt = delete(db_models.SessionListenerRow).where(
            db_models.SessionListenerRow.target_session_id == target_session_id,
            db_models.SessionListenerRow.caller_session_id == caller_session_id,
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount > 0  # type: ignore[union-attr]

    async def get_listeners_for_target(self, target_session_id: str) -> list[db_models.SessionListenerRow]:
        """Get all listeners waiting on a target session."""
        stmt = select(db_models.SessionListenerRow).where(
            db_models.SessionListenerRow.target_session_id == target_session_id,
        )
        async with self._session() as db_session:
            return list((await db_session.exec(stmt)).all())

    async def pop_listeners_for_target(self, target_session_id: str) -> list[db_models.SessionListenerRow]:
        """Remove and return all listeners for a target (cleanup on session close)."""
        listeners = await self.get_listeners_for_target(target_session_id)
        if listeners:
            stmt = delete(db_models.SessionListenerRow).where(
                db_models.SessionListenerRow.target_session_id == target_session_id,
            )
            async with self._session() as db_session:
                await db_session.exec(stmt)
                await db_session.commit()
        return listeners

    async def cleanup_caller_listeners(self, caller_session_id: str) -> int:
        """Remove all listeners registered by a caller (caller session ended)."""
        stmt = delete(db_models.SessionListenerRow).where(
            db_models.SessionListenerRow.caller_session_id == caller_session_id,
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0  # type: ignore[union-attr]

    async def get_all_listeners(self) -> list[db_models.SessionListenerRow]:
        """Get all active listeners (for debugging/monitoring)."""
        async with self._session() as db_session:
            return list((await db_session.exec(select(db_models.SessionListenerRow))).all())

    async def count_listeners(self) -> int:
        """Get total number of active listeners."""
        stmt = sqlalchemy_select(func.count()).select_from(db_models.SessionListenerRow)
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return result.one()[0]  # type: ignore[index]

    async def get_stale_listener_targets(self, max_age_iso: str) -> list[str]:
        """Get target session IDs with listeners older than a threshold.

        Returns unique target IDs. After calling, the caller should reset
        registered_at on these to prevent repeated checks.
        """
        stmt = (
            select(db_models.SessionListenerRow.target_session_id)
            .where(db_models.SessionListenerRow.registered_at < max_age_iso)
            .distinct()
        )
        async with self._session() as db_session:
            return list((await db_session.exec(stmt)).all())

    async def reset_listener_timestamps(self, target_session_id: str, new_timestamp: str) -> None:
        """Reset registered_at for all listeners of a target (after stale check)."""
        stmt = (
            update(db_models.SessionListenerRow)
            .where(db_models.SessionListenerRow.target_session_id == target_session_id)
            .values(registered_at=new_timestamp)
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def get_listeners_for_caller(self, caller_session_id: str) -> list[db_models.SessionListenerRow]:
        """Get all listeners registered by a specific caller."""
        stmt = select(db_models.SessionListenerRow).where(
            db_models.SessionListenerRow.caller_session_id == caller_session_id,
        )
        async with self._session() as db_session:
            return list((await db_session.exec(stmt)).all())

    async def cleanup_orphan_session_listeners(self) -> int:
        """Delete listeners whose target or caller session is closed or missing."""
        live_session_ids = select(db_models.Session.session_id).where(
            db_models.Session.closed_at.is_(None),
            or_(
                db_models.Session.lifecycle_status.is_(None),
                db_models.Session.lifecycle_status != "closed",
            ),
        )
        stmt = delete(db_models.SessionListenerRow).where(
            or_(
                db_models.SessionListenerRow.target_session_id.notin_(live_session_ids),
                and_(
                    or_(
                        db_models.SessionListenerRow.caller_computer.is_(None),
                        db_models.SessionListenerRow.caller_computer == config.computer.name,
                    ),
                    db_models.SessionListenerRow.caller_session_id.notin_(live_session_ids),
                ),
            )
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0

    # ── Conversation links (direct + gathering) ──────────────────────
