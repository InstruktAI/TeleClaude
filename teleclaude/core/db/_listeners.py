"""Mixin: DbListenersMixin."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from .. import db_models

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class DbListenersMixin:
    async def register_listener(
        self,
        target_session_id: str,
        caller_session_id: str,
        caller_tmux_session: str,
    ) -> bool:
        """Upsert a listener row. Returns True if newly inserted, False if already existed."""
        from sqlalchemy.exc import IntegrityError

        now = datetime.now(UTC).isoformat()
        async with self._session() as db_session:
            # Check for existing
            from sqlmodel import select

            stmt = select(db_models.SessionListenerRow).where(
                db_models.SessionListenerRow.target_session_id == target_session_id,
                db_models.SessionListenerRow.caller_session_id == caller_session_id,
            )
            existing = (await db_session.exec(stmt)).first()
            if existing:
                # Update tmux session name (may change after restart)
                existing.caller_tmux_session = caller_tmux_session
                existing.registered_at = now
                db_session.add(existing)
                await db_session.commit()
                return False

            row = db_models.SessionListenerRow(
                target_session_id=target_session_id,
                caller_session_id=caller_session_id,
                caller_tmux_session=caller_tmux_session,
                registered_at=now,
            )
            db_session.add(row)
            try:
                await db_session.commit()
            except IntegrityError:
                return False
            return True

    async def unregister_listener(self, target_session_id: str, caller_session_id: str) -> bool:
        """Remove a specific listener. Returns True if removed."""
        from sqlalchemy import delete

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
        from sqlmodel import select

        stmt = select(db_models.SessionListenerRow).where(
            db_models.SessionListenerRow.target_session_id == target_session_id,
        )
        async with self._session() as db_session:
            return list((await db_session.exec(stmt)).all())

    async def pop_listeners_for_target(self, target_session_id: str) -> list[db_models.SessionListenerRow]:
        """Remove and return all listeners for a target (cleanup on session close)."""
        from sqlalchemy import delete

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
        from sqlalchemy import delete

        stmt = delete(db_models.SessionListenerRow).where(
            db_models.SessionListenerRow.caller_session_id == caller_session_id,
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0  # type: ignore[union-attr]

    async def get_all_listeners(self) -> list[db_models.SessionListenerRow]:
        """Get all active listeners (for debugging/monitoring)."""
        from sqlmodel import select

        async with self._session() as db_session:
            return list((await db_session.exec(select(db_models.SessionListenerRow))).all())

    async def count_listeners(self) -> int:
        """Get total number of active listeners."""
        from sqlalchemy import func, select

        stmt = select(func.count()).select_from(db_models.SessionListenerRow)
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return result.one()[0]  # type: ignore[index]

    async def get_stale_listener_targets(self, max_age_iso: str) -> list[str]:
        """Get target session IDs with listeners older than a threshold.

        Returns unique target IDs. After calling, the caller should reset
        registered_at on these to prevent repeated checks.
        """
        from sqlmodel import select

        stmt = (
            select(db_models.SessionListenerRow.target_session_id)
            .where(db_models.SessionListenerRow.registered_at < max_age_iso)
            .distinct()
        )
        async with self._session() as db_session:
            return list((await db_session.exec(stmt)).all())

    async def reset_listener_timestamps(self, target_session_id: str, new_timestamp: str) -> None:
        """Reset registered_at for all listeners of a target (after stale check)."""
        from sqlalchemy import update

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
        from sqlmodel import select

        stmt = select(db_models.SessionListenerRow).where(
            db_models.SessionListenerRow.caller_session_id == caller_session_id,
        )
        async with self._session() as db_session:
            return list((await db_session.exec(stmt)).all())

    # ── Conversation links (direct + gathering) ──────────────────────
