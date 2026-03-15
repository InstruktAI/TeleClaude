from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from teleclaude.core import db_models
from teleclaude.core.db import Db

pytestmark = pytest.mark.asyncio


async def test_issue_session_token_persists_a_valid_24_hour_token(db: Db) -> None:
    token = await db.issue_session_token("sess-001", "system:sess-001", "admin")

    record = await db.validate_session_token(token)

    assert record is not None
    assert record.session_id == "sess-001"
    assert record.principal == "system:sess-001"
    assert record.role == "admin"
    assert record.issued_at < record.expires_at


async def test_validate_session_token_returns_none_for_expired_rows(db: Db) -> None:
    await db.issue_session_token("sess-001", "system:sess-001", "admin")

    async with db._session() as session:
        result = await session.exec(
            db_models.SessionToken.__table__.select().where(db_models.SessionToken.session_id == "sess-001")
        )
        row = result.first()
        assert row is not None
        token = row[0]
        record = await session.get(db_models.SessionToken, token)
        assert record is not None
        record.expires_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        session.add(record)
        await session.commit()

    assert await db.validate_session_token(token) is None


async def test_revoke_session_tokens_invalidates_all_active_tokens_for_a_session(db: Db) -> None:
    first = await db.issue_session_token("sess-001", "system:sess-001", "admin")
    second = await db.issue_session_token("sess-001", "system:sess-001", "admin")

    await db.revoke_session_tokens("sess-001")

    assert await db.validate_session_token(first) is None
    assert await db.validate_session_token(second) is None
