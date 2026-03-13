"""Mixin: DbLinksMixin."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from instrukt_ai_logging import get_logger

from .. import db_models

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class DbLinksMixin:
    async def create_conversation_link(
        self,
        *,
        mode: Literal["direct_link", "gathering_link"],
        created_by_session_id: str,
        metadata_json: str | None = None,
    ) -> db_models.ConversationLinkRow:
        """Create a new conversation link row."""
        now = datetime.now(UTC).isoformat()
        link = db_models.ConversationLinkRow(
            link_id=str(uuid.uuid4()),
            mode=mode,
            status="active",
            created_by_session_id=created_by_session_id,
            metadata_json=metadata_json,
            created_at=now,
            updated_at=now,
            closed_at=None,
        )
        async with self._session() as db_session:
            db_session.add(link)
            await db_session.commit()
            await db_session.refresh(link)
            return link

    async def get_conversation_link(self, link_id: str) -> db_models.ConversationLinkRow | None:
        """Get a link by ID."""
        from sqlmodel import select

        stmt = select(db_models.ConversationLinkRow).where(db_models.ConversationLinkRow.link_id == link_id)
        async with self._session() as db_session:
            return (await db_session.exec(stmt)).first()

    async def list_conversation_link_members(self, link_id: str) -> list[db_models.ConversationLinkMemberRow]:
        """List members for a link, ordered for deterministic fan-out."""
        from sqlmodel import select

        stmt = (
            select(db_models.ConversationLinkMemberRow)
            .where(db_models.ConversationLinkMemberRow.link_id == link_id)
            .order_by(
                db_models.ConversationLinkMemberRow.participant_number,
                db_models.ConversationLinkMemberRow.joined_at,
            )
        )
        async with self._session() as db_session:
            return list((await db_session.exec(stmt)).all())

    async def get_active_links_for_session(self, session_id: str) -> list[db_models.ConversationLinkRow]:
        """Get all active links containing the given member session."""
        from sqlmodel import select

        stmt = (
            select(db_models.ConversationLinkRow)
            .join(
                db_models.ConversationLinkMemberRow,
                db_models.ConversationLinkMemberRow.link_id == db_models.ConversationLinkRow.link_id,
            )
            .where(db_models.ConversationLinkMemberRow.session_id == session_id)
            .where(db_models.ConversationLinkRow.status == "active")
        )
        async with self._session() as db_session:
            return list((await db_session.exec(stmt)).all())

    async def get_active_links_between_sessions(
        self,
        session_a: str,
        session_b: str,
        *,
        mode: Literal["direct_link", "gathering_link"] | None = None,
    ) -> list[db_models.ConversationLinkRow]:
        """Find all active links that contain both session IDs."""
        links = await self.get_active_links_for_session(session_a)
        matches: list[db_models.ConversationLinkRow] = []
        for link in links:
            if mode and link.mode != mode:
                continue
            members = await self.list_conversation_link_members(link.link_id)
            member_ids = {member.session_id for member in members}
            if session_b in member_ids:
                matches.append(link)
        return sorted(matches, key=lambda item: item.created_at)

    async def get_active_link_between_sessions(
        self,
        session_a: str,
        session_b: str,
        *,
        mode: Literal["direct_link", "gathering_link"] | None = None,
    ) -> db_models.ConversationLinkRow | None:
        """Find the first active link that contains both session IDs."""
        links = await self.get_active_links_between_sessions(session_a, session_b, mode=mode)
        return links[0] if links else None

    async def upsert_conversation_link_member(
        self,
        *,
        link_id: str,
        session_id: str,
        participant_name: str | None = None,
        participant_number: int | None = None,
        participant_role: str | None = None,
        computer_name: str | None = None,
    ) -> None:
        """Create or update link membership metadata."""
        from sqlmodel import select

        now = datetime.now(UTC).isoformat()
        stmt = select(db_models.ConversationLinkMemberRow).where(
            db_models.ConversationLinkMemberRow.link_id == link_id,
            db_models.ConversationLinkMemberRow.session_id == session_id,
        )
        async with self._session() as db_session:
            existing = (await db_session.exec(stmt)).first()
            if existing:
                existing.participant_name = participant_name
                existing.participant_number = participant_number
                existing.participant_role = participant_role
                existing.computer_name = computer_name
                db_session.add(existing)
            else:
                db_session.add(
                    db_models.ConversationLinkMemberRow(
                        link_id=link_id,
                        session_id=session_id,
                        participant_name=participant_name,
                        participant_number=participant_number,
                        participant_role=participant_role,
                        computer_name=computer_name,
                        joined_at=now,
                    )
                )
            await db_session.commit()

    async def remove_conversation_link_member(self, *, link_id: str, session_id: str) -> bool:
        """Remove a member from a link."""
        from sqlalchemy import delete

        stmt = delete(db_models.ConversationLinkMemberRow).where(
            db_models.ConversationLinkMemberRow.link_id == link_id,
            db_models.ConversationLinkMemberRow.session_id == session_id,
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) > 0  # type: ignore[union-attr]

    async def set_conversation_link_status(self, *, link_id: str, status: Literal["active", "closed"]) -> bool:
        """Update link lifecycle status."""
        from sqlalchemy import update

        now = datetime.now(UTC).isoformat()
        closed_at = now if status == "closed" else None
        stmt = (
            update(db_models.ConversationLinkRow)
            .where(db_models.ConversationLinkRow.link_id == link_id)
            .values(status=status, updated_at=now, closed_at=closed_at)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) > 0  # type: ignore[union-attr]

    async def sever_conversation_link(self, link_id: str) -> bool:
        """Close link and remove all active members."""
        from sqlalchemy import delete

        changed = await self.set_conversation_link_status(link_id=link_id, status="closed")
        stmt = delete(db_models.ConversationLinkMemberRow).where(db_models.ConversationLinkMemberRow.link_id == link_id)
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            deleted = (result.rowcount or 0) > 0  # type: ignore[union-attr]
        return changed or deleted

    async def cleanup_conversation_links_for_session(self, session_id: str) -> int:
        """Sever all active links involving the given session."""
        links = await self.get_active_links_for_session(session_id)
        closed = 0
        for link in links:
            if await self.sever_conversation_link(link.link_id):
                closed += 1
        return closed

    # ------------------------------------------------------------------
    # Session token ledger
    # ------------------------------------------------------------------
