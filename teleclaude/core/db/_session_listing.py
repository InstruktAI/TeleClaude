"""Listing selection and recorded-subject backfill queries."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, text, update
from sqlmodel import select

from teleclaude.identity_reach import Reach

from .. import db_models
from ..models import JsonDict, Session
from ..models._types import to_json_dict
from ._base import DbBase
from ._session_retention import not_archive_record

_PROJECT_SUBJECT_PATTERN = "project:%"
_SESSION_SUBJECT_COLUMN = "sessions.config_subject"
_SESSION_SUBJECT_OWNER_COLUMN = "sessions.subject_owner"
_SESSION_PRINCIPAL_COLUMN = "sessions.principal"
_JSON_SERIALIZATION_MODE = "json"


@dataclass(frozen=True)
class SessionRecordFound:
    """The session's stored values, read under the caller's reach."""

    values: JsonDict


@dataclass(frozen=True)
class SessionRecordOutsideReach:
    """The session exists but the caller's reach does not admit it."""


@dataclass(frozen=True)
class SessionRecordAbsent:
    """No session carries the id."""


type SessionRecordRead = SessionRecordFound | SessionRecordOutsideReach | SessionRecordAbsent


class DbSessionListingMixin(DbBase):
    """Store queries dedicated to bounded session listings."""

    async def get_active_sessions(self) -> list[Session]:
        """Get active sessions ordered by last activity."""
        statement = (
            select(db_models.Session)
            .where(
                db_models.Session.closed_at.is_(None),
                db_models.Session.deleted_at.is_(None),
                db_models.Session.lifecycle_status == "active",
            )
            .order_by(db_models.Session.last_activity.desc())
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
        return [self._to_core_session(row) for row in rows]

    async def list_sessions_working_items(self, roles: Collection[str]) -> list[Session]:
        """Every undeleted session of the given roles that works a named item, open or closed, of any age."""
        statement = select(db_models.Session).where(
            db_models.Session.deleted_at.is_(None),
            db_models.Session.working_slug.is_not(None),
            db_models.Session.role.in_(tuple(roles)),
        )
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
        return [self._to_core_session(row) for row in rows]

    async def select_sessions_for_listing(
        self,
        reach: Reach,
        closed_since: datetime | None,
        session_ids: Collection[str] | None,
    ) -> list[Session]:
        """Select listing rows by identity reach and the active closed-row scope."""
        if session_ids is not None and not session_ids:
            return []

        stmt = select(db_models.Session).where(db_models.Session.deleted_at.is_(None), not_archive_record())
        reach_clause, reach_parameters = reach.sql_predicate(
            subject_col=_SESSION_SUBJECT_COLUMN,
            owner_col=_SESSION_SUBJECT_OWNER_COLUMN,
            principal_col=_SESSION_PRINCIPAL_COLUMN,
        )
        stmt = stmt.where(text(reach_clause).bindparams(**reach_parameters))
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

    async def read_session_record_for_reach(self, reach: Reach, session_id: str) -> SessionRecordRead:
        """Read one stored session row under the same reach predicate listing applies."""
        reach_clause, reach_parameters = reach.sql_predicate(
            subject_col=_SESSION_SUBJECT_COLUMN,
            owner_col=_SESSION_SUBJECT_OWNER_COLUMN,
            principal_col=_SESSION_PRINCIPAL_COLUMN,
        )
        reached_stmt = (
            select(db_models.Session)
            .where(text(reach_clause).bindparams(**reach_parameters))
            .where(db_models.Session.session_id == session_id)
        )
        existence_stmt = select(db_models.Session.session_id).where(db_models.Session.session_id == session_id)

        async with self._session() as db_session:
            reached = (await db_session.exec(reached_stmt)).first()
            if reached is not None:
                return SessionRecordFound(to_json_dict(reached.model_dump(mode=_JSON_SERIALIZATION_MODE)))
            exists = (await db_session.exec(existence_stmt)).first() is not None
        return SessionRecordOutsideReach() if exists else SessionRecordAbsent()

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

    async def list_sessions_without_subject_owner(self) -> list[tuple[str, str]]:
        """List project-subject session rows whose declared owner is unknown."""
        stmt = (
            select(db_models.Session.session_id, db_models.Session.config_subject)
            .where(db_models.Session.config_subject.like(_PROJECT_SUBJECT_PATTERN))
            .where(db_models.Session.subject_owner.is_(None))
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return [
                (session_id, config_subject)
                for session_id, config_subject in result.all()
                if config_subject is not None
            ]

    async def set_session_subject_owner_if_unset(self, session_id: str, subject_owner: str) -> int:
        """Record one resolved owner without overwriting a newer value."""
        stmt = (
            update(db_models.Session)
            .where(db_models.Session.session_id == session_id)
            .where(db_models.Session.subject_owner.is_(None))
            .values(subject_owner=subject_owner)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0
