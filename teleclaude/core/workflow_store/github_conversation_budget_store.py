"""Persist the fleet master's conversation request budget and the limit notices other computers owe it.

These records are request-runtime plumbing kept in the daemon's operational database, not workflow state: the
master reloads them after a restart so a restart never resets the share it has already spent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core import db_models
from teleclaude.core.dates import parse_iso_datetime

type SessionOpener = Callable[[], SqlAsyncSession]

_BUDGET_ROW_ID = 1


@dataclass(frozen=True)
class PauseState:
    """When conversation requests may resume, and how many limit responses in a row named no time."""

    pause_until: datetime | None
    unnamed_limits: int


@dataclass(frozen=True)
class LimitNotice:
    """A limit response this computer received, to be told to the fleet master."""

    notice_id: int
    observed_at: datetime
    resume_at: datetime | None


class ConversationBudgetStore:
    """Read and write the budget records through an injected session opener."""

    def __init__(self, open_session: SessionOpener) -> None:
        self._open_session = open_session

    async def record_send(self, sent_at: datetime) -> None:
        """Record one append the master sent."""
        async with self._open_session() as db_session:
            db_session.add(db_models.GitHubConversationSendRow(sent_at=sent_at.isoformat()))
            await db_session.commit()

    async def sends_since(self, since: datetime) -> list[datetime]:
        """The times of the appends sent at or after ``since``, oldest first; older ones are forgotten."""
        async with self._open_session() as db_session:
            await db_session.exec(
                delete(db_models.GitHubConversationSendRow).where(
                    col(db_models.GitHubConversationSendRow.sent_at) < since.isoformat()
                )
            )
            await db_session.commit()
            rows = (
                await db_session.exec(
                    select(db_models.GitHubConversationSendRow).order_by(
                        col(db_models.GitHubConversationSendRow.sent_at)
                    )
                )
            ).all()
        return [parsed for row in rows if (parsed := parse_iso_datetime(row.sent_at)) is not None]

    async def pause_state(self) -> PauseState:
        """The current pause, or none."""
        async with self._open_session() as db_session:
            row = await db_session.get(db_models.GitHubConversationBudgetRow, _BUDGET_ROW_ID)
        if row is None:
            return PauseState(pause_until=None, unnamed_limits=0)
        return PauseState(pause_until=parse_iso_datetime(row.pause_until), unnamed_limits=row.unnamed_limits)

    async def save_pause_state(self, state: PauseState) -> None:
        """Replace the pause state."""
        async with self._open_session() as db_session:
            row = await db_session.get(db_models.GitHubConversationBudgetRow, _BUDGET_ROW_ID)
            if row is None:
                row = db_models.GitHubConversationBudgetRow(id=_BUDGET_ROW_ID)
            row.pause_until = state.pause_until.isoformat() if state.pause_until is not None else None
            row.unnamed_limits = state.unnamed_limits
            db_session.add(row)
            await db_session.commit()

    async def add_notice(self, observed_at: datetime, resume_at: datetime | None) -> None:
        """Keep a limit response until the master has been told of it."""
        async with self._open_session() as db_session:
            db_session.add(
                db_models.GitHubRateLimitNoticeRow(
                    observed_at=observed_at.isoformat(),
                    resume_at=resume_at.isoformat() if resume_at is not None else None,
                )
            )
            await db_session.commit()

    async def undelivered_notices(self, now: datetime) -> list[LimitNotice]:
        """The notices not yet delivered and not yet obsolete: one that names a time already passed is dropped."""
        async with self._open_session() as db_session:
            rows = (
                await db_session.exec(
                    select(db_models.GitHubRateLimitNoticeRow)
                    .where(col(db_models.GitHubRateLimitNoticeRow.delivered_at).is_(None))
                    .order_by(col(db_models.GitHubRateLimitNoticeRow.id))
                )
            ).all()
            notices: list[LimitNotice] = []
            for row in rows:
                observed_at = parse_iso_datetime(row.observed_at)
                resume_at = parse_iso_datetime(row.resume_at)
                if observed_at is None or row.id is None:
                    continue
                if resume_at is not None and resume_at <= now:
                    row.delivered_at = now.astimezone(UTC).isoformat()
                    db_session.add(row)
                    continue
                notices.append(LimitNotice(notice_id=row.id, observed_at=observed_at, resume_at=resume_at))
            await db_session.commit()
        return notices

    async def mark_notice_delivered(self, notice_id: int, delivered_at: datetime) -> None:
        """Record that the master has been told of a notice."""
        async with self._open_session() as db_session:
            row = await db_session.get(db_models.GitHubRateLimitNoticeRow, notice_id)
            if row is not None:
                row.delivered_at = delivered_at.isoformat()
                db_session.add(row)
                await db_session.commit()
