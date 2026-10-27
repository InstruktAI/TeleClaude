"""Own the ordinals of a session's turns, fixed the first time a turn is found."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core import db_models

type SessionOpener = Callable[[], SqlAsyncSession]

_FIRST_ORDINAL = 1
_RECORD_ATTEMPTS = 2


class SessionTurnStore:
    """Persist which ordinal each turn of a session received, in the order the turns were found."""

    def __init__(self, open_session: SessionOpener) -> None:
        self._open_session = open_session

    async def known_ordinals(self, session_id: str) -> dict[str, int]:
        """Return every recorded turn identity of a session with its ordinal."""
        statement = select(db_models.SessionTurnRow).where(db_models.SessionTurnRow.session_id == session_id)
        async with self._open_session() as db_session:
            rows = (await db_session.exec(statement)).all()
        return {row.turn_identity: row.ordinal for row in rows}

    async def known_sources(self, session_id: str) -> frozenset[str]:
        """Return the digest of every transcript file of a session that a read has taken turns from."""
        statement = select(db_models.SessionTurnSourceRow).where(
            db_models.SessionTurnSourceRow.session_id == session_id
        )
        async with self._open_session() as db_session:
            rows = (await db_session.exec(statement)).all()
        return frozenset(row.source_digest for row in rows)

    async def record_turns(
        self, session_id: str, identities: Sequence[str], sources: Sequence[str] = ()
    ) -> dict[str, int]:
        """Give each identity not yet recorded the next ordinal, in the order given, and return all ordinals.

        An identity that already has an ordinal keeps it, so an ordinal is never rewritten. The files the turns were
        taken from are recorded in the same write, so a file is never known as read without its turns recorded. Two
        concurrent recorders of one session meet at the unique ordinal; the loser reads what the winner wrote.
        """
        for attempt in range(_RECORD_ATTEMPTS):
            known = await self.known_ordinals(session_id)
            known_sources = await self.known_sources(session_id)
            fresh = [identity for identity in dict.fromkeys(identities) if identity not in known]
            fresh_sources = [digest for digest in dict.fromkeys(sources) if digest not in known_sources]
            if not fresh and not fresh_sources:
                return known
            next_ordinal = max(known.values(), default=_FIRST_ORDINAL - 1) + 1
            now = datetime.now(UTC).isoformat()
            async with self._open_session() as db_session:
                for offset, identity in enumerate(fresh):
                    db_session.add(
                        db_models.SessionTurnRow(
                            session_id=session_id,
                            turn_identity=identity,
                            ordinal=next_ordinal + offset,
                            created_at=now,
                        )
                    )
                for digest in fresh_sources:
                    db_session.add(
                        db_models.SessionTurnSourceRow(session_id=session_id, source_digest=digest, created_at=now)
                    )
                try:
                    await db_session.commit()
                except IntegrityError:
                    await db_session.rollback()
                    if attempt + 1 == _RECORD_ATTEMPTS:
                        raise
                    continue
            return await self.known_ordinals(session_id)
        return await self.known_ordinals(session_id)
