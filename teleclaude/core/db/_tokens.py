"""Mixin: DbTokensMixin."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from .. import db_models

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class DbTokensMixin:
    async def issue_session_token(self, session_id: str, principal: str, role: str) -> str:
        """Issue a new session token and store it in the ledger.

        Returns the token string (UUID).
        """
        token = str(uuid.uuid4())
        now = datetime.now(UTC)
        issued_at = now.isoformat()
        expires_at = (now + timedelta(hours=24)).isoformat()
        record = db_models.SessionToken(
            token=token,
            session_id=session_id,
            principal=principal,
            role=role,
            issued_at=issued_at,
            expires_at=expires_at,
            revoked_at=None,
        )
        async with self._session() as db_session:
            db_session.add(record)
            await db_session.commit()
        return token

    async def validate_session_token(self, token: str) -> db_models.SessionToken | None:
        """Validate a token against the ledger.

        Returns the SessionToken record if valid (not expired, not revoked), else None.
        """
        from sqlmodel import select

        stmt = select(db_models.SessionToken).where(db_models.SessionToken.token == token)
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            record = result.first()

        if record is None:
            return None

        now_iso = datetime.now(UTC).isoformat()
        if record.expires_at < now_iso:
            return None
        if record.revoked_at is not None:
            return None
        return record

    async def revoke_session_tokens(self, session_id: str) -> None:
        """Revoke all active tokens for a session (called on session close)."""
        from sqlalchemy import update

        now_iso = datetime.now(UTC).isoformat()
        stmt = (
            update(db_models.SessionToken)
            .where(db_models.SessionToken.session_id == session_id)
            .where(db_models.SessionToken.revoked_at.is_(None))  # type: ignore[union-attr]
            .values(revoked_at=now_iso)
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()
