"""Mixin: DbTokensMixin."""

import uuid
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from sqlmodel import select

from .. import db_models

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class DbTokensMixin:
    """Session token issuance and revocation helpers."""

    async def issue_session_token(self, session_id: str, principal: str, role: str) -> str:
        """Issue a new session token and store it in the ledger.

        Returns the token string (UUID).
        """
        token = str(uuid.uuid4())
        record = db_models.SessionToken(
            token=token,
            session_id=session_id,
            principal=principal,
            role=role,
        )
        async with self._session() as db_session:
            db_session.add(record)
            await db_session.commit()
        return token

    async def validate_session_token(self, token: str) -> db_models.SessionToken | None:
        """Validate a token against the ledger.

        Returns the SessionToken record if it exists, else None.
        Token lifetime is controlled exclusively by deletion on session close.
        """
        stmt = select(db_models.SessionToken).where(db_models.SessionToken.token == token)
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return result.first()

    async def revoke_session_tokens(self, session_id: str) -> None:
        """Delete all tokens for a session (called on session close)."""
        async with self._session() as db_session:
            stmt = select(db_models.SessionToken).where(db_models.SessionToken.session_id == session_id)
            result = await db_session.exec(stmt)
            for token_record in result.all():
                await db_session.delete(token_record)
            await db_session.commit()
