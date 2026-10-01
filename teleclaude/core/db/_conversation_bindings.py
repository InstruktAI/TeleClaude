"""Database adapter for the mesh master's durable conversation bindings."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import select

from teleclaude.core import db_models
from teleclaude.core.models import EndpointStamp


@dataclass(frozen=True)
class ConversationBinding:
    """One shared-adapter conversation's binding: the session its next message goes to."""

    origin: str
    key_field: str
    conversation_key: str
    host: str
    session_id: str
    endpoint: EndpointStamp
    entered_at: str


@dataclass(frozen=True)
class ConversationAdoptionSource:
    """One computer expected to export its open conversation sessions, and when it did."""

    computer: str
    answered_at: str | None


@dataclass(frozen=True)
class ConversationBindingOrphan:
    """A session id a lost remote-create answer may have left on its host."""

    session_id: str
    host: str
    recorded_at: str


class DbConversationBindingsMixin:
    """Persist the master's conversation bindings, adoption sources and orphan record."""

    async def get_conversation_binding(
        self, origin: str, key_field: str, conversation_key: str
    ) -> ConversationBinding | None:
        """Read one conversation's binding."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.ConversationBindingRow, (origin, key_field, conversation_key))
        return _to_binding(row) if row is not None else None

    async def put_conversation_binding(self, binding: ConversationBinding) -> None:
        """Record a conversation's binding in one write, replacing any earlier one."""
        statement = sqlite_insert(db_models.ConversationBindingRow).values(
            origin=binding.origin,
            key_field=binding.key_field,
            conversation_key=binding.conversation_key,
            host=binding.host,
            session_id=binding.session_id,
            endpoint=json.dumps(binding.endpoint.to_dict()),
            entered_at=binding.entered_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["origin", "key_field", "conversation_key"],
            set_={
                "host": statement.excluded.host,
                "session_id": statement.excluded.session_id,
                "endpoint": statement.excluded.endpoint,
                "entered_at": statement.excluded.entered_at,
            },
        )
        async with self._session() as db_session:
            await db_session.exec(statement)
            await db_session.commit()

    async def record_conversation_adoption_sources(self, computers: Sequence[str]) -> None:
        """Set the expected adoption sources; a source that already answered keeps its answer."""
        async with self._session() as db_session:
            await db_session.exec(
                delete(db_models.ConversationAdoptionSourceRow).where(
                    db_models.ConversationAdoptionSourceRow.computer.not_in(list(computers))  # type: ignore[attr-defined]
                )
            )
            for computer in computers:
                await db_session.exec(
                    sqlite_insert(db_models.ConversationAdoptionSourceRow)
                    .values(computer=computer, answered_at=None)
                    .on_conflict_do_nothing(index_elements=["computer"])
                )
            await db_session.commit()

    async def list_conversation_adoption_sources(self) -> list[ConversationAdoptionSource]:
        """Every expected adoption source, in name order."""
        statement = select(db_models.ConversationAdoptionSourceRow).order_by(
            db_models.ConversationAdoptionSourceRow.computer
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
        return [ConversationAdoptionSource(computer=row.computer, answered_at=row.answered_at) for row in rows]

    async def mark_conversation_adoption_source_answered(self, computer: str, answered_at: str) -> None:
        """Record that an expected source has exported its open conversation sessions."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.ConversationAdoptionSourceRow, computer)
            if row is None:
                return
            row.answered_at = answered_at
            db_session.add(row)
            await db_session.commit()

    async def record_conversation_binding_orphan(self, orphan: ConversationBindingOrphan) -> None:
        """Remember a session id a lost remote-create answer may have left behind."""
        statement = (
            sqlite_insert(db_models.ConversationBindingOrphanRow)
            .values(session_id=orphan.session_id, host=orphan.host, recorded_at=orphan.recorded_at)
            .on_conflict_do_nothing(index_elements=["session_id"])
        )
        async with self._session() as db_session:
            await db_session.exec(statement)
            await db_session.commit()

    async def list_conversation_binding_orphans(self) -> list[ConversationBindingOrphan]:
        """Every remembered orphan session id."""
        async with self._session() as db_session:
            rows = (await db_session.exec(select(db_models.ConversationBindingOrphanRow))).all()
        return [
            ConversationBindingOrphan(session_id=row.session_id, host=row.host, recorded_at=row.recorded_at)
            for row in rows
        ]

    async def delete_conversation_binding_orphan(self, session_id: str) -> None:
        """Forget an orphan once its host has closed it."""
        async with self._session() as db_session:
            await db_session.exec(
                delete(db_models.ConversationBindingOrphanRow).where(
                    db_models.ConversationBindingOrphanRow.session_id == session_id  # type: ignore[arg-type]
                )
            )
            await db_session.commit()


def _to_binding(row: db_models.ConversationBindingRow) -> ConversationBinding:
    stored: object = json.loads(row.endpoint)
    endpoint = EndpointStamp.from_dict(stored) if isinstance(stored, dict) else None
    if endpoint is None:
        raise ValueError(f"conversation binding for session {row.session_id} has no valid endpoint")
    return ConversationBinding(
        origin=row.origin,
        key_field=row.key_field,
        conversation_key=row.conversation_key,
        host=row.host,
        session_id=row.session_id,
        endpoint=endpoint,
        entered_at=row.entered_at,
    )


__all__ = [
    "ConversationAdoptionSource",
    "ConversationBinding",
    "ConversationBindingOrphan",
    "DbConversationBindingsMixin",
]
