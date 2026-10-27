"""Own the ordinals of a session's turns, fixed the first time a turn is found."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core import db_models
from teleclaude.core.dates import parse_iso_datetime

type SessionOpener = Callable[[], SqlAsyncSession]

_FIRST_ORDINAL = 1
_RECORD_ATTEMPTS = 2


@dataclass(frozen=True)
class SourceCoverage:
    """How far a session's completions were covered when a read took a transcript file.

    ``stop_at`` is the session's last agent stop at that read; ``tail_open`` says the file's last turn had not yet
    completed, so the next stop is the one that completes it.
    """

    stop_at: datetime | None
    tail_open: bool


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

    async def known_sources(self, session_id: str) -> dict[str, SourceCoverage]:
        """Return every transcript file of a session that a read has taken turns from, by digest, with its coverage."""
        statement = select(db_models.SessionTurnSourceRow).where(
            db_models.SessionTurnSourceRow.session_id == session_id
        )
        async with self._open_session() as db_session:
            rows = (await db_session.exec(statement)).all()
        return {
            row.source_digest: SourceCoverage(
                stop_at=parse_iso_datetime(row.stop_at) if row.stop_at else None, tail_open=row.tail_open
            )
            for row in rows
        }

    async def record_turns(
        self, session_id: str, identities: Sequence[str], sources: Mapping[str, SourceCoverage] | None = None
    ) -> dict[str, int]:
        """Give each identity not yet recorded the next ordinal, in the order given, and return all ordinals.

        An identity that already has an ordinal keeps it, so an ordinal is never rewritten. The files the turns were
        taken from are recorded in the same write, each with how far the session's completions were covered, so a
        file is never known as read without its turns recorded; a later read moves a file's coverage forward and
        never back. Two concurrent recorders of one session meet at the unique ordinal; the loser reads what the
        winner wrote.
        """
        for attempt in range(_RECORD_ATTEMPTS):
            known = await self.known_ordinals(session_id)
            known_sources = await self.known_sources(session_id)
            changed = {
                digest: coverage
                for digest, coverage in (sources or {}).items()
                if digest not in known_sources or _advances(known_sources[digest], coverage)
            }
            fresh = [identity for identity in dict.fromkeys(identities) if identity not in known]
            if not fresh and not changed:
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
                for digest, coverage in changed.items():
                    await db_session.merge(
                        db_models.SessionTurnSourceRow(
                            session_id=session_id,
                            source_digest=digest,
                            created_at=now,
                            stop_at=coverage.stop_at.isoformat() if coverage.stop_at else None,
                            tail_open=coverage.tail_open,
                        )
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


def _advances(recorded: SourceCoverage, read: SourceCoverage) -> bool:
    """Whether a read covers the session's completions further than the record does, or settles an open tail."""
    if recorded.stop_at is None:
        return read.stop_at is not None or read.tail_open != recorded.tail_open
    if read.stop_at is None:
        return False
    return read.stop_at > recorded.stop_at or (
        read.stop_at == recorded.stop_at and read.tail_open != recorded.tail_open
    )
