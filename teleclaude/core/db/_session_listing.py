"""Listing selection and recorded-subject backfill queries."""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import or_, update
from sqlmodel import select

from .. import db_models
from ..models import Session
from ._base import DbBase


class DbSessionListingMixin(DbBase):
    """Store queries dedicated to bounded session listings."""

    async def select_sessions_for_listing(
        self,
        subject_tokens: Collection[str] | None,
        closed_since: datetime | None,
        session_ids: Collection[str] | None,
    ) -> list[Session]:
        """Select listing rows by subject and the active closed-row scope."""
        if subject_tokens is not None and not subject_tokens:
            return []
        if session_ids is not None and not session_ids:
            return []

        stmt = select(db_models.Session)
        if subject_tokens is not None:
            stmt = stmt.where(db_models.Session.config_subject.in_(tuple(subject_tokens)))
        if session_ids is not None:
            stmt = stmt.where(db_models.Session.session_id.in_(tuple(session_ids)))
        elif closed_since is None:
            stmt = stmt.where(db_models.Session.closed_at.is_(None))
        else:
            stmt = stmt.where(or_(db_models.Session.closed_at.is_(None), db_models.Session.closed_at >= closed_since))
        stmt = stmt.order_by(db_models.Session.last_activity.desc())

        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return [self._to_core_session(row) for row in result.all()]

    async def list_unattributed_session_locations(self) -> list[tuple[str | None, str | None]]:
        """Return distinct project path and subdirectory pairs without a subject."""
        stmt = (
            select(db_models.Session.project_path, db_models.Session.subdir)
            .where(db_models.Session.config_subject.is_(None))
            .distinct()
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return [(project_path, subdir) for project_path, subdir in result.all()]

    async def set_session_config_subject_if_unset(
        self,
        project_path: str | None,
        subdir: str | None,
        config_subject: str,
    ) -> int:
        """Set one location's missing subject without overwriting a newer value."""
        stmt = (
            update(db_models.Session)
            .where(db_models.Session.project_path.is_(project_path))
            .where(db_models.Session.subdir.is_(subdir))
            .where(db_models.Session.config_subject.is_(None))
            .values(config_subject=config_subject)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0
