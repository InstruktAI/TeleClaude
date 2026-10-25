"""Database adapter for the per-place Discord inbound recovery cursor and the facts that seed it."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import cast, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.types import Integer
from sqlmodel import select

from teleclaude.core import db_models
from teleclaude.core.integration.discord_inbound_cursor import message_id_of_source_identity
from teleclaude.core.models import DiscordMetadataField
from teleclaude.core.origins import InputOrigin

_DISCORD_THREAD_ID_JSON_PATH: Final = f"$.{InputOrigin.DISCORD.value}.{DiscordMetadataField.THREAD_ID.value}"
_CURSOR_KEY_COLUMNS: Final = ("place_id",)
_CURSOR_MESSAGE_COLUMN: Final = "message_id"
_CURSOR_UPDATED_COLUMN: Final = "updated_at"


@dataclass(frozen=True)
class DiscordThreadPlace:
    """A Discord thread bound to still-active sessions, and the earliest of their creations."""

    thread_id: int
    session_ids: tuple[str, ...]
    bound_at: datetime | None


class DbDiscordInboundCursorsMixin:
    """Persist the Discord inbound recovery cursor of each place."""

    async def get_discord_inbound_cursor(self, place_id: int) -> int | None:
        """The newest concluded message of a place, or ``None`` when the place has no cursor."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.DiscordInboundCursorRow, place_id)
        return row.message_id if row is not None else None

    async def create_discord_inbound_cursor(self, place_id: int, message_id: int) -> bool:
        """Start a place's cursor at ``message_id``; ``False`` when the place already has one, which stays as it is."""
        statement = (
            sqlite_insert(db_models.DiscordInboundCursorRow)
            .values(place_id=place_id, message_id=message_id, updated_at=datetime.now(UTC).isoformat())
            .on_conflict_do_nothing(index_elements=list(_CURSOR_KEY_COLUMNS))
        )
        async with self._session() as db_session:
            result = await db_session.exec(statement)
            await db_session.commit()
        return bool(result.rowcount)

    async def advance_discord_inbound_cursor(self, place_id: int, message_id: int) -> None:
        """Move a place's cursor forward to ``message_id``, starting it there when the place has none.

        A cursor never moves backwards.
        """
        statement = sqlite_insert(db_models.DiscordInboundCursorRow).values(
            place_id=place_id, message_id=message_id, updated_at=datetime.now(UTC).isoformat()
        )
        statement = statement.on_conflict_do_update(
            index_elements=list(_CURSOR_KEY_COLUMNS),
            set_={
                _CURSOR_MESSAGE_COLUMN: statement.excluded.message_id,
                _CURSOR_UPDATED_COLUMN: statement.excluded.updated_at,
            },
            where=db_models.DiscordInboundCursorRow.message_id < statement.excluded.message_id,  # type: ignore[arg-type]
        )
        async with self._session() as db_session:
            await db_session.exec(statement)
            await db_session.commit()

    async def list_active_discord_threads(self) -> list[DiscordThreadPlace]:
        """Every Discord thread bound to a session that is still open."""
        thread_id = func.json_extract(db_models.Session.origin_metadata, _DISCORD_THREAD_ID_JSON_PATH)
        statement = select(db_models.Session.session_id, db_models.Session.created_at, cast(thread_id, Integer)).where(
            db_models.Session.closed_at.is_(None),  # type: ignore[union-attr]
            thread_id.is_not(None),
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
        sessions_by_thread: defaultdict[int, list[tuple[str, datetime | None]]] = defaultdict(list)
        for session_id, created_at, bound_thread_id in rows:
            sessions_by_thread[bound_thread_id].append((session_id, created_at))
        return [
            DiscordThreadPlace(
                thread_id=bound_thread_id,
                session_ids=tuple(session_id for session_id, _ in sessions),
                bound_at=min((created for _, created in sessions if created is not None), default=None),
            )
            for bound_thread_id, sessions in sessions_by_thread.items()
        ]

    async def newest_retained_discord_input(self, session_ids: Sequence[str]) -> int | None:
        """The newest Discord message the inbound queue still retains as accepted for any of these sessions."""
        if not session_ids:
            return None
        statement = select(db_models.InboundQueue.source_message_id).where(
            db_models.InboundQueue.origin == InputOrigin.DISCORD.value,
            db_models.InboundQueue.session_id.in_(session_ids),  # type: ignore[attr-defined]
            db_models.InboundQueue.source_message_id.is_not(None),  # type: ignore[union-attr]
        )
        async with self._session() as db_session:
            identities = (await db_session.exec(statement)).all()
        message_ids = [
            message_id
            for identity in identities
            if identity is not None and (message_id := message_id_of_source_identity(identity)) is not None
        ]
        return max(message_ids, default=None)
